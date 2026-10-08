"""Regression tests for the real hotel topic registry and broker default."""
from __future__ import annotations

from app.config.config_manager import load_profiles
from app.config.hotel_topics import EX_ROOT, FA_ROOT, READBACKS, build_hotel_topics
from app.config.models import TopicClass


def test_registry_has_complete_roots_and_required_devices():
    topics = build_hotel_topics()
    by_topic = {topic.topic: topic for topic in topics}
    assert len(by_topic) == len(topics)
    assert all(topic.startswith((EX_ROOT + "/", FA_ROOT + "/")) for topic in by_topic)
    for suffix in (
        "panel/state/plc-heartbeat",
        "EF-01/state/hoa",
        "EF-02/state/hoa",
        "VFD-EX/telemetry/speed-actual",
        "VFD-FA/telemetry/speed-actual",
        "crowpanel/state/heartbeat",
        "MD-EX-01/state/position",
        "MD-FA-01/state/position",
        "AFS-01/telemetry/wind-speed-ms",
    ):
        assert any(topic.endswith("/" + suffix) for topic in by_topic)


def test_commands_are_monitor_only_with_disabled_publishing():
    commands = [topic for topic in build_hotel_topics() if topic.topic_class == TopicClass.COMMAND]
    assert commands
    assert all(topic.monitor_only and not topic.publish_allowed for topic in commands)
    assert all(topic.readback_topics for topic in commands if topic.topic in READBACKS)


def test_registry_does_not_include_disabled_or_reserved_topics():
    topics = {topic.topic for topic in build_hotel_topics()}
    assert not any("/diag/" in topic for topic in topics)
    assert not any(topic.endswith("/state/fault-input") for topic in topics)


def test_expected_intervals_are_only_set_for_known_timing():
    by_topic = {topic.topic: topic for topic in build_hotel_topics()}
    assert by_topic[f"{EX_ROOT}/panel/state/plc-heartbeat"].period_s == 2
    assert by_topic[f"{EX_ROOT}/crowpanel/state/heartbeat"].period_s == 2
    assert by_topic[f"{EX_ROOT}/AFS-01/telemetry/wind-speed-ms"].period_s == 2
    assert by_topic[f"{EX_ROOT}/VFD-EX/telemetry/speed-actual"].period_s is None


def test_default_broker_profile_is_hotel_broker():
    default = load_profiles()[0]
    assert (default.name, default.host, default.port) == (
        "Hotel Kitchen MQTT", "192.168.50.11", 1883
    )
    assert not default.username
    assert not default.password
