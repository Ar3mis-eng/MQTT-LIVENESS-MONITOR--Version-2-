"""Load/save topics.json, profiles.json and settings.json.

Design notes
------------
* ``topics.json`` is the primary topic configuration — human readable,
  indented, never contains credentials.
* ``profiles.json`` holds broker credentials and is listed in
  ``.gitignore``.  Written with ``0o600`` permissions where supported.
* All writes are atomic (temp file + ``os.replace``).
* A corrupt file is renamed ``*.bad-<timestamp>`` and defaults returned,
  so the app still starts.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import BrokerProfile, MonitorSettings, TopicConfig
from .hotel_topics import EX_ROOT, FA_ROOT, build_hotel_topics

log = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration cannot be parsed or validated."""


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def app_root() -> Path:
    """Root directory of the project (parent of the ``app`` package)."""
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return app_root() / "data"


def topics_path() -> Path:
    return data_dir() / "topics.json"


def profiles_path() -> Path:
    return data_dir() / "profiles.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"


# --------------------------------------------------------------------------
# Low-level atomic JSON IO
# --------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=4, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _quarantine_corrupt(path: Path) -> None:
    """Rename a corrupt file so it is preserved but no longer loaded."""
    bad = path.with_name(f"{path.name}.bad-{int(time.time())}")
    try:
        shutil.move(path, bad)
        log.error("Corrupt config %s quarantined to %s", path, bad)
    except OSError as exc:  # pragma: no cover
        log.error("Could not quarantine %s: %s", path, exc)


def _load_json(path: Path) -> Any | None:
    """Return parsed JSON or ``None`` if missing/corrupt."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to read %s: %s", path, exc)
        _quarantine_corrupt(path)
        return None


# --------------------------------------------------------------------------
# topics.json
# --------------------------------------------------------------------------


@dataclass
class TopicConfigFile:
    """In-memory representation of ``data/topics.json``."""

    topics: list[TopicConfig] = field(default_factory=list)
    path: Path = topics_path()

    def validate(self) -> list[str]:
        """Full-file validation: per-topic checks + duplicate detection."""
        errors: list[str] = []
        seen: set[str] = set()
        for i, t in enumerate(self.topics):
            for err in t.validate():
                errors.append(f"topics[{i}] ({t.topic or '<empty>'}): {err}")
            key = t.topic.strip()
            if key in seen:
                errors.append(f"topics[{i}]: duplicate topic {key!r}")
            seen.add(key)
        return errors

    @classmethod
    def load(cls, path: Path | None = None) -> "TopicConfigFile":
        """Load topics.json, seeding the official hotel registry over demo defaults."""
        path = path or topics_path()
        raw = _load_json(path)
        if raw is None:
            result = cls(topics=build_hotel_topics(), path=path)
            if path == topics_path():
                result.save()
            return result
        if not isinstance(raw, dict) or not isinstance(raw.get("topics"), list):
            log.error("%s has no 'topics' array; starting empty", path)
            _quarantine_corrupt(path)
            result = cls(topics=build_hotel_topics(), path=path)
            if path == topics_path():
                result.save()
            return result
        topics: list[TopicConfig] = []
        for i, entry in enumerate(raw["topics"]):
            if not isinstance(entry, dict):
                log.error("%s: topics[%d] is not an object; skipped", path, i)
                continue
            try:
                topics.append(TopicConfig.from_dict(entry))
            except (ValueError, TypeError) as exc:
                log.error("%s: topics[%d] invalid (%s); skipped", path, i, exc)
        # Replace only the known demo fixture; preserve operator-edited registries.
        if path == topics_path() and topics and not any(
            t.topic.startswith((EX_ROOT + "/", FA_ROOT + "/")) for t in topics
        ):
            result = cls(topics=build_hotel_topics(), path=path)
            result.save()
            return result
        return cls(topics=topics, path=path)

    def save(self, path: Path | None = None) -> None:
        """Validate then atomically write. Raises ConfigError on bad data."""
        path = path or self.path
        errors = self.validate()
        if errors:
            raise ConfigError(
                "Refusing to save invalid topics.json:\n" + "\n".join(errors)
            )
        payload = {"topics": [t.to_dict() for t in self.topics]}
        _atomic_write_json(path, payload)
        log.info("Saved %d topics to %s", len(self.topics), path)

    def save_as(self, path: Path) -> None:
        """Save a copy to another path (Save As)."""
        TopicConfigFile(topics=list(self.topics), path=path).save(path)

# --------------------------------------------------------------------------
# profiles.json  (credentials — never in topics.json, never logged)
# --------------------------------------------------------------------------


def load_profiles() -> list[BrokerProfile]:
    """Load profiles and ensure the credential-free hotel profile is available."""
    raw = _load_json(profiles_path())
    profiles: list[BrokerProfile] = []
    if isinstance(raw, dict) and isinstance(raw.get("profiles"), list):
        for entry in raw["profiles"]:
            if not isinstance(entry, dict):
                continue
            p = BrokerProfile.from_dict(entry)
            if p.name == "Hotel Kitchen MQTT":
                if not p.host or p.host in {"127.0.0.1", "localhost"}:
                    p.host = "192.168.50.11"
                p.port = 1883
                if not p.username:
                    p.username = "crowpanel"
                if not p.password:
                    p.password = "createlabz123"
            errors = p.validate()
            if errors:
                log.error("Skipping invalid profile %r (%s)", p.name, "; ".join(errors))
                continue
            profiles.append(p)
    default = next(
        (p for p in profiles if p.name == "Hotel Kitchen MQTT"),
        BrokerProfile(
            name="Hotel Kitchen MQTT",
            host="192.168.50.11",
            port=1883,
            username="crowpanel",
            password="createlabz123",
        ),
    )
    profiles = [p for p in profiles if p.name != default.name]
    profiles.insert(0, default)
    return profiles


def save_profiles(profiles: list[BrokerProfile]) -> None:
    """Persist broker profiles atomically. Never logs contents."""
    payload = {"profiles": [p.to_dict() for p in profiles]}
    path = profiles_path()
    _atomic_write_json(path, payload)
    try:  # best effort: restrict file permissions on POSIX.
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows may not support
        pass
    log.info("Saved %d broker profiles to %s (contents not logged)", len(profiles), path)


# --------------------------------------------------------------------------
# settings.json  (non-secret runtime settings)
# --------------------------------------------------------------------------


def load_settings() -> MonitorSettings:
    raw = _load_json(settings_path())
    if isinstance(raw, dict):
        try:
            return MonitorSettings.from_dict(raw)
        except TypeError as exc:
            log.error("settings.json invalid (%s); using defaults", exc)
    return MonitorSettings()


def save_settings(settings: MonitorSettings) -> None:
    _atomic_write_json(settings_path(), settings.to_dict())
    log.info("Saved settings to %s", settings_path())
