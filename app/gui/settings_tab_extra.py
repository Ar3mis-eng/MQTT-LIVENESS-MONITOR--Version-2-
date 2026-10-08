"""Settings tab part 2/2: save/test connections (monkey-patched)."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from ..config.config_manager import save_profiles
from ..config.models import BrokerProfile
from .settings_tab import SettingsTab


def _save(self: SettingsTab) -> None:
    p = BrokerProfile(
        name=self.name_edit.text().strip(), host=self.host_edit.text().strip(),
        port=int(self.port_spin.value()), username=self.user_edit.text(),
        password=self.pass_edit.text(),
    )
    errs = p.validate()
    if errs:
        QMessageBox.warning(self, "Invalid profile", "\n".join(errs))
        return
    others = [x for x in self._window.profiles if x.name != p.name]
    cur = self._current()
    if cur is not None and cur.name != p.name:
        others = [x for x in others if x.name != cur.name]
    others.append(p)
    self._window.profiles = sorted(others, key=lambda x: x.name.lower())
    save_profiles(self._window.profiles)
    self._window.active_profile = p
    self._window._refresh_profile_combo()
    self.refresh_profiles()
    QMessageBox.information(self, "Saved", f"Profile '{p.name}' saved (password masked, not logged).")


def _use(self: SettingsTab) -> None:
    p = self._current()
    if p is None:
        return
    self._window.active_profile = p
    self._window._refresh_profile_combo()


def _test(self: SettingsTab) -> None:
    p = BrokerProfile(
        name=self.name_edit.text().strip() or "(test)", host=self.host_edit.text().strip(),
        port=int(self.port_spin.value()), username=self.user_edit.text(),
        password=self.pass_edit.text(),
    )
    if not p.host:
        QMessageBox.warning(self, "Test", "Enter a host first.")
        return
    self.test_label.setText("Testing...")
    self.test_btn.setEnabled(False)
    from PySide6.QtCore import QTimer
    result: dict = {}
    self._window.test_connection(p, lambda ok, msg: result.update(ok=ok, msg=msg))

    def poll(tries: int = 100) -> None:
        if "ok" in result or tries <= 0:
            self.test_btn.setEnabled(True)
            if "ok" in result:
                self.test_label.setText(("OK: " if result["ok"] else "FAILED: ") + str(result["msg"]))
            else:
                self.test_label.setText("FAILED: timed out")
            return
        QTimer.singleShot(100, lambda: poll(tries - 1))

    poll()


SettingsTab._save = _save  # type: ignore[method-assign]
SettingsTab._use = _use  # type: ignore[method-assign]
SettingsTab._test = _test  # type: ignore[method-assign]
