"""Monitor tab: filtered topic table, device summary, and live terminal."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config.hotel_topics import EX_ROOT, FA_ROOT
from ..config.models import ConnectionState, TopicState
from .terminal import LiveTerminal
from .topic_detail import TopicDetailPanel

_COLUMNS = [
    "Tier", "Device", "Topic", "Class", "Value", "Quality", "State",
    "Age", "Expected", "Last Seen", "Retained",
]
_FILTERS = [
    "All", "Exhaust", "Fresh Air", "PLC", "EF-01", "EF-02", "VFD-EX",
    "FAF-01", "VFD-FA", "CrowPanel", "Dampers", "Commands", "Alarms",
    "Telemetry", "Heartbeats",
]
_STATE_COLORS = {
    TopicState.ALIVE: ("#007a70", "#e6f5f3"),
    TopicState.STALE: ("#c94818", "#fff0e9"),
    TopicState.DEAD: ("#b42318", "#fef3f2"),
    TopicState.BAD_QUALITY: ("#7a5af8", "#f4f3ff"),
    TopicState.NEVER_SEEN: ("#60716f", "#f2f6f5"),
}


class MonitorTab(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        conn_row = QHBoxLayout()
        self.conn_banner = QLabel("DISCONNECTED")
        self.conn_banner.setStyleSheet(
            "background:#f2f6f5; color:#526562; border-radius:8px; "
            "padding:6px 10px; font-weight:600;"
        )
        conn_row.addWidget(self.conn_banner)
        self.live_label = QLabel("WAITING FOR MQTT")
        self.live_label.setStyleSheet(
            "background:#f2f6f5; color:#60716f; border-radius:8px; "
            "padding:6px 10px; font-weight:600;"
        )
        conn_row.addWidget(self.live_label)
        self.summary_label = QLabel("Devices: -")
        self.summary_label.setStyleSheet("color:#526562;")
        conn_row.addWidget(self.summary_label, 1)
        conn_row.addWidget(QLabel("Group"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(_FILTERS)
        self.filter_combo.setMinimumWidth(150)
        self.filter_combo.currentTextChanged.connect(self.refresh)
        conn_row.addWidget(self.filter_combo)
        layout.addLayout(conn_row)

        split = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        mid = QHBoxLayout()
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.itemSelectionChanged.connect(self._on_select)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        for col, width in enumerate((54, 100, 280, 100, 120, 78, 105, 75, 88, 100, 82)):
            self.table.setColumnWidth(col, width)
        mid.addWidget(self.table, 3)
        self.detail = TopicDetailPanel()
        mid.addWidget(self.detail, 1)
        top_layout.addLayout(mid)
        split.addWidget(top)

        self.terminal = LiveTerminal(max_lines=window.settings.terminal_max_lines)
        split.addWidget(self.terminal)
        split.setSizes([600, 220])
        layout.addWidget(split, 1)

    def set_conn(self, state: ConnectionState, detail: str = "") -> None:
        show_detail = detail if state != ConnectionState.CONNECTED else ""
        self.conn_banner.setText(state.value + (f" · {show_detail}" if show_detail else ""))
        colors = {
            ConnectionState.DISCONNECTED: ("#526562", "#f2f6f5"),
            ConnectionState.CONNECTING: ("#c94818", "#fff0e9"),
            ConnectionState.CONNECTED: ("#007a70", "#e6f5f3"),
            ConnectionState.RECONNECTING: ("#c94818", "#fff0e9"),
            ConnectionState.ERROR: ("#b42318", "#fef3f2"),
        }
        fg, bg = colors[state]
        self.conn_banner.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:8px; padding:6px 10px; "
            "font-weight:600;"
        )

    def set_live(self, live: bool) -> None:
        self.live_label.setText("LIVE MQTT" if live else "WAITING FOR MQTT")
        if live:
            self.live_label.setStyleSheet(
                "background:#e6f5f3; color:#007a70; border-radius:8px; "
                "padding:6px 10px; font-weight:700;"
            )
        else:
            self.live_label.setStyleSheet(
                "background:#f2f6f5; color:#60716f; border-radius:8px; "
                "padding:6px 10px; font-weight:600;"
            )

    def _on_select(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 2)
        if item is None:
            return
        topic = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self.terminal.set_topic_filter(topic)
        rt = next((r for r in self._window.monitor.snapshot() if r.config.topic == topic), None)
        if rt is not None:
            self.detail.show_runtime(rt, self._window.monitor)

    def refresh(self, _rate: float = 0.0) -> None:
        mon = self._window.monitor
        now = time.time()
        selected_topic = None
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            selected_item = self.table.item(selected_rows[0].row(), 2)
            if selected_item is not None:
                selected_topic = selected_item.data(Qt.ItemDataRole.UserRole)
        runtimes = mon.snapshot()
        runtimes.sort(key=lambda r: (r.config.tier, r.state.severity, r.config.topic))
        selected_filter = self.filter_combo.currentText()
        runtimes = [rt for rt in runtimes if _matches_filter(rt.config, selected_filter)]
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(runtimes))
        for row, rt in enumerate(runtimes):
            c = rt.config
            age_s = (now - rt.last_rx) if rt.last_rx is not None else None
            age_txt = _fmt_age(age_s)
            try:
                last_seen = time.strftime("%H:%M:%S", time.localtime(rt.last_rx)) if rt.last_rx else "-"
            except (OverflowError, OSError, ValueError):
                last_seen = "-"
            expected = f"{c.period_s:g}s" if c.period_s is not None else "-"
            kind = c.kind or c.topic_class.value.upper()
            value = _format_value(rt.last_value, c.unit)
            state_txt = rt.state.value
            vals = [
                str(c.tier), c.entity or "-", c.short_name or c.topic.rsplit("/", 1)[-1],
                kind, value, rt.last_quality or "-", state_txt, age_txt,
                expected, last_seen, "RETAINED" if rt.last_retain else "",
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, c.topic)
                if col == 2:
                    item.setToolTip(c.topic)
                if col == 6:
                    fg, bg = _STATE_COLORS[rt.state]
                    item.setText(f"●  {state_txt}")
                    item.setForeground(QColor(fg))
                    item.setBackground(QColor(bg))
                if col == 5 and rt.last_quality == "BAD":
                    item.setForeground(QColor("#ff6128"))
                if col == 10 and rt.last_retain:
                    item.setForeground(QColor("#c94818"))
                self.table.setItem(row, col, item)
        self.table.setUpdatesEnabled(True)
        if selected_topic:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 2)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == selected_topic:
                    self.table.selectRow(row)
                    selected_runtime = next(
                        (rt for rt in runtimes if rt.config.topic == selected_topic), None
                    )
                    if selected_runtime is not None:
                        self.detail.show_runtime(selected_runtime, mon)
                    break

        parts = []
        for ent, (worst, count) in sorted(mon.device_summary().items()):
            parts.append(f"{ent}: {worst.value} ({count})")
        self.summary_label.setText("   ·   ".join(parts) if parts else "Devices: -")


def _matches_filter(config, selected: str) -> bool:
    if selected == "All":
        return True
    topic = config.topic
    kind = (config.kind or "").upper()
    entity = config.entity
    if selected == "Exhaust":
        return topic.startswith(EX_ROOT + "/")
    if selected == "Fresh Air":
        return topic.startswith(FA_ROOT + "/")
    if selected == "Commands":
        return kind == "COMMAND"
    if selected == "Alarms":
        return kind == "ALARM"
    if selected == "Telemetry":
        return kind == "TELEMETRY"
    if selected == "Heartbeats":
        return kind == "HEARTBEAT"
    if selected == "Dampers":
        return entity.startswith("MD-") or entity == "Dampers"
    if selected == "PLC":
        return entity == "PLC"
    return entity == selected


def _format_value(value, unit: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        text = str(value).lower()
    elif isinstance(value, (dict, list)):
        text = str(value)
    else:
        text = str(value)
    if unit:
        text = f"{text} {unit}"
    return text if len(text) <= 64 else text[:61] + "..."


def _fmt_age(age_s: float | None) -> str:
    if age_s is None or age_s < 0:
        return "-"
    if age_s < 60:
        return f"{age_s:.1f}s"
    m = int(age_s // 60)
    s = int(age_s % 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    return f"{m // 60}h {(m % 60):02d}m"
