"""Topics tab: configured-topic table (part 1/2)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView, QHeaderView, QFileDialog,
)

from ..config.config_manager import ConfigError
from ..config.models import TopicClass, TopicConfig

_FIELDS = [
    "topic", "short_name", "purpose", "entity", "class",
    "period_s", "tier", "if_silent", "sample_value", "first_seen",
    "kind", "unit", "readback_topics", "retained_expected",
]


class TopicsTab(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search topics...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_table)
        bar.addWidget(self.search, 2)
        for label in ["Load", "Save", "Save As...", "Add", "Remove"]:
            b = QPushButton(label)
            b.clicked.connect(getattr(self, "_" + label.lower().replace(" ", "_").replace(".", "")))
            bar.addWidget(b)
        layout.addLayout(bar)

        self.split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, len(_FIELDS))
        self.table.setHorizontalHeaderLabels([f.replace("_", " ").title() for f in _FIELDS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.split.addWidget(self.table)
        layout.addWidget(self.split, 1)

    def refresh_table(self) -> None:
        q = self.search.text().strip().lower()
        topics = self._window.topic_file.topics
        if q:
            topics = [t for t in topics if q in t.topic.lower() or q in t.short_name.lower()]
        self.table.setRowCount(len(topics))
        for r, t in enumerate(topics):
            vals = [
                t.topic, t.short_name, t.purpose, t.entity,
                t.topic_class.value if isinstance(t.topic_class, TopicClass) else str(t.topic_class),
                "" if t.period_s is None else str(t.period_s),
                str(t.tier), t.if_silent, t.sample_value, t.first_seen,
                t.kind, t.unit, ", ".join(t.readback_topics),
                "" if t.retained_expected is None else str(t.retained_expected),
            ]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()

    def _collect(self) -> list[TopicConfig]:
        out: list[TopicConfig] = []
        for r in range(self.table.rowCount()):
            cells = [(self.table.item(r, c).text() if self.table.item(r, c) else "") for c in range(len(_FIELDS))]
            period = cells[5].strip()
            tier_txt = cells[6].strip() or "3"
            out.append(TopicConfig(
                topic=cells[0].strip(), short_name=cells[1], purpose=cells[2],
                entity=cells[3],
                topic_class=TopicClass.parse(cells[4] or "periodic"),
                period_s=float(period) if period else None,
                tier=int(float(tier_txt)), if_silent=cells[7],
                sample_value=cells[8], first_seen=cells[9],
                kind=cells[10], unit=cells[11],
                readback_topics=tuple(x.strip() for x in cells[12].split(",") if x.strip()),
                retained_expected=(
                    None if not cells[13].strip()
                    else cells[13].strip().lower() in {"true", "yes", "1"}
                ),
                monitor_only=True, publish_allowed=False,
            ))
        return out

    def _apply_and_save(self, path=None) -> bool:
        try:
            topics = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid value", str(exc))
            return False
        self._window.topic_file.topics = topics
        try:
            if path:
                self._window.topic_file.save_as(path)
            else:
                self._window.topic_file.save()
        except (ConfigError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot save", str(exc))
            return False
        self._window.reload_topics()
        return True

    def _load(self) -> None:
        self._window.reload_topics()

    def _save(self) -> None:
        if self._apply_and_save():
            QMessageBox.information(self, "Saved", "topics.json saved and monitor updated.")

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save topics.json as", "topics.json", "JSON (*.json)")
        if path and self._apply_and_save(path):
            QMessageBox.information(self, "Saved", f"Saved copy to {path}.")

    def _add(self) -> None:
        self._window.topic_file.topics.append(TopicConfig(topic="exhaust-system/main/new-topic"))
        self.refresh_table()

    def _remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        topics = self._collect()
        for r in rows:
            if 0 <= r < len(topics):
                del topics[r]
        self._window.topic_file.topics = topics
        self.refresh_table()
