"""Dataclasses and enums for topic configuration and broker profiles.

All configuration models are plain data + (de)serialization.  No
credentials are ever stored in ``topics.json``; broker credentials
live only in ``profiles.json`` (see :class:`BrokerProfile`).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TopicClass(str, Enum):
    """Supported topic classes (the liveness rules keyed off these)."""

    CONNECTION = "connection"
    HEARTBEAT = "heartbeat"
    PERIODIC = "periodic"
    ON_CHANGE = "on_change"
    COMMAND = "command"

    @classmethod
    def parse(cls, value: str) -> "TopicClass":
        """Parse a string into a TopicClass, raising ``ValueError``."""
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            valid = ", ".join(c.value for c in cls)
            raise ValueError(f"Invalid topic class {value!r}; expected one of: {valid}") from exc


class TopicState(str, Enum):
    """Liveness states, ordered from most to least severe."""

    DEAD = "DEAD"
    STALE = "STALE"
    BAD_QUALITY = "BAD QUALITY"
    NEVER_SEEN = "NEVER SEEN"
    ALIVE = "ALIVE"

    @property
    def severity(self) -> int:
        """Lower value == more severe. Used as the secondary sort key."""
        return _STATE_SEVERITY[self]


_STATE_SEVERITY: dict[TopicState, int] = {
    TopicState.DEAD: 0,
    TopicState.STALE: 1,
    TopicState.BAD_QUALITY: 2,
    TopicState.NEVER_SEEN: 3,
    TopicState.ALIVE: 4,
}


class ConnectionState(str, Enum):
    """Broker connection states shown in the status bar."""

    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


# --------------------------------------------------------------------------
# topics.json model
# --------------------------------------------------------------------------

_VALID_TIERS = (1, 2, 3, 4)


@dataclass
class TopicConfig:
    """One entry of ``data/topics.json``.

    ``class`` is a Python keyword, hence the attribute name
    ``topic_class`` while the JSON key remains ``"class"``.
    """

    topic: str
    short_name: str = ""
    purpose: str = ""
    entity: str = ""
    topic_class: TopicClass = TopicClass.PERIODIC
    period_s: float | None = None
    tier: int = 3
    if_silent: str = ""
    sample_value: str = ""
    first_seen: str = ""
    kind: str = ""
    unit: str = ""
    readback_topics: tuple[str, ...] = ()
    monitor_only: bool = True
    publish_allowed: bool = False
    retained_expected: bool | None = None

    def validate(self) -> list[str]:
        """Return a list of human-readable problems (empty == valid)."""
        errors: list[str] = []
        if not self.topic or not self.topic.strip():
            errors.append("topic must not be empty")
        if isinstance(self.topic_class, str) and not isinstance(self.topic_class, TopicClass):
            try:
                TopicClass.parse(self.topic_class)
            except ValueError as exc:
                errors.append(str(exc))
        if self.tier not in _VALID_TIERS:
            errors.append(f"tier must be one of {_VALID_TIERS}, got {self.tier!r}")
        if not self.monitor_only:
            errors.append("all configured topics must remain monitor-only")
        if self.publish_allowed:
            errors.append("publishing is forbidden for every configured topic")
        if self.period_s is not None:
            if not isinstance(self.period_s, (int, float)) or isinstance(self.period_s, bool):
                errors.append(f"period_s must be numeric, got {self.period_s!r}")
            elif self.period_s <= 0:
                errors.append(f"period_s must be > 0, got {self.period_s!r}")
        if (
            isinstance(self.topic_class, TopicClass)
            and self.topic_class in (TopicClass.HEARTBEAT, TopicClass.PERIODIC)
            and self.period_s is None
        ):
            errors.append(f"{self.topic_class.value} topics should define period_s")
        return errors

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict with keys exactly as required by the spec."""
        return {
            "topic": self.topic,
            "short_name": self.short_name,
            "purpose": self.purpose,
            "entity": self.entity,
            "class": self.topic_class.value
            if isinstance(self.topic_class, TopicClass)
            else str(self.topic_class),
            "period_s": self.period_s,
            "tier": self.tier,
            "if_silent": self.if_silent,
            "sample_value": self.sample_value,
            "first_seen": self.first_seen,
            "kind": self.kind,
            "unit": self.unit,
            "readback_topics": list(self.readback_topics),
            "monitor_only": self.monitor_only,
            "publish_allowed": self.publish_allowed,
            "retained_expected": self.retained_expected,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicConfig":
        """Build from a dict, tolerating unknown/missing keys.

        Raises ``ValueError`` only when the ``class`` value is invalid.
        """
        known = {f.name for f in fields(cls)}
        raw = dict(data)
        raw["topic_class"] = TopicClass.parse(
            raw.pop("class", raw.pop("topic_class", "periodic"))
        )
        if "readback_topics" in raw:
            raw["readback_topics"] = tuple(raw["readback_topics"] or ())
        cleaned2 = {k: v for k, v in raw.items() if k in known}
        return cls(**cleaned2)


# --------------------------------------------------------------------------
# profiles.json model
# --------------------------------------------------------------------------


@dataclass
class BrokerProfile:
    """An MQTT broker profile. Passwords live ONLY in profiles.json."""

    name: str
    host: str
    port: int = 1883
    username: str = ""
    password: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name.strip():
            errors.append("profile name must not be empty")
        if not self.host.strip():
            errors.append("broker host must not be empty")
        if not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            errors.append(f"port must be 1-65535, got {self.port!r}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": int(self.port),
            "username": self.username,
            "password": self.password,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrokerProfile":
        port = data.get("port", 1883)
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 1883
        return cls(
            name=str(data.get("name", "")),
            host=str(data.get("host", "")),
            port=port,
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
        )

    @property
    def masked(self) -> str:
        """Safe repr for logs/GUI: never reveals the password."""
        return f"{self.name} ({self.host}:{self.port})"

    def __repr__(self) -> str:  # pragma: no cover - safety net
        return (
            f"BrokerProfile(name={self.name!r}, host={self.host!r}, "
            f"port={self.port!r}, password='***')"
        )

    __str__ = __repr__


# --------------------------------------------------------------------------
# Runtime settings (application state, not credentials)
# --------------------------------------------------------------------------


@dataclass
class MonitorSettings:
    """Tunable monitoring parameters (Settings tab)."""

    discovery_duration_s: int = 30
    activity_history_s: int = 60
    heartbeat_stale_multiplier: float = 2.5
    heartbeat_dead_multiplier: float = 5.0
    periodic_stale_multiplier: float = 3.0
    periodic_dead_multiplier: float = 6.0
    gui_refresh_ms: int = 100
    terminal_max_lines: int = 5000
    raw_capture_enabled: bool = False
    log_dir: str = "data/logs"
    sound_alert_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitorSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def utc_now_iso() -> str:
    """Timezone-aware ISO 8601 timestamp for logs/first_seen."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
