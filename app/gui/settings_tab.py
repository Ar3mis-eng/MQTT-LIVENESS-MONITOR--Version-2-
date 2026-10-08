"""Settings tab (part 1/2): broker profiles CRUD."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..config.config_manager import save_profiles
from ..config.models import BrokerProfile


class SettingsTab(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Broker profiles (credentials ONLY in data/profiles.json):"))
        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(260)
        self.profile_combo.currentIndexChanged.connect(self._on_pick)
        row.addWidget(self.profile_combo, 2)
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self._new)
        row.addWidget(self.new_btn)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete)
        row.addWidget(self.del_btn)
        self.use_btn = QPushButton("Use Selected")
        self.use_btn.clicked.connect(self._use)
        row.addWidget(self.use_btn)
        layout.addLayout(row)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.50.11")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(1883)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("(stored in profiles.json, never logged)")
        form.addRow("Name:", self.name_edit)
        form.addRow("Host:", self.host_edit)
        form.addRow("Port:", self.port_spin)
        form.addRow("Username:", self.user_edit)
        form.addRow("Password:", self.pass_edit)
        layout.addLayout(form)

        brow = QHBoxLayout()
        self.save_btn = QPushButton("Save Profile")
        self.save_btn.clicked.connect(self._save)
        brow.addWidget(self.save_btn)
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test)
        brow.addWidget(self.test_btn)
        self.test_label = QLabel("")
        brow.addWidget(self.test_label, 1)
        layout.addLayout(brow)
        layout.addStretch(1)
        self.refresh_profiles()

    def refresh_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self._window.profiles:
            self.profile_combo.addItem(p.name, p.name)
        if self._window.active_profile:
            idx = self.profile_combo.findData(self._window.active_profile.name)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._on_pick(self.profile_combo.currentIndex())

    def _current(self) -> BrokerProfile | None:
        name = self.profile_combo.currentData()
        return next((p for p in self._window.profiles if p.name == name), None)

    def _on_pick(self, _idx: int) -> None:
        p = self._current()
        if p is None:
            return
        self.name_edit.setText(p.name)
        self.host_edit.setText(p.host)
        self.port_spin.setValue(int(p.port))
        self.user_edit.setText(p.username)
        self.pass_edit.setText(p.password)

    def _new(self) -> None:
        self.profile_combo.setCurrentIndex(-1)
        self.name_edit.clear()
        self.host_edit.clear()
        self.port_spin.setValue(1883)
        self.user_edit.clear()
        self.pass_edit.clear()
        self.name_edit.setFocus()

    def _delete(self) -> None:
        p = self._current()
        if p is None:
            return
        self._window.profiles = [x for x in self._window.profiles if x.name != p.name]
        save_profiles(self._window.profiles)
        if self._window.active_profile and self._window.active_profile.name == p.name:
            self._window.active_profile = self._window.profiles[0] if self._window.profiles else None
        self._window._refresh_profile_combo()
        self.refresh_profiles()
