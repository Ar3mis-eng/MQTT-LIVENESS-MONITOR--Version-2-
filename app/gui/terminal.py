"""Live MQTT terminal widget (bounded, filterable, pausable).

Pause freezes *display only* — MQTT reception, monitoring, state
calculation and logging all continue in the background.
"""
from __future__ import annotations

from collections import deque
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..monitoring.payload import parse_payload


class LiveTerminal(QWidget):
    """Bottom-of-monitor rolling traffic view."""

    def __init__(self, max_lines: int = 5000, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_lines = max_lines
        self._paused = False
        self._changes_only = False
        self._pending: deque[str] = deque(maxlen=max_lines)
        self._last_value: dict[str, str] = {}  # topic -> meaningful value key
        self._filter_text = ""
        self._entity_filter = "all"
        self._entity_of: Callable[[str], str] = lambda t: ""
        self._frozen_buffer: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("topic substring…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter)
        bar.addWidget(self.filter_edit, 2)

        bar.addWidget(QLabel("Device:"))
        self.entity_combo = QComboBox()
        self.entity_combo.addItem("all")
        self.entity_combo.currentTextChanged.connect(self._on_entity)
        bar.addWidget(self.entity_combo)

        self.changes_box = QCheckBox("Changes only")
        self.changes_box.toggled.connect(self._on_changes)
        bar.addWidget(self.changes_box)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)
        bar.addWidget(self.pause_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        bar.addWidget(clear_btn)
        layout.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(max_lines)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setPlaceholderText("MQTT traffic appears here once connected…")
        self.view.setStyleSheet(
            "QPlainTextEdit { background-color: #ffffff; color: #263238; "
            "selection-background-color: #e6f5f3; selection-color: #006e65; "
            "border: 1px solid #d9e8e6; border-radius: 6px; }"
        )
        layout.addWidget(self.view, 1)

    # -- configuration --------------------------------------------------
    def set_entity_resolver(self, fn: Callable[[str], str]) -> None:
        self._entity_of = fn

    def set_entities(self, entities: list[str]) -> None:
        cur = self.entity_combo.currentText()
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        self.entity_combo.addItem("all")
        for e in sorted(set(entities)):
            if e:
                self.entity_combo.addItem(e)
        if cur:
            idx = self.entity_combo.findText(cur)
            if idx >= 0:
                self.entity_combo.setCurrentIndex(idx)
        self.entity_combo.blockSignals(False)

    def set_topic_filter(self, text: str) -> None:
        self.filter_edit.setText(text)

    # -- slots ----------------------------------------------------------
    def _on_filter(self, t: str) -> None:
        self._filter_text = t.strip().lower()

    def _on_entity(self, t: str) -> None:
        self._entity_filter = t

    def _on_changes(self, on: bool) -> None:
        self._changes_only = on

    def _on_pause(self, on: bool) -> None:
        self._paused = on
        self.pause_btn.setText("Resume" if on else "Pause")

    @property
    def paused(self) -> bool:
        return self._paused

    def clear(self) -> None:
        self.view.clear()
        self._pending.clear()
        self._last_value.clear()

    # -- ingestion (GUI thread only) ------------------------------------
    def append_message(self, stamp: str, topic: str, payload: str, retain: bool) -> None:
        if self._filter_text and self._filter_text not in topic.lower():
            return
        if self._entity_filter != "all":
            if self._entity_of(topic) != self._entity_filter:
                return
        if self._changes_only:
            try:
                p = parse_payload(payload)
                key = f"{p.value!r}|{p.quality}"
            except Exception:
                key = payload
            if self._last_value.get(topic) == key:
                return
            self._last_value[topic] = key
        flag = " [retained]" if retain else ""
        line = f"{stamp}  {topic}{flag}\n    {payload[:400]}"
        if self._paused:
            return  # frozen display; monitoring continues elsewhere
        self.view.appendPlainText(line)

    def flush_pending(self) -> None:
        pass  # messages are appended directly at GUI-timer pace
