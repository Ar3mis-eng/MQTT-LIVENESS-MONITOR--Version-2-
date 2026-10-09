"""READ-ONLY MQTT client wrapper.

SAFETY CONTRACT (enforced in code, not just by convention)
----------------------------------------------------------
* The underlying paho client's ``publish`` attribute is REPLACED with a
  function that raises :class:`PublishForbiddenError`.  Even if a future
  developer reaches for ``self._client.publish(...)``, it cannot send.
* This module exposes no ``publish`` method of its own.
* A unique client id (``ojt-g1-monitor``) is used — never a device id.
* Credentials come exclusively from a :class:`BrokerProfile`.

The wrapper runs paho's network loop in its own thread; the GUI
marshals to the Qt main thread itself (see ``app/gui``).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import paho.mqtt.client as mqtt

from ..config.models import BrokerProfile, ConnectionState

log = logging.getLogger(__name__)

# Unique application client id. NEVER use a PLC/HMI/device client id.
CLIENT_ID = "ojt-g1-monitor"

RECONNECT_MIN_DELAY_S = 1
RECONNECT_MAX_DELAY_S = 30


class PublishForbiddenError(RuntimeError):
    """Raised if anything attempts to publish through this application."""


def _forbidden_publish(*_args: object, **_kwargs: object) -> None:
    raise PublishForbiddenError(
        "THIS APPLICATION IS READ-ONLY: publishing to the broker is forbidden."
    )


@dataclass
class MqttMessage:
    """One received application message."""

    topic: str
    payload: bytes
    retain: bool
    qos: int
    rx_time: float  # time.time() when the client callback fired
    _text: str | None = field(default=None, repr=False)

    @property
    def text(self) -> str:
        """Decoded payload text (cached, decoded once)."""
        if self._text is None:
            self._text = self.payload.decode("utf-8", errors="replace")
        return self._text


MessageHandler = Callable[[MqttMessage], None]
StateHandler = Callable[[ConnectionState, str], None]


class ReadOnlyMqttClient:
    """Subscribe-only MQTT client with automatic reconnect.

    Exposes: ``connect()``, ``disconnect()``, ``subscribe()``,
    message/state callback registration.  Deliberately does NOT expose
    ``publish()``.
    """

    def __init__(
        self,
        on_message: MessageHandler | None = None,
        on_state: StateHandler | None = None,
        client_id: str = CLIENT_ID,
    ) -> None:
        self._client_id = client_id
        self._on_message_cb = on_message
        self._on_state_cb = on_state
        self._state = ConnectionState.DISCONNECTED
        self._state_detail = ""
        self._want_connection = False
        self._subscribed_topics: list[str] = []
        self._lock = threading.RLock()
        self._reconnect_thread: threading.Thread | None = None

        # paho v2 callback API with fallback for v1 installs.
        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):  # pragma: no cover - paho 1.x
            self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        # ---- HARD READ-ONLY ENFORCEMENT -------------------------------
        self._client.publish = _forbidden_publish  # type: ignore[method-assign]
        # -------------------------------------------------------------

        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_message
        self._client.reconnect_delay_set(
            min_delay=RECONNECT_MIN_DELAY_S, max_delay=RECONNECT_MAX_DELAY_S
        )
        self._client.keepalive = 30

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def state_detail(self) -> str:
        return self._state_detail

    @property
    def client_id(self) -> str:
        return self._client_id

    # ------------------------------------------------------------------
    # Public API (safe / read-only)
    # ------------------------------------------------------------------
    def set_on_message(self, cb: MessageHandler | None) -> None:
        self._on_message_cb = cb

    def connect(self, profile: BrokerProfile) -> bool:
        """Start connecting (non-blocking). Auto-reconnect stays active."""
        errors = profile.validate()
        if errors:
            raise ValueError("; ".join(errors))
        try:
            with self._lock:
                self._want_connection = True
                self._set_state(ConnectionState.CONNECTING, profile.masked)
            if profile.username:
                self._client.username_pw_set(profile.username, profile.password or None)
            else:
                self._client.username_pw_set(None, None)
            # connect_async + loop_start: never blocks the calling (GUI) thread.
            self._client.connect_async(profile.host, profile.port, keepalive=30)
            self._client.loop_start()
            log.info(
                "Connecting to %s with client id %r (read-only)",
                profile.masked,
                self._client_id,
            )
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_state(ConnectionState.ERROR, f"connect setup failed: {exc}")
            log.exception("MQTT connect setup failed for %s:%s", profile.host, profile.port)
            return False

    def disconnect(self) -> None:
        """User-requested disconnect: disables auto-reconnect."""
        with self._lock:
            self._want_connection = False
        try:
            self._client.disconnect()
        except Exception as exc:
            log.warning("disconnect() raised: %s", exc)
        self._client.loop_stop()
        self._set_state(ConnectionState.DISCONNECTED, "user disconnect")
        log.info("Disconnected (user requested)")

    def subscribe(self, topic_filter: str) -> None:
        """Subscribe to a topic filter (e.g. ``#``). Read-only operation."""
        with self._lock:
            if topic_filter not in self._subscribed_topics:
                self._subscribed_topics.append(topic_filter)
        if self._state == ConnectionState.CONNECTED:
            self._client.subscribe(topic_filter, qos=0)

    def unsubscribe_all(self) -> None:
        with self._lock:
            filters = list(self._subscribed_topics)
            self._subscribed_topics.clear()
        for f in filters:
            try:
                self._client.unsubscribe(f)
            except Exception as exc:
                log.warning("unsubscribe(%s) failed: %s", f, exc)

    def unsubscribe(self, topic_filter: str) -> None:
        """Remove one read-only subscription filter."""
        with self._lock:
            if topic_filter not in self._subscribed_topics:
                return
            self._subscribed_topics.remove(topic_filter)
        if self._state == ConnectionState.CONNECTED:
            try:
                self._client.unsubscribe(topic_filter)
            except Exception as exc:
                log.warning("unsubscribe(%s) failed: %s", topic_filter, exc)

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        changed = state != self._state or detail != self._state_detail
        self._state, self._state_detail = state, detail
        if changed and self._on_state_cb is not None:
            try:
                self._on_state_cb(state, detail)
            except Exception:  # pragma: no cover - never kill the network thread
                log.exception("on_state callback failed")

    # ------------------------------------------------------------------
    # paho callbacks (run on the paho network thread)
    # ------------------------------------------------------------------
    def _handle_connect(self, client: object, userdata: object, *args: object) -> None:
        rc = _extract_rc(args)
        if rc != 0:
            self._set_state(ConnectionState.ERROR, f"connect refused (code {rc})")
            log.error("Broker refused connection: code %s", rc)
            return
        with self._lock:
            filters = list(self._subscribed_topics)
        for f in filters:
            client.subscribe(f, qos=0)  # type: ignore[attr-defined]
        self._set_state(ConnectionState.CONNECTED, "subscribed: " + ", ".join(filters))
        log.info("Connected to broker; (re)subscribed to %s", filters or "[]")

    def _handle_disconnect(self, client: object, userdata: object, *args: object) -> None:
        rc = _extract_rc(args, offset=1 if len(args) >= 3 else 0)
        if not self._want_connection:
            self._set_state(ConnectionState.DISCONNECTED, "user disconnect")
            return
        detail = "connection lost" if rc == 0 else f"connection lost (code {rc})"
        self._set_state(ConnectionState.RECONNECTING, detail)
        log.warning("%s — auto-reconnect active", detail)
        self._ensure_reconnect_watchdog()

    def _handle_message(self, client: object, userdata: object, msg: object) -> None:
        topic = getattr(msg, "topic", "")
        try:
            m = MqttMessage(
                topic=str(topic),
                payload=bytes(getattr(msg, "payload", b"")),
                retain=bool(getattr(msg, "retain", False)),
                qos=int(getattr(msg, "qos", 0)),
                rx_time=time.time(),
            )
        except Exception:  # pragma: no cover
            log.exception("Failed to wrap message on topic %r", topic)
            return
        if self._on_message_cb is not None:
            try:
                self._on_message_cb(m)
            except Exception:
                # A malformed payload must NEVER crash the application.
                log.exception("on_message handler failed for topic %r", topic)

    # ------------------------------------------------------------------
    # Reconnect watchdog (single instance — no parallel reconnect loops)
    # ------------------------------------------------------------------
    def _ensure_reconnect_watchdog(self) -> None:
        with self._lock:
            if not self._want_connection:
                return
            if self._reconnect_thread is not None and self._reconnect_thread.is_alive():
                return
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop, name="mqtt-reconnect", daemon=True
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        delay = float(RECONNECT_MIN_DELAY_S)
        while True:
            with self._lock:
                if not self._want_connection:
                    return
                if self._state == ConnectionState.CONNECTED:
                    return
            try:
                self._client.reconnect()
                log.info("Reconnect attempt succeeded (backoff was %.0fs)", delay)
                return
            except (socket.error, OSError) as exc:
                log.warning("Reconnect failed: %s; retrying in %.0fs", exc, delay)
                self._set_state(
                    ConnectionState.RECONNECTING, f"retry in {delay:.0f}s ({exc})"
                )
                time.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY_S)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("Unexpected reconnect error: %s", exc)
                time.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY_S)


def _extract_rc(args: tuple[object, ...], offset: int = 0) -> int:
    """Normalize paho v1/v2 callback rc/reason_code arguments to an int."""
    if len(args) <= offset:
        return 0
    val = args[offset]
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    value = getattr(val, "value", None)  # paho v2 ReasonCode
    if isinstance(value, int):
        return value
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def get_local_ip() -> str:
    """Best-effort laptop IP address (UDP connect sends no packets)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.2)
        s.connect(("192.168.50.11", 1883))  # route lookup only
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()
