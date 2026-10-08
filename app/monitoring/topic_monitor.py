"""The class-specific liveness engine.

This is the most important module in the application.  Each topic is
evaluated according to its CLASS, expected period, retain flag, payload
timestamp, payload quality and heartbeat counter — never a single
generic timeout.

Thread-safety: ``TopicMonitor.ingest()`` is called from the MQTT network
thread; ``evaluate()/snapshot()`` are called from the GUI timer thread.
A plain ``threading.Lock`` guards all shared state.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ..config.models import MonitorSettings, TopicClass, TopicConfig, TopicState
from ..mqtt.client import MqttMessage
from .payload import ParsedPayload, parse_payload
from .states import StateChange, transition

log = logging.getLogger(__name__)

# Heartbeat counter behaviour labels shown in the UI.
COUNTER_OK = "increasing"
COUNTER_UNVERIFIED = "awaiting increasing counter"
COUNTER_STUCK = "STUCK"
COUNTER_BACKWARDS = "BACKWARDS"
COUNTER_RESET = "RESTARTED?"  # large backwards jump (device rebooted)

_BACKWARDS_RESET_THRESHOLD = 100  # drop larger than this => probable restart


@dataclass
class TopicRuntime:
    """Live state for one configured topic."""

    config: TopicConfig
    # Timing (wall-clock seconds, time.time()).
    last_rx: float | None = None  # arrival time of the latest message
    last_payload_ts: float | None = None  # ts inside the payload, if any
    last_retain: bool = False
    last_state: str = ""  # normalized connection token (ONLINE/OFFLINE/...)
    last_quality: str | None = None
    quality_known: bool = True
    last_value: Any = None
    first_seen_iso: str = ""
    # Freshness anchor: min(rx, payload ts) for retained messages so an
    # old retained snapshot cannot masquerade as fresh data.
    fresh_anchor: float | None = None
    # Heartbeat counter tracking.
    counter_prev: float | None = None
    counter_behavior: str = ""
    counter_verified: bool = False
    # Interval statistics (non-retained messages only).
    interval_last: float | None = None
    interval_min: float | None = None
    interval_max: float | None = None
    interval_sum: float = 0.0
    interval_count: int = 0
    _last_interval_anchor: float | None = field(default=None, repr=False)
    # State.
    state: TopicState = TopicState.NEVER_SEEN
    state_reason: str = "no message received yet"
    state_changed_mono: float = field(default_factory=time.monotonic)
    # 60 s activity strip: (mono_ts of hit) entries, pruned on read.
    activity: deque[float] = field(default_factory=lambda: deque(maxlen=512))
    # Last N messages for the detail panel: (iso, topic, payload, retain).
    recent: deque[tuple[str, str, bool]] = field(default_factory=lambda: deque(maxlen=20))
    msg_count: int = 0

ChangeCallback = Callable[[StateChange], None]


class TopicMonitor:
    """Aggregates configured topics, ingests messages, evaluates states.

    ``on_change`` is invoked (outside the lock) whenever a topic's state
    changes, so the state-change logger can persist it.
    """

    def __init__(
        self,
        settings: MonitorSettings,
        on_change: ChangeCallback | None = None,
    ) -> None:
        self._settings = settings
        self._on_change = on_change
        self._lock = threading.RLock()
        self._topics: dict[str, TopicRuntime] = {}
        self._configs: dict[str, TopicConfig] = {}
        # entity -> connection topic (for on_change source-device lookup)
        self._entity_conn: dict[str, str] = {}
        self._stale_mult = settings.heartbeat_stale_multiplier
        self._dead_mult = settings.heartbeat_dead_multiplier
        self._p_stale_mult = settings.periodic_stale_multiplier
        self._p_dead_mult = settings.periodic_dead_multiplier

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def set_settings(self, settings: MonitorSettings) -> None:
        with self._lock:
            self._settings = settings
            self._stale_mult = settings.heartbeat_stale_multiplier
            self._dead_mult = settings.heartbeat_dead_multiplier
            self._p_stale_mult = settings.periodic_stale_multiplier
            self._p_dead_mult = settings.periodic_dead_multiplier

    def set_topics(self, configs: Iterable[TopicConfig]) -> None:
        """Replace the configured topic set, preserving runtime data."""
        with self._lock:
            new_configs: dict[str, TopicConfig] = {}
            for c in configs:
                new_configs[c.topic] = c
            self._configs = new_configs
            for t in [t for t in self._topics if t not in new_configs]:
                del self._topics[t]
            for topic, cfg in new_configs.items():
                if topic not in self._topics:
                    self._topics[topic] = TopicRuntime(config=cfg)
                else:
                    self._topics[topic].config = cfg
            self._entity_conn = {
                c.entity: c.topic
                for c in new_configs.values()
                if c.topic_class == TopicClass.CONNECTION and c.entity
            }
        log.info("Monitor configured with %d topics", len(new_configs))

    # ------------------------------------------------------------------
    # Ingestion (called from MQTT network thread)
    # ------------------------------------------------------------------
    def ingest(self, msg: MqttMessage, parsed: ParsedPayload | None = None) -> None:
        """Record one received message against its configured topic."""
        with self._lock:
            rt = self._topics.get(msg.topic)
            if rt is None:
                return  # not configured — discovery/discovery-only traffic
            if parsed is None:
                parsed = parse_payload(msg.text)
            self._ingest_locked(rt, msg, parsed)

    def _ingest_locked(
        self, rt: TopicRuntime, msg: MqttMessage, parsed: ParsedPayload
    ) -> None:
        now = msg.rx_time

        # ---- freshness anchor -----------------------------------------
        payload_ts = parsed.ts.timestamp() if parsed.ts else None
        # An old payload timestamp (retained snapshot) must not count as
        # fresh; freshness is bounded by min(now, payload ts).
        anchor = min(now, payload_ts) if payload_ts is not None else now
        rt.last_rx = now
        rt.last_payload_ts = payload_ts
        rt.last_retain = msg.retain
        rt.last_value = parsed.value
        rt.last_quality = parsed.quality
        rt.quality_known = parsed.quality_known
        conn = parsed.is_online
        rt.last_state = "" if conn is None else ("ONLINE" if conn else "OFFLINE")
        rt.fresh_anchor = anchor
        rt.msg_count += 1
        if not rt.first_seen_iso:
            rt.first_seen_iso = (
                datetime.fromtimestamp(now, tz=timezone.utc)
                .astimezone()
                .isoformat(timespec="seconds")
            )
        rt.activity.append(time.monotonic())
        stamp = (
            datetime.fromtimestamp(now, tz=timezone.utc)
            .astimezone()
            .strftime("%H:%M:%S.%f")[:-3]
        )
        rt.recent.append((stamp, msg.text[:300], msg.retain))

        # ---- interval statistics (live messages only) ------------------
        if not msg.retain:
            if rt._last_interval_anchor is not None:
                gap = now - rt._last_interval_anchor
                if 0 <= gap <= 3600:
                    rt.interval_last = gap
                    rt.interval_sum += gap
                    rt.interval_count += 1
                    rt.interval_min = (
                        gap if rt.interval_min is None else min(rt.interval_min, gap)
                    )
                    rt.interval_max = (
                        gap if rt.interval_max is None else max(rt.interval_max, gap)
                    )
            rt._last_interval_anchor = now



        # ---- heartbeat counter ------------------------------------------
        if (
            rt.config.topic_class == TopicClass.HEARTBEAT
            and isinstance(parsed.value, (int, float))
            and not isinstance(parsed.value, bool)
        ):
            v = float(parsed.value)
            if rt.counter_prev is None:
                rt.counter_behavior = COUNTER_UNVERIFIED
            elif v > rt.counter_prev:
                rt.counter_behavior = COUNTER_OK
                if not msg.retain:
                    rt.counter_verified = True
            elif v == rt.counter_prev:
                rt.counter_behavior = COUNTER_STUCK
                rt.counter_verified = False
            else:
                drop = rt.counter_prev - v
                rt.counter_behavior = (
                    COUNTER_RESET
                    if drop > _BACKWARDS_RESET_THRESHOLD
                    else COUNTER_BACKWARDS
                )
                rt.counter_verified = False
            rt.counter_prev = v

    # ------------------------------------------------------------------
    # Evaluation (called from GUI timer)
    # ------------------------------------------------------------------
    def evaluate(self) -> list[StateChange]:
        """Recalculate every topic state; return the list of changes."""
        changes: list[StateChange] = []
        now = time.time()
        with self._lock:
            for rt in self._topics.values():
                new_state, reason = self._evaluate_one(rt, now)
                new_state = transition(rt.state, new_state)
                if new_state != rt.state:
                    prev = rt.state
                    rt.state = new_state
                    rt.state_reason = reason
                    rt.state_changed_mono = time.monotonic()
                    changes.append(
                        StateChange(
                            timestamp_iso=datetime.now(timezone.utc)
                            .astimezone()
                            .isoformat(timespec="seconds"),
                            topic=rt.config.topic,
                            short_name=rt.config.short_name,
                            entity=rt.config.entity,
                            tier=rt.config.tier,
                            previous=prev,
                            new=new_state,
                            reason=reason,
                        )
                    )
                else:
                    rt.state_reason = reason
        if self._on_change is not None:
            for ch in changes:
                try:
                    self._on_change(ch)
                except Exception:  # pragma: no cover
                    log.exception("state-change callback failed")
        return changes


    # ------------------------------------------------------------------
    # Class-specific rules (the heart of the liveness engine)
    # ------------------------------------------------------------------
    def _evaluate_one(self, rt: TopicRuntime, now: float) -> tuple[TopicState, str]:
        cfg = rt.config
        cls = cfg.topic_class

        if rt.last_rx is None:
            return TopicState.NEVER_SEEN, "no message received yet"

        # Age from the freshness anchor: a retained snapshot carries its
        # payload timestamp, so an old retained message is judged old.
        anchor = rt.fresh_anchor if rt.fresh_anchor is not None else rt.last_rx
        age = max(0.0, now - anchor)

        if cls == TopicClass.CONNECTION:
            return self._eval_connection(rt, age)
        if cls == TopicClass.HEARTBEAT:
            return self._eval_heartbeat(rt, age)
        if cls == TopicClass.PERIODIC:
            return self._eval_periodic(rt, age)
        if cls == TopicClass.ON_CHANGE:
            return self._eval_on_change(rt, age)
        if cls == TopicClass.COMMAND:
            return self._eval_command(rt, age)
        return TopicState.ALIVE, f"unhandled class {cls}"  # pragma: no cover

    def _eval_connection(self, rt: TopicRuntime, age: float) -> tuple[TopicState, str]:
        """ONLINE + good quality => ALIVE; OFFLINE => DEAD (even retained)."""
        if rt.last_state == "OFFLINE":
            when = "retained OFFLINE" if rt.last_retain else "latest value OFFLINE"
            return TopicState.DEAD, f"{when}; source device reports OFFLINE"
        if rt.last_quality == "BAD":
            return (
                TopicState.BAD_QUALITY,
                f"quality=BAD (value={rt.last_state or rt.last_value!r})",
            )
        if rt.last_state == "ONLINE":
            if rt.last_retain:
                return TopicState.STALE, "ONLINE received as retained snapshot; live connection not verified"
            suffix = ""
            return TopicState.ALIVE, f"ONLINE{suffix}"
        # Unrecognised payload: light freshness judgement, never DEAD by age.
        if age > 60:
            return TopicState.STALE, f"unrecognised value; silent {age:.0f}s"
        return TopicState.ALIVE, f"value={rt.last_value!r} (unrecognised)"


    def _eval_heartbeat(self, rt: TopicRuntime, age: float) -> tuple[TopicState, str]:
        """ALIVE only within stale threshold AND counter increasing."""
        period = rt.config.period_s or 2.0
        stale_at = self._stale_mult * period
        dead_at = max(self._dead_mult * period, stale_at + 1.0)
        if rt.last_quality == "BAD":
            return TopicState.BAD_QUALITY, "quality=BAD on heartbeat"
        if age > dead_at:
            return TopicState.DEAD, (
                f"no heartbeat for {age:.1f}s (dead after {dead_at:.1f}s = "
                f"{self._dead_mult:g}x period)"
            )
        if age > stale_at:
            return TopicState.STALE, (
                f"no heartbeat for {age:.1f}s (stale after {stale_at:.1f}s = "
                f"{self._stale_mult:g}x period)"
            )
        if rt.counter_behavior in (COUNTER_STUCK, COUNTER_BACKWARDS, COUNTER_RESET):
            # Messages may still arrive, but the counter is abnormal:
            # never report ALIVE (spec: do not judge heartbeat on time alone).
            if age > dead_at:
                return TopicState.DEAD, (
                    f"counter {rt.counter_behavior} and silent {age:.1f}s "
                    f"(> {dead_at:.1f}s)"
                )
            return TopicState.STALE, (
                f"heartbeat counter {rt.counter_behavior} at {rt.counter_prev}"
            )
        if not rt.counter_verified:
            return TopicState.STALE, (
                f"heartbeat counter {rt.counter_behavior or COUNTER_UNVERIFIED}; "
                "waiting for a live increase"
            )
        return TopicState.ALIVE, f"heartbeat {age:.1f}s ago; counter increasing"

    def _eval_periodic(self, rt: TopicRuntime, age: float) -> tuple[TopicState, str]:
        """ALIVE within 3x period AND quality GOOD; else STALE/DEAD."""
        period = rt.config.period_s or 1.0
        stale_at = self._p_stale_mult * period
        dead_at = max(self._p_dead_mult * period, stale_at + 1.0)
        if age > dead_at:
            return TopicState.DEAD, (
                f"no message for {age:.1f}s (dead after {dead_at:.1f}s = "
                f"{self._p_dead_mult:g}x period)"
            )
        if age > stale_at:
            return TopicState.STALE, (
                f"no message for {age:.1f}s (stale after {stale_at:.1f}s = "
                f"{self._p_stale_mult:g}x period)"
            )
        if rt.last_quality == "BAD":
            return TopicState.BAD_QUALITY, "quality=BAD on periodic telemetry"
        if rt.last_retain:
            return TopicState.STALE, "retained snapshot; live telemetry not verified"
        return TopicState.ALIVE, f"message {age:.1f}s ago; quality GOOD"

    def _eval_on_change(self, rt: TopicRuntime, age: float) -> tuple[TopicState, str]:
        """Never times out by age. Depends on value + source connection."""
        if rt.last_state == "OFFLINE":
            return TopicState.DEAD, (
                "retained OFFLINE" if rt.last_retain else "value OFFLINE"
            )
        if rt.last_quality == "BAD":
            return TopicState.BAD_QUALITY, "quality=BAD on state topic"
        if rt.last_retain:
            return TopicState.STALE, (
                f"retained snapshot ({age:.0f}s informational age); live update not verified"
            )
        # Source device connection check (entity -> connection topic).
        conn_topic = self._entity_conn.get(rt.config.entity)
        if conn_topic and conn_topic != rt.config.topic:
            conn_rt = self._topics.get(conn_topic)
            if conn_rt is not None and conn_rt.last_state == "OFFLINE":
                return TopicState.DEAD, (
                    f"source entity {rt.config.entity!r} connection is OFFLINE"
                )
        return TopicState.ALIVE, (
            f"state value held {age:.0f}s (event-driven; age is informational)"
        )

    def _eval_command(self, rt: TopicRuntime, age: float) -> tuple[TopicState, str]:
        """Event-driven: NEVER judged by age."""
        if rt.last_quality == "BAD":
            return TopicState.BAD_QUALITY, "quality=BAD on observed command"
        return TopicState.ALIVE, (
            f"last command {age:.0f}s ago (event-driven; not age-checked)"
        )

    # ------------------------------------------------------------------
    # Snapshot API (GUI reads)
    # ------------------------------------------------------------------
    def snapshot(self) -> list[TopicRuntime]:
        """Return the list of runtimes for rendering (do not mutate)."""
        with self._lock:
            return list(self._topics.values())

    def activity_strip(self, rt: TopicRuntime, window_s: int = 60) -> str:
        """Render the last ``window_s`` seconds as a compact strip.

        One character per second, e.g. ``| | | ||  | |``.  O(window).
        """
        now_m = time.monotonic()
        cutoff = now_m - window_s
        hits = [0] * window_s
        for ts in rt.activity:
            if ts < cutoff:
                continue
            idx = window_s - 1 - int(now_m - ts)
            if 0 <= idx < window_s:
                hits[idx] += 1
        chars = []
        for h in hits:
            if h == 0:
                chars.append(" ")
            elif h == 1:
                chars.append("|")
            elif h < 5:
                chars.append("‖")
            else:
                chars.append("█")
        return "".join(chars)

    def device_summary(self) -> dict[str, tuple[TopicState, int]]:
        """entity -> (worst state across its topics, topic count)."""
        summary: dict[str, tuple[TopicState, int]] = {}
        with self._lock:
            for rt in self._topics.values():
                ent = rt.config.entity or "(unassigned)"
                worst, count = summary.get(ent, (TopicState.ALIVE, 0))
                if rt.state.severity < worst.severity:
                    worst = rt.state
                summary[ent] = (worst, count + 1)
        return summary
