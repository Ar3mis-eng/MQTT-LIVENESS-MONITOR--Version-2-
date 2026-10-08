"""State-machine helpers for topic liveness.

Explicit transition map + hysteresis utilities. The actual per-class
rules live in :mod:`app.monitoring.topic_monitor`; this module owns the
state vocabulary, severity ordering and transition validation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config.models import TopicState

log = logging.getLogger(__name__)

# Allowed transitions (from -> set of to). Anything else is logged and
# coerced, so tiny timing jitter can never produce an illegal jump.
ALLOWED_TRANSITIONS: dict[TopicState, set[TopicState]] = {
    TopicState.NEVER_SEEN: {
        TopicState.ALIVE,
        TopicState.STALE,
        TopicState.DEAD,
        TopicState.BAD_QUALITY,
        TopicState.NEVER_SEEN,
    },
    TopicState.ALIVE: {
        TopicState.STALE,
        TopicState.DEAD,
        TopicState.BAD_QUALITY,
        TopicState.ALIVE,
        TopicState.NEVER_SEEN,
    },
    TopicState.BAD_QUALITY: {
        TopicState.ALIVE,
        TopicState.STALE,
        TopicState.DEAD,
        TopicState.BAD_QUALITY,
    },
    TopicState.STALE: {
        TopicState.ALIVE,
        TopicState.DEAD,
        TopicState.STALE,
        TopicState.BAD_QUALITY,
    },
    TopicState.DEAD: {
        TopicState.ALIVE,
        TopicState.STALE,
        TopicState.DEAD,
        TopicState.BAD_QUALITY,
    },
}


def transition(prev: TopicState, new: TopicState) -> TopicState:
    """Return the (possibly coerced) next state; log illegal transitions."""
    if new == prev:
        return new
    if new not in ALLOWED_TRANSITIONS[prev]:
        log.warning("Illegal state transition %s -> %s; coercing to %s", prev, new, new)
    return new


@dataclass(frozen=True)
class StateChange:
    """One logged state transition."""

    timestamp_iso: str
    topic: str
    short_name: str
    entity: str
    tier: int
    previous: TopicState
    new: TopicState
    reason: str

    def to_csv_line(self) -> str:
        """Single CSV/log line (no commas inside unquoted fields)."""
        return (
            f"{self.timestamp_iso},{_q(self.topic)},{_q(self.short_name)},"
            f"{_q(self.entity)},{self.tier},"
            f"{self.previous.value},{self.new.value},{_q(self.reason)}"
        )

    def to_display(self) -> str:
        return (
            f"{self.timestamp_iso}  {self.short_name or self.topic}  "
            f"{self.previous.value} -> {self.new.value}  ({self.reason})"
        )


def _q(s: str) -> str:
    """CSV-quote a field (state logs must survive commas in reasons)."""
    s = s or ""
    if any(c in s for c in ',"\n\r'):
        return '"' + s.replace('"', '""') + '"'
    return s


def severity_key(state: TopicState) -> int:
    """Sort key: DEAD(0) < STALE(1) < BAD QUALITY(2) < NEVER SEEN(3) < ALIVE(4)."""
    return state.severity


def sort_topics(rows: list[tuple[int, TopicState, str]]) -> list[tuple[int, TopicState, str]]:
    """Sort (tier, state, topic) triples: tier asc, severity asc, name asc."""
    return sorted(rows, key=lambda r: (r[0], severity_key(r[1]), r[2]))
