"""Parse MQTT payloads into value / timestamp / quality components.

Tolerant by design: malformed JSON, bad timestamps and unknown quality
values must never raise — they degrade gracefully.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Values recognised as "connection" states (case-insensitive).
ONLINE_VALUES = {"ONLINE", "UP", "OK", "CONNECTED", "TRUE", "1", "ALIVE"}
OFFLINE_VALUES = {"OFFLINE", "DOWN", "DISCONNECTED", "FALSE", "0", "DEAD"}


@dataclass
class ParsedPayload:
    """Components extracted from one MQTT payload."""

    raw: str
    value: Any = None  # 'value' field for JSON, else the raw text
    is_json: bool = False
    ts: datetime | None = None  # payload timestamp (aware) if present/parseable
    quality: str | None = None  # normalized upper-case GOOD/BAD/... or None
    quality_known: bool = True  # False when quality present but unrecognized

    @property
    def is_online(self) -> bool | None:
        """True/False for recognised connection values, None otherwise."""
        if self.value is None:
            return None
        token = str(self.value).strip().upper()
        if token in ONLINE_VALUES:
            return True
        if token in OFFLINE_VALUES:
            return False
        return None

    @property
    def is_bad_quality(self) -> bool:
        return self.quality == "BAD"


def _to_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_payload(text: str) -> ParsedPayload:
    """Extract value/ts/quality from a payload string. Never raises."""
    p = ParsedPayload(raw=text)
    stripped = text.strip()
    if not stripped:
        return p
    if stripped[0] not in "{[":
        # Plain-text payload (e.g. "ONLINE").
        p.value = stripped
        return p
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        log.debug("Malformed JSON payload (kept as text): %.120s", text)
        p.value = stripped
        return p
    p.is_json = True
    if isinstance(obj, dict):
        p.value = obj.get("value", None)
        if p.value is None and len(obj) == 1:
            # e.g. {"state": "ONLINE"} — take the single field as the value.
            p.value = next(iter(obj.values()))
        p.ts = _parse_ts(obj.get("ts"))
        q = obj.get("quality")
        if q is not None:
            q_up = str(q).strip().upper()
            p.quality = q_up
            p.quality_known = q_up in {"GOOD", "BAD", "UNCERTAIN", "STALE", "NULL"}
    else:
        p.value = obj
    return p


def _parse_ts(raw: Any) -> datetime | None:
    """Parse a payload 'ts' field (epoch s/ms/us, ISO string). Never raises."""
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            v = float(raw)
            if v > 1e17:  # microseconds
                v /= 1_000_000
            elif v > 1e14:  # milliseconds
                v /= 1_000
            # Seconds since epoch; clamp to a sane range.
            if v < 0 or v > 4e9:
                return None
            return datetime.fromtimestamp(v, tz=timezone.utc)
        if isinstance(raw, str):
            s = raw.strip().replace("Z", "+00:00")
            return _to_aware(datetime.fromisoformat(s))
    except (ValueError, OverflowError, OSError):
        log.debug("Unparseable payload ts: %r", raw)
    return None
