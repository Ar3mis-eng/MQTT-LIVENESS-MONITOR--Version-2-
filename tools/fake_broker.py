"""Local fake publishers for testing WITHOUT the plant broker.

Uses a local Mosquitto broker (default 127.0.0.1:1883).  Run a local
broker first, e.g.::

    mosquitto -p 1883 -v

Then::

    python tools/fake_broker.py --scenario demo

Scenarios exercise the full acceptance arc:
  ALIVE -> (stop) -> STALE -> DEAD -> (restart) -> ALIVE,
plus retained OFFLINE shown as DEAD, BAD quality, and command topics
that never time out.

SAFETY: defaults to 127.0.0.1.  Refuses the plant broker
192.168.50.11 unless --i-understand-this-is-live is passed (and even
then, prefer never to run fakes against plant equipment).
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time

try:
    from paho.mqtt import client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None  # type: ignore[assignment]

PLANT_HOST = "192.168.50.11"
BASE = "exhaust-system/main"
STOP = threading.Event()


def _payload(value, quality: str = "GOOD") -> str:
    return json.dumps({"value": value, "ts": time.time(), "quality": quality})


def _client(host: str, port: int, cid: str):
    if mqtt is None:
        raise SystemExit("paho-mqtt is not installed (pip install -r requirements.txt)")
    try:
        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=cid, protocol=mqtt.MQTTv311)
    except (AttributeError, TypeError):
        c = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311)
    c.connect(host, port, keepalive=30)
    c.loop_start()
    return c


def _pub(c, topic: str, payload: str, retain: bool = False) -> None:
    c.publish(topic, payload, qos=0, retain=retain)


def _loop(c, topic: str, period: float, make_value, quality: str = "GOOD",
          retain: bool = False, stop: threading.Event = STOP) -> None:
    i = 0
    while not stop.is_set():
        _pub(c, topic, _payload(make_value(i), quality), retain=retain)
        i += 1
        stop.wait(period)


def run_demo(host: str, port: int) -> int:
    print(f"[fake] connecting to LOCAL test broker {host}:{port}")
    c = _client(host, port, "ojt-g1-fake-pub")
    counter = {"hb": 1040}

    threads = [
        # PLC connection (retained ONLINE).
        threading.Thread(target=_loop, daemon=True, args=(c, f"{BASE}/panel/state/plc-connection", 5.0, lambda i: "ONLINE"),
                         kwargs={"retain": True}),
        # PLC heartbeat counter every 2 s.
        threading.Thread(target=lambda: _hb_loop(c), daemon=True),
        # Airflow periodic every 0.5 s.
        threading.Thread(target=_loop, daemon=True, args=(c, f"{BASE}/controller/telemetry/airflow", 0.5, lambda i: round(31.0 + (i % 20) * 0.1, 1))),
        # Damper position periodic every 1 s.
        threading.Thread(target=_loop, daemon=True, args=(c, f"{BASE}/damper/telemetry/position", 1.0, lambda i: 72 + (i % 3))),
        # System run state (retained, on_change).
        threading.Thread(target=_loop, daemon=True, args=(c, f"{BASE}/system/run-state", 15.0, lambda i: "RUN"),
                         kwargs={"retain": True}),
        # VFD speed that goes BAD quality every ~30 s.
        threading.Thread(target=lambda: _badq_loop(c), daemon=True),
        # Command echo (event-driven): emits once a minute so the terminal shows it.
        threading.Thread(target=_loop, daemon=True, args=(c, f"{BASE}/panel/cmd/damper-open", 60.0, lambda i: 1)),
    ]

    def _hb_loop(c):
        i = 1040
        while not STOP.is_set():
            _pub(c, f"{BASE}/panel/state/plc-heartbeat", _payload(i))
            i += 1
            STOP.wait(2.0)

    def _badq_loop(c):
        i = 0
        while not STOP.is_set():
            q = "BAD" if (i // 20) % 3 == 2 else "GOOD"  # ~10 s BAD every 30 s
            _pub(c, f"{BASE}/controller/telemetry/vfd-speed", _payload(1480 + (i % 5), q))
            i += 1
            STOP.wait(0.5)

    for t in threads:
        t.start()
    print("[fake] publishing. Try in the app:")
    print("  1. Discover on #  -> classes guessed, save to topics.json")
    print("  2. Monitor shows ALIVE; stop this script -> STALE -> DEAD (Tier 1 on top)")
    print("  3. Restart -> back to ALIVE.  Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        try:
            c.loop_stop()
            c.disconnect()
        except Exception:
            pass
    return 0


def run_offline_retained(host: str, port: int) -> int:
    """Publish a retained OFFLINE then exit — app must show DEAD, not ALIVE."""
    c = _client(host, port, "ojt-g1-fake-offline")
    _pub(c, f"{BASE}/panel/state/plc-connection", _payload("OFFLINE"), retain=True)
    time.sleep(0.5)
    c.loop_stop()
    c.disconnect()
    print("[fake] retained OFFLINE published. The app must show this topic as DEAD.")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Local fake MQTT publishers (test only).")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--scenario", choices=["demo", "offline-retained"], default="demo")
    ap.add_argument("--i-understand-this-is-live", action="store_true",
                    help="Required if --host is the plant broker.")
    args = ap.parse_args()
    if args.host == PLANT_HOST and not args.i_understand_this_is_live:
        print(f"REFUSING to run fake publishers against plant broker {PLANT_HOST}.")
        print("Use a local Mosquitto broker (default 127.0.0.1:1883).")
        return 2
    if args.scenario == "demo":
        return run_demo(args.host, args.port)
    return run_offline_retained(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
