"""Discover mode: listen on ``#`` and record every unique topic.

Read-only: discovery only subscribes.  Retained messages arriving
immediately after subscription are recorded *as retained* so the UI can
flag them; timing statistics ignore retained arrivals (they are
snapshots, not live traffic).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config.models import TopicClass, TopicConfig
from ..mqtt.client import MqttMessage
from ..monitoring.classifiers import Classification, TopicObservation, classify

log = logging.getLogger(__name__)


@dataclass
class DiscoveredTopic:
    """A discovered topic plus everything the UI needs to show."""

    observation: TopicObservation
    classification: Classification
    sample_payload: str = ""
    first_seen_iso: str = ""
    last_seen_iso: str = ""

    @property
    def topic(self) -> str:
        return self.observation.topic

    @property
    def count(self) -> int:
        return self.observation.count

    @property
    def retained(self) -> bool:
        return self.observation.last_retain

    @property
    def measured_interval(self) -> float | None:
        return self.observation.measured_interval_s


class DiscoverySession:
    """Collects observations while Discover mode is running."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._topics: dict[str, TopicObservation] = {}
        self.started_mono: float = 0.0
        self.total_messages: int = 0
        self.retained_messages: int = 0

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            self._topics.clear()
            self.total_messages = 0
            self.retained_messages = 0
            self.started_mono = time.monotonic()
        log.info("Discovery started (subscribing to # only; read-only)")

    @property
    def running(self) -> bool:
        return self.started_mono > 0

    @property
    def elapsed_s(self) -> float:
        if self.started_mono <= 0:
            return 0.0
        return time.monotonic() - self.started_mono

    # -- ingestion --------------------------------------------------------
    def ingest(self, msg: MqttMessage) -> None:
        with self._lock:
            self.total_messages += 1
            if msg.retain:
                self.retained_messages += 1
            obs = self._topics.get(msg.topic)
            if obs is None:
                obs = TopicObservation(
                    topic=msg.topic, first_seen=msg.rx_time, last_seen=msg.rx_time
                )
                self._topics[msg.topic] = obs
            obs.observe(msg.text, msg.retain, msg.rx_time)

    # -- results ----------------------------------------------------------
    def snapshot(self) -> list[DiscoveredTopic]:
        """Current discovered topics with fresh classifications."""
        with self._lock:
            items = list(self._topics.items())
        out: list[DiscoveredTopic] = []
        for topic, obs in items:
            cls = classify(obs)
            out.append(
                DiscoveredTopic(
                    observation=obs,
                    classification=cls,
                    sample_payload=obs.sample_payload,
                    first_seen_iso=_iso(obs.first_seen),
                    last_seen_iso=_iso(obs.last_seen),
                )
            )
        out.sort(key=lambda d: d.topic)
        return out

    @property
    def unique_count(self) -> int:
        with self._lock:
            return len(self._topics)

    @property
    def message_rate(self) -> float:
        e = self.elapsed_s
        return self.total_messages / e if e > 0.5 else 0.0

    def stop(self) -> None:
        """Stop collecting (session data kept for review until cleared)."""
        log.info(
            "Discovery stopped after %.1fs: %d unique topics, %d messages",
            self.elapsed_s,
            self.unique_count,
            self.total_messages,
        )
        self.started_mono = 0.0

    def clear(self) -> None:
        with self._lock:
            self._topics.clear()
            self.total_messages = 0
            self.retained_messages = 0
            self.started_mono = 0.0


def _iso(ts: float) -> str:
    if ts <= 0:
        return ""
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def to_topic_configs(
    discovered: list[DiscoveredTopic],
    overrides: dict[str, tuple[TopicClass, str]] | None = None,
) -> list[TopicConfig]:
    """Convert discovery results into TopicConfig entries.

    ``overrides`` maps topic -> (class, short_name) for user corrections.
    """
    overrides = overrides or {}
    configs: list[TopicConfig] = []
    for d in discovered:
        obs = d.observation
        cls, short = overrides.get(
            d.topic, (d.classification.topic_class, _short_name(d.topic))
        )
        period = obs.measured_interval_s
        if cls not in (TopicClass.HEARTBEAT, TopicClass.PERIODIC):
            period = None
        configs.append(
            TopicConfig(
                topic=d.topic,
                short_name=short,
                purpose="Discovered by Discover mode — edit me",
                entity=_entity_guess(d.topic),
                topic_class=cls,
                period_s=round(period, 3) if period else None,
                tier=_default_tier(cls),
                if_silent="",
                sample_value=d.sample_payload[:400],
                first_seen=d.first_seen_iso,
            )
        )
    return configs


def _short_name(topic: str) -> str:
    return topic.rsplit("/", 1)[-1] or topic


def _entity_guess(topic: str) -> str:
    """Best-effort entity from the topic path (never hardcoded devices)."""
    parts = topic.split("/")
    if len(parts) >= 3:
        return parts[2] if parts[0].startswith("exhaust") else parts[1]
    return parts[0]


def _default_tier(cls: TopicClass) -> int:
    """Spec default tiers by class; operator can change every value."""
    return {
        TopicClass.CONNECTION: 1,
        TopicClass.HEARTBEAT: 1,
        TopicClass.PERIODIC: 3,
        TopicClass.ON_CHANGE: 2,
        TopicClass.COMMAND: 4,
    }[cls]

