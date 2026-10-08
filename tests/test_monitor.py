"""Tests for the class-specific liveness engine (no broker needed)."""
from __future__ import annotations

import json
import time

from app.config.models import MonitorSettings, TopicClass, TopicConfig, TopicState
from app.monitoring.topic_monitor import TopicMonitor
from app.mqtt.client import MqttMessage


def _msg(topic: str, payload: str, retain: bool = False, rx: float | None = None) -> MqttMessage:
    return MqttMessage(topic=topic, payload=payload.encode(), retain=retain, qos=0, rx_time=rx or time.time())


def _mon(*configs: TopicConfig) -> TopicMonitor:
    m = TopicMonitor(MonitorSettings())
    m.set_topics(list(configs))
    return m


def _cfg(topic: str, cls: TopicClass, period=None, tier: int = 3, entity: str = "controller") -> TopicConfig:
    return TopicConfig(topic=topic, short_name=topic.rsplit("/", 1)[-1],
                       entity=entity, topic_class=cls, period_s=period, tier=tier)


def test_connection_online_alive():
    m = _mon(_cfg("sys/conn", TopicClass.CONNECTION, tier=1))
    m.ingest(_msg("sys/conn", json.dumps({"value": "ONLINE", "quality": "GOOD"})))
    m.evaluate()
    assert m._topics["sys/conn"].state == TopicState.ALIVE


def test_connection_offline_dead_and_retained_offline_dead():
    for retain in (False, True):
        m = _mon(_cfg("sys/conn", TopicClass.CONNECTION, tier=1))
        m.ingest(_msg("sys/conn", json.dumps({"value": "OFFLINE", "quality": "GOOD"}), retain=retain))
        m.evaluate()
        assert m._topics["sys/conn"].state == TopicState.DEAD, retain


def test_retained_online_connection_is_not_proof_of_live_connection():
    m = _mon(_cfg("sys/conn", TopicClass.CONNECTION, tier=1))
    m.ingest(_msg("sys/conn", json.dumps({"value": "ONLINE", "quality": "GOOD"}), retain=True))
    m.evaluate()
    assert m._topics["sys/conn"].state == TopicState.STALE


def test_never_seen():
    m = _mon(_cfg("sys/x", TopicClass.PERIODIC, period=0.5))
    m.evaluate()
    assert m._topics["sys/x"].state == TopicState.NEVER_SEEN


def test_bad_quality_is_own_state():
    m = _mon(_cfg("sys/air", TopicClass.PERIODIC, period=0.5))
    m.ingest(_msg("sys/air", json.dumps({"value": 31.2, "quality": "BAD"})))
    m.evaluate()
    assert m._topics["sys/air"].state == TopicState.BAD_QUALITY


def test_periodic_timeout_stale_then_dead():
    m = _mon(_cfg("sys/air", TopicClass.PERIODIC, period=0.5))
    now = time.time()
    m.ingest(_msg("sys/air", json.dumps({"value": 1, "quality": "GOOD"}), rx=now - 2.0))
    m.evaluate()
    assert m._topics["sys/air"].state == TopicState.STALE  # > 3x0.5=1.5s
    m2 = _mon(_cfg("sys/air", TopicClass.PERIODIC, period=0.5))
    m2.ingest(_msg("sys/air", json.dumps({"value": 1, "quality": "GOOD"}), rx=now - 10.0))
    m2.evaluate()
    assert m2._topics["sys/air"].state == TopicState.DEAD


def test_heartbeat_counter_stuck_is_not_alive():
    m = _mon(_cfg("sys/hb", TopicClass.HEARTBEAT, period=2.0, tier=1))
    now = time.time()
    m.ingest(_msg("sys/hb", json.dumps({"value": 42}), rx=now - 1.0))
    m.ingest(_msg("sys/hb", json.dumps({"value": 42}), rx=now - 0.5))
    m.ingest(_msg("sys/hb", json.dumps({"value": 42}), rx=now))
    m.evaluate()
    assert m._topics["sys/hb"].state in (TopicState.STALE, TopicState.DEAD)


def test_heartbeat_counter_backwards_is_not_alive():
    m = _mon(_cfg("sys/hb", TopicClass.HEARTBEAT, period=2.0, tier=1))
    now = time.time()
    m.ingest(_msg("sys/hb", json.dumps({"value": 50}), rx=now - 1.0))
    m.ingest(_msg("sys/hb", json.dumps({"value": 49}), rx=now))
    m.evaluate()
    assert m._topics["sys/hb"].state in (TopicState.STALE, TopicState.DEAD)


def test_heartbeat_healthy_alive():
    m = _mon(_cfg("sys/hb", TopicClass.HEARTBEAT, period=2.0, tier=1))
    now = time.time()
    m.ingest(_msg("sys/hb", json.dumps({"value": 1}), rx=now - 2.0))
    m.ingest(_msg("sys/hb", json.dumps({"value": 2}), rx=now - 1.0))
    m.ingest(_msg("sys/hb", json.dumps({"value": 3}), rx=now))
    m.evaluate()
    assert m._topics["sys/hb"].state == TopicState.ALIVE


def test_retained_on_change_snapshot_is_not_treated_as_live():
    m = _mon(_cfg("sys/run", TopicClass.ON_CHANGE, tier=2))
    m.ingest(_msg("sys/run", json.dumps({"value": 1, "quality": "GOOD"}), retain=True,
                  rx=time.time() - 3600))
    m.evaluate()
    assert m._topics["sys/run"].state == TopicState.STALE


def test_live_on_change_state_does_not_timeout_by_age():
    m = _mon(_cfg("sys/run", TopicClass.ON_CHANGE, tier=2))
    m.ingest(_msg("sys/run", json.dumps({"value": 1, "quality": "GOOD"}),
                  rx=time.time() - 3600))
    m.evaluate()
    assert m._topics["sys/run"].state == TopicState.ALIVE


def test_command_never_times_out():
    m = _mon(_cfg("sys/cmd/x", TopicClass.COMMAND, tier=4))
    m.ingest(_msg("sys/cmd/x", json.dumps({"value": 1}), rx=time.time() - 7200))
    m.evaluate()
    assert m._topics["sys/cmd/x"].state == TopicState.ALIVE


def test_tier_sorting_dead_tier1_first():
    from app.monitoring.states import sort_topics
    rows = [(4, TopicState.ALIVE, "z"), (1, TopicState.DEAD, "a"), (1, TopicState.ALIVE, "b")]
    assert sort_topics(rows)[0] == (1, TopicState.DEAD, "a")
