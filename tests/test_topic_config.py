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
