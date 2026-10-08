"""Tests for DiscoverySession aggregation (no broker needed)."""
from __future__ import annotations

import time

from app.mqtt.client import MqttMessage
from app.mqtt.discovery import DiscoverySession


def _m(topic, payload, retain=False, rx=None):
    return MqttMessage(topic=topic, payload=payload.encode(), retain=retain, qos=0, rx_time=rx or time.time())


def test_discovery_counts_and_retained_flag():
    d = DiscoverySession()
    d.start()
    t = time.time()
    d.ingest(_m("a/b", '{"value": 1}', retain=True, rx=t))
    d.ingest(_m("a/b", '{"value": 2}', retain=False, rx=t + 1))
    d.ingest(_m("a/c", 'ONLINE', retain=True, rx=t))
    rows = {r.topic: r for r in d.snapshot()}
    assert rows["a/b"].count == 2
    assert rows["a/b"].retained is True
    assert rows["a/c"].count == 1
    assert d.unique_count == 2
    assert d.retained_messages >= 1
