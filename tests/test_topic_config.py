"""Tests for topics.json load/save/validation (no broker needed)."""
from __future__ import annotations

from app.config.config_manager import TopicConfigFile
from app.config.models import TopicClass


def test_default_hotel_topics_load_and_validate(tmp_path):
    from app.config.hotel_topics import EX_ROOT, FA_ROOT

    tcf = TopicConfigFile.load()
    assert len(tcf.topics) == 78
    assert all(topic.topic.startswith((EX_ROOT + "/", FA_ROOT + "/")) for topic in tcf.topics)
    assert tcf.validate() == []


def test_duplicate_and_bad_entries_rejected(tmp_path):
    from app.config.models import TopicConfig
    tcf = TopicConfigFile(
        topics=[TopicConfig(topic="a"), TopicConfig(topic="a"),
                TopicConfig(topic="b", tier=9)],
        path=tmp_path / "topics.json",
    )
    errs = tcf.validate()
    assert any("uplicate" in e for e in errs)
    assert any("tier" in e for e in errs)


def test_save_round_trip(tmp_path):
    from app.config.models import TopicConfig
    p = tmp_path / "topics.json"
    tcf = TopicConfigFile(
        topics=[TopicConfig(topic="x/y", short_name="Y", topic_class=TopicClass.HEARTBEAT,
                            period_s=2.0, tier=1)],
        path=p,
    )
    tcf.save()
    back = TopicConfigFile.load(p)
    assert back.topics[0].topic == "x/y"
    assert back.topics[0].topic_class == TopicClass.HEARTBEAT


def test_profiles_not_in_topics(tmp_path):
    import json
    from app.config.config_manager import topics_path
    raw = json.loads(topics_path().read_text(encoding="utf-8"))
    blob = json.dumps(raw).lower()
    assert "password" not in blob


def test_default_profile_uses_hmi_broker(monkeypatch, tmp_path):
    import app.config.config_manager as cm

    monkeypatch.setattr(cm, "profiles_path", lambda: tmp_path / "profiles.json")
    profiles = cm.load_profiles()

    assert profiles[0].name == "Hotel Kitchen MQTT"
    assert profiles[0].host == "192.168.50.11"
    assert profiles[0].port == 1883
    assert profiles[0].username == "crowpanel"
    assert profiles[0].password == "createlabz123"


def test_legacy_profile_is_migrated_to_hmi_broker(monkeypatch, tmp_path):
    import json
    import app.config.config_manager as cm

    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({
            "profiles": [{
                "name": "Hotel Kitchen MQTT",
                "host": "127.0.0.1",
                "port": 1883,
                "username": "",
                "password": "",
            }]
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "profiles_path", lambda: path)

    profiles = cm.load_profiles()

    assert profiles[0].name == "Hotel Kitchen MQTT"
    assert profiles[0].host == "192.168.50.11"
    assert profiles[0].port == 1883
    assert profiles[0].username == "crowpanel"
    assert profiles[0].password == "createlabz123"


def test_mqtt_connect_returns_true_when_connect_async_is_scheduled():
    from app.config.models import BrokerProfile
    from app.mqtt.client import ReadOnlyMqttClient

    class DummyClient:
        def __init__(self):
            self.calls = []

        def username_pw_set(self, username, password):
            self.calls.append(("userpass", username, password))

        def connect_async(self, host, port, keepalive):
            self.calls.append(("connect_async", host, port, keepalive))

        def loop_start(self):
            self.calls.append(("loop_start",))

    client = ReadOnlyMqttClient()
    client._client = DummyClient()
    profile = BrokerProfile(name="Test", host="127.0.0.1", port=1883)

    assert client.connect(profile) is True
    assert client.state == "CONNECTING" or client.state.value == "CONNECTING"


def test_valid_profile_is_not_rejected(monkeypatch, tmp_path):
    import json
    import app.config.config_manager as cm

    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({
            "profiles": [{
                "name": "Hotel Kitchen MQTT",
                "host": "127.0.0.1",
                "port": 1883,
                "username": "crowpanel",
                "password": "createlabz123",
            }]
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "profiles_path", lambda: path)

    profiles = cm.load_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "Hotel Kitchen MQTT"
    assert profiles[0].host == "192.168.50.11"
    assert profiles[0].port == 1883
