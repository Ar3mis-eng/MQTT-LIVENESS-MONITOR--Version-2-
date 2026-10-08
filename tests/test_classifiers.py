"""Tests for discovery classification heuristics (no broker needed)."""
from __future__ import annotations

import time

from app.config.models import TopicClass
from app.monitoring.classifiers import TopicObservation, classify


def _obs(topic: str) -> TopicObservation:
    now = time.time()
    return TopicObservation(topic=topic, first_seen=now, last_seen=now)


def test_cmd_topic_classified_command():
    o = _obs("exhaust-system/main/panel/cmd/damper-open")
    o.observe('{"value": 1}', False, time.time())
    assert classify(o).topic_class == TopicClass.COMMAND


def test_connection_online_offline_retained():
    o = _obs("exhaust-system/main/panel/state/plc-connection")
    t = time.time()
    o.observe('{"value": "ONLINE", "quality": "GOOD"}', True, t)
    o.observe('{"value": "OFFLINE", "quality": "GOOD"}', True, t + 1)
    c = classify(o)
    assert c.topic_class == TopicClass.CONNECTION


def test_heartbeat_counter_steady():
    o = _obs("exhaust-system/main/panel/state/plc-heartbeat")
    t = time.time()
    for i in range(8):
        o.observe(f'{{"value": {1000 + i}, "quality": "GOOD"}}', False, t + i * 2.0)
    assert classify(o).topic_class == TopicClass.HEARTBEAT


def test_periodic_steady_interval():
    o = _obs("exhaust-system/main/controller/telemetry/airflow")
    t = time.time()
    for i in range(8):
        o.observe(f'{{"value": {30.0 + i * 0.1}, "quality": "GOOD"}}', False, t + i * 0.5)
    got = classify(o).topic_class
    assert got in (TopicClass.PERIODIC, TopicClass.HEARTBEAT)


def test_on_change_irregular():
    o = _obs("exhaust-system/main/system/run-state")
    t = time.time()
    # NOTE: avoid 0/1 here — "0"/"1" are connection-state tokens
    # (OFFLINE/ONLINE aliases), so a 0/1 toggle is *correctly* guessed
    # as CONNECTION. RUN/STOP is unambiguous on_change data.
    o.observe('{"value": "RUN"}', True, t)
    o.observe('{"value": "STOP"}', False, t + 37)
    o.observe('{"value": "RUN"}', False, t + 200)
    assert classify(o).topic_class == TopicClass.ON_CHANGE
