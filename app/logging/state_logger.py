"""State-change logging: one line per STATE CHANGE, never per message.

Daily log files in ``<log_dir>/state_changes_YYYY-MM-DD.csv`` (CSV with
header).  Also provides reconnect/event logging and optional raw traffic
capture (OFF by default — raw capture can produce hundreds of MB/day at
~90 msg/s).
"""

from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..config.models import MonitorSettings
from ..monitoring.states import StateChange

log = logging.getLogger(__name__)

CSV_HEADER = [
    "timestamp",
    "topic",
    "short_name",
    "entity",
    "tier",
    "previous_state",
    "new_state",
    "reason",
]


class StateChangeLogger:
    """Appends state transitions to a daily CSV file.

    Cheap: writes only on transitions (a handful of lines/minute at
    worst), never per MQTT message.
    """

    def __init__(self, log_dir: str | Path) -> None:
        self._dir = Path(log_dir)
        self._lock = threading.Lock()
        self._current_date = ""
        self._fh = None
        self._writer = None

    # -- file management --------------------------------------------------
    def _path_for(self, day: str) -> Path:
        return self._dir / f"state_changes_{day}.csv"

    def _ensure_file(self, now: datetime) -> None:
        day = now.strftime("%Y-%m-%d")
        if day == self._current_date and self._fh is not None:
            return
        self._close()
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(day)
        new_file = not path.exists() or path.stat().st_size == 0
        self._fh = path.open("a", encoding="utf-8", newline="")
        self._writer = csv.writer(self._fh)
        if new_file:
            self._writer.writerow(CSV_HEADER)
        self._current_date = day

    def _close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:  # pragma: no cover
                pass
            self._fh = None
            self._writer = None


    # -- writing ----------------------------------------------------------
    def log_change(self, ch: StateChange) -> None:
        """Write one state change. Thread-safe; never raises to callers."""
        try:
            now = datetime.now(timezone.utc).astimezone()
            with self._lock:
                self._ensure_file(now)
                assert self._writer is not None
                self._writer.writerow(
                    [
                        ch.timestamp_iso,
                        ch.topic,
                        ch.short_name,
                        ch.entity,
                        ch.tier,
                        ch.previous.value,
                        ch.new.value,
                        ch.reason,
                    ]
                )
                assert self._fh is not None
                self._fh.flush()
        except Exception:  # pragma: no cover - logging must never crash the app
            log.exception("Failed to write state change for %s", ch.topic)

    def log_event(self, message: str) -> None:
        """Append an application event (reconnect, connect, errors)."""
        try:
            now = datetime.now(timezone.utc).astimezone()
            with self._lock:
                self._ensure_file(now)
                assert self._writer is not None
                self._writer.writerow(
                    [
                        now.isoformat(timespec="seconds"),
                        "(event)",
                        "",
                        "",
                        "",
                        "",
                        "",
                        message,
                    ]
                )
                assert self._fh is not None
                self._fh.flush()
        except Exception:  # pragma: no cover
            log.exception("Failed to write event")

    def close(self) -> None:
        with self._lock:
            self._close()

    def read_all(self, day: str | None = None) -> list[dict[str, str]]:
        """Read back logged rows (for the History tab). Debug/secondary."""
        rows: list[dict[str, str]] = []
        try:
            paths = (
                [self._path_for(day)]
                if day
                else sorted(self._dir.glob("state_changes_*.csv"))
            )
            for p in paths:
                if not p.exists():
                    continue
                with p.open("r", encoding="utf-8", newline="") as fh:
                    reader = csv.DictReader(fh)
                    rows.extend(reader)
        except Exception:  # pragma: no cover
            log.exception("Failed to read state logs")
        return rows
