"""Topics tab, part 2/2: Discover panel methods (imported for side effects)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView,
)

from ..config.models import TopicClass
from ..mqtt.discovery import to_topic_configs
from .topics_tab import TopicsTab


def _build_discovery(self: TopicsTab) -> None:
    disc = QWidget()
    dl = QVBoxLayout(disc)
    dl.setContentsMargins(0, 0, 0, 0)
    row = QHBoxLayout()
    self.start_btn = QPushButton("Start Discover")
    self.start_btn.clicked.connect(self._window.start_discovery)
    row.addWidget(self.start_btn)
    self.stop_btn = QPushButton("Stop Discover")
    self.stop_btn.clicked.connect(self._window.stop_discovery)
    row.addWidget(self.stop_btn)
    self.disc_status = QLabel("Discover idle")
    row.addWidget(self.disc_status, 1)
    self.save_disc_btn = QPushButton("Save Discovered -> topics.json")
    self.save_disc_btn.clicked.connect(_save_discovered)
    row.addWidget(self.save_disc_btn)
    dl.addLayout(row)
    self.disc_table = QTableWidget(0, 9)
    self.disc_table.setHorizontalHeaderLabels(
        ["Topic", "Registry", "Guess", "Why", "Retain", "Count", "Interval", "First", "Last"])
    self.disc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    dl.addWidget(self.disc_table, 1)
    hint = QLabel("Guess is heuristic only - correct Class/Tier before saving. Sample payload in tooltip.")
    hint.setWordWrap(True)
    dl.addWidget(hint)
    self.split.addWidget(disc)


def refresh_discovery(self: TopicsTab) -> None:
    d = self._window.discovery
    if not self._window.discovering and d.unique_count == 0:
        self.disc_status.setText("Discover idle")
        return
    mode = "DISCOVERING" if self._window.discovering else "discover results"
    self.disc_status.setText(
        f"{mode} - {d.elapsed_s:.0f}s, {d.unique_count} topics, "
        f"{d.total_messages} msgs, {d.retained_messages} retained, "
        f"{d.message_rate:.1f} msg/s   (listening on # - retained flagged R)")
    rows = d.snapshot()
    configured = {topic.topic for topic in self._window.topic_file.topics}
    self.disc_table.setRowCount(len(rows))
    for r, item in enumerate(rows):
        iv = f"{item.measured_interval:.2f}s" if item.measured_interval else "-"
        is_new = item.topic not in configured
        vals = [item.topic, "NEW TOPIC DETECTED" if is_new else "Configured",
                item.classification.topic_class.value,
                item.classification.reason, "R" if item.retained else "",
                str(item.count), iv, item.first_seen_iso, item.last_seen_iso]
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if c == 0:
                it.setToolTip(f"Sample: {item.sample_payload[:400]}")
            if c == 1 and is_new:
                it.setForeground(Qt.GlobalColor.darkBlue)
            self.disc_table.setItem(r, c, it)
    self.disc_table.resizeColumnsToContents()


def _save_discovered() -> None:
    pass  # bound below as a method


def _save_discovered_method(self: TopicsTab) -> None:
    rows = self._window.discovery.snapshot()
    if not rows:
        QMessageBox.information(self, "Nothing to save", "No discovered topics yet.")
        return
    overrides = {}
    for r in range(self.disc_table.rowCount()):
        topic_item = self.disc_table.item(r, 0)
        class_item = self.disc_table.item(r, 2)
        if not topic_item or not class_item:
            continue
        try:
            cls = TopicClass.parse(class_item.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid class", f"Row {r+1}: {class_item.text()!r} is not valid.")
            return
        overrides[topic_item.text()] = (cls, topic_item.text().rsplit("/", 1)[-1])
    configs = to_topic_configs(rows, overrides)
    existing = {t.topic for t in self._window.topic_file.topics}
    added = 0
    for c in configs:
        if c.topic not in existing:
            self._window.topic_file.topics.append(c)
            added += 1
    try:
        self._window.topic_file.save()
    except Exception as exc:
        QMessageBox.warning(self, "Cannot save", str(exc))
        return
    self._window.reload_topics()
    QMessageBox.information(self, "Saved", f"Added {added} new topics to topics.json.")


# Attach to the class (keeps topics_tab.py part 1 under the size limit).
TopicsTab.refresh_discovery = refresh_discovery  # type: ignore[method-assign]
TopicsTab._save_discovered = _save_discovered_method  # type: ignore[method-assign]
_orig_init = TopicsTab.__init__

def _patched_init(self: TopicsTab, window) -> None:
    _orig_init(self, window)
    _build_discovery(self)
    self.save_disc_btn.clicked.disconnect()
    self.save_disc_btn.clicked.connect(self._save_discovered)
    self.split.setSizes([380, 260])

TopicsTab.__init__ = _patched_init  # type: ignore[method-assign]
