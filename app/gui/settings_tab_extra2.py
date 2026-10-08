"""Settings tab part 3/3: monitoring/logging/safety widgets."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QLabel, QMessageBox, QPushButton,
)

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox
from ..config.config_manager import save_settings
from .settings_tab import SettingsTab
import app.gui.settings_tab_extra as _p2  # noqa: F401


def _build_extra(self: SettingsTab) -> None:
    lay = self.layout()
    assert lay is not None
    lay.addWidget(QLabel("Monitoring thresholds (multipliers on expected period):"))
    form = QFormLayout()
    self.hb_stale = QDoubleSpinBox(); self.hb_stale.setRange(1.0, 20.0); self.hb_stale.setSingleStep(0.5)
    self.hb_dead = QDoubleSpinBox(); self.hb_dead.setRange(1.0, 40.0); self.hb_dead.setSingleStep(0.5)
    self.p_stale = QDoubleSpinBox(); self.p_stale.setRange(1.0, 20.0); self.p_stale.setSingleStep(0.5)
    self.p_dead = QDoubleSpinBox(); self.p_dead.setRange(1.0, 40.0); self.p_dead.setSingleStep(0.5)
    self.refresh_spin = QSpinBox(); self.refresh_spin.setRange(50, 1000)
    self.term_lines = QSpinBox(); self.term_lines.setRange(500, 20000)
    s = self._window.settings
    self.hb_stale.setValue(float(s.heartbeat_stale_multiplier))
    self.hb_dead.setValue(float(s.heartbeat_dead_multiplier))
    self.p_stale.setValue(float(s.periodic_stale_multiplier))
    self.p_dead.setValue(float(s.periodic_dead_multiplier))
    self.refresh_spin.setValue(int(s.gui_refresh_ms))
    self.term_lines.setValue(int(s.terminal_max_lines))
    form.addRow("Heartbeat stale x:", self.hb_stale)
    form.addRow("Heartbeat dead x:", self.hb_dead)
    form.addRow("Periodic stale x:", self.p_stale)
    form.addRow("Periodic dead x:", self.p_dead)
    form.addRow("GUI refresh ms:", self.refresh_spin)
    form.addRow("Terminal lines:", self.term_lines)
    lay.addLayout(form)
    self.raw_check = QCheckBox("Raw capture (OFF by default - can be hundreds of MB/day!)")
    self.raw_check.setChecked(bool(s.raw_capture_enabled))
    lay.addWidget(self.raw_check)
    self.sound_check = QCheckBox("Tier-1 DEAD sound")
    self.sound_check.setChecked(bool(s.sound_alert_enabled))
    lay.addWidget(self.sound_check)
    apply_btn = QPushButton("Apply Monitoring Settings")
    apply_btn.clicked.connect(lambda: _apply_method(self))
    lay.addWidget(apply_btn)
def _apply_method(self: SettingsTab) -> None:
    s = self._window.settings
    s.heartbeat_stale_multiplier = float(self.hb_stale.value())
    s.heartbeat_dead_multiplier = float(self.hb_dead.value())
    s.periodic_stale_multiplier = float(self.p_stale.value())
    s.periodic_dead_multiplier = float(self.p_dead.value())
    s.gui_refresh_ms = int(self.refresh_spin.value())
    s.terminal_max_lines = int(self.term_lines.value())
    s.raw_capture_enabled = bool(self.raw_check.isChecked())
    s.sound_alert_enabled = bool(self.sound_check.isChecked())
    save_settings(s)
    self._window.monitor.set_settings(s)
    self._window._timer.setInterval(max(50, int(s.gui_refresh_ms)))
    QMessageBox.information(self, "Applied", "Monitoring settings applied and saved.")


_orig = SettingsTab.__init__

def _patched(self: SettingsTab, window) -> None:
    _orig(self, window)
    for btn, meth in [(self.save_btn, self._save), (self.use_btn, self._use), (self.test_btn, self._test)]:
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        btn.clicked.connect(meth)
    _build_extra(self)

SettingsTab.__init__ = _patched  # type: ignore[method-assign]
