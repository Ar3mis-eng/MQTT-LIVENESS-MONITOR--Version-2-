"""Topic detail side panel: full metadata + interval stats + recent messages."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget


class TopicDetailPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.title = QLabel("Select a topic for detail")
        self.title.setStyleSheet("font-weight:bold;")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.body = QTextEdit()
        self.body.setReadOnly(True)
        layout.addWidget(self.body, 1)

    def show_runtime(self, rt, monitor) -> None:
        c = rt.config
        now = time.time()
        age = (now - rt.last_rx) if rt.last_rx else None
        avg = rt.interval_sum / rt.interval_count if rt.interval_count else None
        lines = [
            f"Topic: {c.topic}",
            f"Short name: {c.short_name}",
            f"Purpose: {c.purpose}",
            f"Entity: {c.entity}   Kind: {c.kind or c.topic_class.value.upper()}   Tier: {c.tier}",
            f"If silent: {c.if_silent}",
            f"State: {rt.state.value}  ({rt.state_reason})",
            f"Value: {_display_value(rt.last_value, c.unit)}",
            f"Age: {age:.1f}s" if age is not None else "Age: -",
            f"Expected: {c.period_s:g}s" if c.period_s is not None else "Expected: not specified",
            f"Measured last/min/avg/max: "
            f"{_f(rt.interval_last)} / {_f(rt.interval_min)} / {_f(avg)} / {_f(rt.interval_max)}",
            f"Quality: {rt.last_quality or '-'}   Retained: {'YES' if rt.last_retain else 'NO'}",
            f"Retained expected: {c.retained_expected if c.retained_expected is not None else 'not specified'}",
            f"Counter: prev={rt.counter_prev} behavior={rt.counter_behavior or '-'}",
            f"Messages: {rt.msg_count}",
        ]
        linked_commands = [
            candidate
            for candidate in monitor.snapshot()
            if c.topic in candidate.config.readback_topics
        ]
        if c.readback_topics or linked_commands:
            lines.extend(["", "Command / readback relationships:"])
            for readback_topic in c.readback_topics:
                readback_rt = next(
                    (item for item in monitor.snapshot() if item.config.topic == readback_topic),
                    None,
                )
                if rt.last_rx is None:
                    status = "No command observed in this monitor session"
                elif readback_rt is None or readback_rt.last_rx is None:
                    status = "Command observed; readback not observed"
                elif readback_rt.last_rx <= rt.last_rx:
                    status = (
                        "Missing MQTT readback after command — possible "
                        "communication/push-through issue"
                    )
                else:
                    status = "Readback observed after command"
                lines.append(f"  Expected readback: {readback_topic}")
                lines.append(f"  Status: {status}")
            for command_rt in linked_commands:
                status = (
                    "No command observed in this monitor session"
                    if command_rt.last_rx is None
                    else "Command observed: "
                    + datetime.fromtimestamp(command_rt.last_rx).strftime("%H:%M:%S")
                )
                lines.append(f"  Related command: {command_rt.config.topic}")
                lines.append(f"  Status: {status}")
        lines.extend(["", "Last 20 messages (time, retained?, payload):"])
        for stamp, payload, retained in list(rt.recent)[-20:]:
            lines.append(f"  {stamp}{' [R]' if retained else ''}  {payload[:200]}")
        self.title.setText(c.short_name or c.topic)
        self.body.setPlainText("\n".join(lines))


def _f(v) -> str:
    return f"{v:.3f}s" if isinstance(v, (int, float)) else "-"


def _display_value(value, unit: str) -> str:
    if value is None:
        return "-"
    text = str(value).lower() if isinstance(value, bool) else str(value)
    return f"{text} {unit}" if unit else text
