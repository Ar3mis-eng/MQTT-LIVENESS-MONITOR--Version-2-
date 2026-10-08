"""Topic-class guessing heuristics for Discover mode.

Pure functions over a :class:`TopicObservation` (stats collected while
listening).  Deliberately easy to tweak — every rule is a small helper
with a weight/reason so the UI can explain its guess.

IMPORTANT: these are HEURISTICS. The operator can always override the
guessed class in the Topics tab.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..config.models import TopicClass
from .payload import OFFLINE_VALUES, ONLINE_VALUES, parse_payload

# Topic-name patterns (case-insensitive). Name signals are the strongest
# single indicator but never trusted alone.
_CMD_RE = re.compile(r"(^|/)(cmd|command|commands|set|setpoint|write)(/|$)", re.I)
_CONN_RE = re.compile(
    r"(^|/)(connection|connectivity|status|state|online|lwt|availability)(/|$)", re.I
)
_HB_RE = re.compile(r"(^|/)(heartbeat|hb|pulse|alive|keepalive|watchdog)(/|$)", re.I)

# Timing thresholds (seconds).
_STEADY_INTERVAL_CV = 0.15  # coefficient of variation <= 15% == steady
_MIN_STEADY_SAMPLES = 4
_COUNTER_MIN_INCREASES = 3


@dataclass
class TopicObservation:
    """Stats collected for one topic during discovery."""

    topic: str
    first_seen: float  # time.time()
    last_seen: float
    count: int = 0
    retained_count: int = 0
    last_retain: bool = False
    sample_payload: str = ""
    # Non-retained arrival timestamps (retained excluded from timing).
    intervals: list[float] = field(default_factory=list)  # gap between arrivals
    _last_arrival: float | None = field(default=None, repr=False)
    # Numeric value history (counter detection), most recent last.
    values: list[float] = field(default_factory=list)
    # Distinct raw payload values seen (bounded).
    distinct_values: set[str] = field(default_factory=set)
    # Distinct value field tokens like ONLINE/OFFLINE.
    state_tokens: set[str] = field(default_factory=set)

    # -- ingestion --------------------------------------------------------
    def observe(self, payload_text: str, retain: bool, rx_time: float) -> None:
        self.count += 1
        self.last_seen = rx_time
        if self.first_seen <= 0:
            self.first_seen = rx_time
        if retain:
            self.retained_count += 1
            self.last_retain = True
        else:
            if self._last_arrival is not None:
                gap = rx_time - self._last_arrival
                if 0 <= gap <= 3600:
                    self.intervals.append(gap)
                    if len(self.intervals) > 512:
                        del self.intervals[:256]
            self._last_arrival = rx_time
        if not self.sample_payload:
            self.sample_payload = payload_text[:500]

        parsed = parse_payload(payload_text)
        if len(self.distinct_values) < 64:
            self.distinct_values.add(str(parsed.value)[:120])
        if isinstance(parsed.value, (int, float)) and not isinstance(parsed.value, bool):
            self.values.append(float(parsed.value))
            if len(self.values) > 256:
                del self.values[:128]
        token = str(parsed.value).strip().upper() if parsed.value is not None else ""
        if token in ONLINE_VALUES or token in OFFLINE_VALUES:
            self.state_tokens.add(token)

    # -- derived stats ----------------------------------------------------
    @property
    def measured_interval_s(self) -> float | None:
        """Median of measured non-retained gaps (robust to bursts)."""
        if len(self.intervals) < _MIN_STEADY_SAMPLES:
            return None
        ordered = sorted(self.intervals)
        return ordered[len(ordered) // 2]

    @property
    def interval_cv(self) -> float:
        """Coefficient of variation of measured gaps (0 == perfectly steady)."""
        n = len(self.intervals)
        if n < _MIN_STEADY_SAMPLES:
            return 1.0
        mean = sum(self.intervals) / n
        if mean <= 0:
            return 1.0
        var = sum((x - mean) ** 2 for x in self.intervals) / n
        return math.sqrt(var) / mean

    @property
    def counter_increases(self) -> int:
        """How many times the numeric value increased monotonically."""
        increases = 0
        for a, b in zip(self.values, self.values[1:]):
            if b > a:
                increases += 1
        return increases

    @property
    def counter_sticky(self) -> bool:
        """True when the value mostly repeats (counter-like but not rising)."""
        if len(self.values) < 4:
            return False
        repeats = sum(1 for a, b in zip(self.values, self.values[1:]) if b == a)
        return repeats >= max(2, int(0.6 * (len(self.values) - 1)))


@dataclass(frozen=True)
class Classification:
    """A guessed class plus the reasoning, for display to the operator."""

    topic_class: TopicClass
    reason: str
    confidence: str  # "high" | "medium" | "low"


def classify(obs: TopicObservation) -> Classification:
    """Guess the topic class from observations. Heuristics, not truth.

    Rule order (first match wins):
      1. /cmd/ in the name                      -> command   (high)
      2. ONLINE/OFFLINE-like payload values      -> connection (high if also retained/name hint)
      3. counter increasing + steady interval    -> heartbeat (medium/high)
      4. steady interval                         -> periodic  (high)
      5. retained state / irregular              -> on_change (medium)
    """
    name = obs.topic

    # 1) Command: explicit operator command path.
    if _CMD_RE.search(name):
        return Classification(
            TopicClass.COMMAND, "topic name contains a command segment (/cmd/)", "high"
        )

    # 2) Connection: ONLINE/OFFLINE payloads, or connection-ish name with retain.
    if obs.state_tokens & ONLINE_VALUES and obs.state_tokens & OFFLINE_VALUES:
        conf = "high" if (obs.last_retain or _CONN_RE.search(name)) else "medium"
        return Classification(
            TopicClass.CONNECTION,
            f"payload values {sorted(obs.state_tokens)} look like a connection state"
            + ("; retained" if obs.last_retain else ""),
            conf,
        )
    if obs.state_tokens and (obs.last_retain and _CONN_RE.search(name)):
        return Classification(
            TopicClass.CONNECTION,
            "retained message on a connection-like topic name",
            "medium",
        )

    # 3) Heartbeat: rising counter with a fairly steady interval.
    interval = obs.measured_interval_s
    steady = obs.interval_cv <= _STEADY_INTERVAL_CV
    rising = obs.counter_increases >= _COUNTER_MIN_INCREASES
    if rising and (steady or _HB_RE.search(name)):
        conf = "high" if steady else "medium"
        return Classification(
            TopicClass.HEARTBEAT,
            f"numeric counter increasing {obs.counter_increases}x"
            + (f" at steady ~{interval:.2f}s" if interval else ""),
            conf,
        )
    if _HB_RE.search(name) and obs.count >= 2:
        return Classification(
            TopicClass.HEARTBEAT, "topic name contains heartbeat/pulse/alive", "medium"
        )

    # 4) Periodic telemetry: steady arrival interval.
    if steady and interval is not None and obs.count >= _MIN_STEADY_SAMPLES + 2:
        return Classification(
            TopicClass.PERIODIC,
            f"steady interval ~{interval:.2f}s (cv={obs.interval_cv:.2f})",
            "high",
        )
    if obs.counter_sticky:
        return Classification(
            TopicClass.HEARTBEAT, "value repeats like a stalled counter", "low"
        )

    # 5) On change: irregular arrivals, often retained.
    if obs.retained_count > 0:
        return Classification(
            TopicClass.ON_CHANGE,
            "retained message with no steady period (state-like)",
            "medium",
        )
    if obs.count >= 3 and not steady:
        return Classification(
            TopicClass.ON_CHANGE,
            f"irregular arrivals (cv={obs.interval_cv:.2f})",
            "medium",
        )

    return Classification(
        TopicClass.ON_CHANGE, "insufficient data; defaulting to on_change", "low"
    )

