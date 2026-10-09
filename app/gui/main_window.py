"""Main window: tab shell + status bar + MQTT orchestration (part 1/3)."""
from __future__ import annotations

import logging
import queue
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox, QPushButton, QStatusBar,
    QTabWidget, QVBoxLayout, QWidget, QHBoxLayout, QComboBox,
)

from ..config.config_manager import (
    TopicConfigFile, load_profiles, load_settings,
)
from ..config.hotel_topics import EX_ROOT, FA_ROOT
from ..config.models import BrokerProfile, ConnectionState, MonitorSettings
from ..logging.state_logger import StateChangeLogger
from ..monitoring.topic_monitor import TopicMonitor
from ..mqtt.client import ReadOnlyMqttClient, get_local_ip, MqttMessage
from ..mqtt.discovery import DiscoverySession

log = logging.getLogger(__name__)

class _Bridge(QObject):
    """Qt signal bridge: lets the MQTT thread wake the GUI thread."""

    arrived = Signal()
    state_changed = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MQTT Topic Liveness Monitor")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)

        self.settings: MonitorSettings = load_settings()
        self.profiles: list[BrokerProfile] = load_profiles()
        self.active_profile: BrokerProfile | None = self.profiles[0] if self.profiles else None
        self.topic_file = TopicConfigFile.load()
        self.conn_state = ConnectionState.DISCONNECTED
        self.conn_detail = ""

        self.monitor = TopicMonitor(self.settings)
        self.monitor.set_topics(self.topic_file.topics)
        self.state_logger = StateChangeLogger(self.settings.log_dir or "data/logs")
        self.monitor._on_change = self.state_logger.log_change

        self.discovery = DiscoverySession()
        self.discovering = False

        self._inbox: queue.Queue[MqttMessage] = queue.Queue(maxsize=20000)
        self._rate_times: deque[float] = deque(maxlen=300)
        self._terminal_pending: deque[MqttMessage] = deque(maxlen=2000)
        self._last_broker_rx_mono: float | None = None
        self._entity_of: dict[str, str] = {t.topic: t.entity for t in self.topic_file.topics}

        self._bridge = _Bridge()
        self._bridge.state_changed.connect(self._on_conn_signal)

        self.mqtt = ReadOnlyMqttClient(
            on_message=self._on_mqtt_thread,
            on_state=self._on_state_thread,
        )

        self._build_ui()
        self._refresh_profile_combo()
        self._refresh_topic_views()

        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(max(50, int(self.settings.gui_refresh_ms)))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        try:
            self.status_label.setText(f"Laptop IP: {get_local_ip()}")
        except Exception:
            self.status_label.setText("Laptop IP: ?")

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QWidget { font-family: "Segoe UI"; font-size: 10pt; color: #263238; }
            QMainWindow, QWidget#centralWidget { background: #ffffff; }
            QTabWidget::pane { background: #ffffff; border: 1px solid #d9e8e6;
                               border-radius: 8px; top: -1px; }
            QTabBar::tab { background: transparent; color: #60716f; padding: 10px 18px;
                           margin-right: 4px; border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #009B8D; border-bottom-color: #009B8D;
                                    font-weight: 600; }
            QPushButton { background: #ffffff; border: 1px solid #cbd9d7; border-radius: 6px;
                          padding: 7px 13px; color: #263f3c; }
            QPushButton:hover { background: #fff3ee; border-color: #ff6128; }
            QPushButton:disabled { color: #98a2a0; background: #f5f8f7; }
            QPushButton#primaryButton { background: #009B8D; color: #ffffff;
                                        border-color: #009B8D; font-weight: 600; }
            QPushButton#primaryButton:hover { background: #ff6128; border-color: #ff6128; }
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
                background: #ffffff; border: 1px solid #cbd9d7; border-radius: 5px;
                padding: 6px 8px; selection-background-color: #009B8D;
            }
            QTableWidget { background: #ffffff; alternate-background-color: #f5faf9;
                           gridline-color: #edf3f2; border: 1px solid #d9e8e6;
                           border-radius: 6px; selection-background-color: #e6f5f3;
                           selection-color: #006e65; }
            QTableWidget::item:selected { border-left: 2px solid #ff6128; }
            QHeaderView::section { background: #f5faf9; color: #526562; font-weight: 600;
                                   border: none; border-bottom: 1px solid #d9e8e6;
                                   padding: 8px 6px; }
            QTextEdit { background: #ffffff; border: 1px solid #d9e8e6; border-radius: 6px; }
            QStatusBar { background: #ffffff; border-top: 1px solid #d9e8e6; color: #60716f; }
            QLabel#appTitle { font-size: 16pt; font-weight: 650; color: #173b37; }
            QLabel#readonlyTag { color: #006e65; background: #e6f5f3; border-radius: 9px;
                                 padding: 3px 8px; font-size: 9pt; }
        """)
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        app_title = QLabel("MQTT Topic Liveness Monitor")
        app_title.setObjectName("appTitle")
        heading.addWidget(app_title)
        readonly_tag = QLabel("Read-only")
        readonly_tag.setObjectName("readonlyTag")
        readonly_tag.setToolTip("Passive monitor: connects, subscribes, receives, displays and logs.")
        heading.addWidget(readonly_tag)
        heading.addStretch(1)
        layout.addLayout(heading)

        top = QHBoxLayout()
        top.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_picked)
        top.addWidget(self.profile_combo)

        self.broker_label = QLabel("Broker: -")
        top.addWidget(self.broker_label, 1)
        self.conn_label = QLabel("DISCONNECTED")
        self.conn_label.setStyleSheet("font-weight:bold;")
        top.addWidget(self.conn_label)
        self.rate_label = QLabel("0.0 msg/s")
        top.addWidget(self.rate_label)
        self.ip_label = QLabel("")
        top.addWidget(self.ip_label)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self.connect)
        top.addWidget(self.connect_btn)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect)
        self.disconnect_btn.setEnabled(False)
        top.addWidget(self.disconnect_btn)
        layout.addLayout(top)

        from PySide6.QtWidgets import QTabWidget
        from .monitor_tab import MonitorTab
        from .topics_tab import TopicsTab
        import app.gui.topics_tab_extra as _extra  # noqa: F401  (attaches Discover panel)
        import app.gui.settings_tab_extra as _s1  # noqa: F401
        import app.gui.settings_tab_extra2 as _s2  # noqa: F401
        from .settings_tab import SettingsTab
        self.tabs = QTabWidget()
        self.monitor_tab = MonitorTab(self)
        self.topics_tab = TopicsTab(self)
        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.monitor_tab, "Monitor")
        self.tabs.addTab(self.topics_tab, "Topics / Discover")
        self.tabs.addTab(self.settings_tab, "Settings")
        layout.addWidget(self.tabs, 1)

        status = QStatusBar()
        self.status_label = QLabel("")
        status.addWidget(self.status_label, 1)
        self.setStatusBar(status)

    # -- profiles -------------------------------------------------------
    def _refresh_profile_combo(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(f"{p.name}  ({p.host}:{p.port})", p.name)
        if self.active_profile:
            idx = self.profile_combo.findData(self.active_profile.name)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._update_broker_label()

    def _on_profile_picked(self, idx: int) -> None:
        if 0 <= idx < len(self.profiles):
            self.active_profile = self.profiles[idx]
            self._update_broker_label()
            try:
                self.settings_tab.refresh_profiles()
            except Exception:
                pass

    def _update_broker_label(self) -> None:
        if self.active_profile:
            p = self.active_profile
            user = f" user={p.username}" if p.username else ""
            self.broker_label.setText(f"Broker: {p.host}:{p.port}{user}")
            try:
                self.ip_label.setText(f"Laptop IP: {get_local_ip()}")
            except Exception:
                pass
        else:
            self.broker_label.setText("Broker: (no profile - create one in Settings)")

    # -- connection -----------------------------------------------------
    def connect(self) -> None:
        if not self.active_profile:
            QMessageBox.warning(self, "No profile", "Create a broker profile in Settings first.")
            self.tabs.setCurrentWidget(self.settings_tab)
            return
        self._set_conn(ConnectionState.CONNECTING, "connecting...")
        try:
            self.mqtt.connect(self.active_profile)
        except ValueError as exc:
            self._set_conn(ConnectionState.ERROR, str(exc))

    def disconnect(self) -> None:
        self.mqtt.disconnect()
        self._set_conn(ConnectionState.DISCONNECTED, "disconnected by user")

    def _on_state_thread(self, state: ConnectionState, detail: str) -> None:
        self._bridge.state_changed.emit(state.value, detail)

    def _on_conn_signal(self, state_value: str, detail: str) -> None:
        try:
            state = ConnectionState(state_value)
        except ValueError:
            state = ConnectionState.ERROR
        self._set_conn(state, detail)
        if state == ConnectionState.CONNECTED:
            self._resubscribe()
            tgt = self.active_profile.masked if self.active_profile else "?"
            self.state_logger.log_event(f"connected to {tgt}")
        elif state in (ConnectionState.RECONNECTING, ConnectionState.ERROR):
            self.state_logger.log_event(f"connection {state.value}: {detail}")

    def _set_conn(self, state: ConnectionState, detail: str = "") -> None:
        self.conn_state = state
        self.conn_detail = detail
        colors = {
            ConnectionState.DISCONNECTED: "#60716f",
            ConnectionState.CONNECTING: "#ff6128",
            ConnectionState.CONNECTED: "#009B8D",
            ConnectionState.RECONNECTING: "#ff6128",
            ConnectionState.ERROR: "#b42318",
        }
        self.conn_label.setText(state.value)
        self.conn_label.setToolTip(detail)
        self.conn_label.setStyleSheet(f"font-weight:bold; color:{colors.get(state, '#000')};")
        connected = state == ConnectionState.CONNECTED
        self.connect_btn.setEnabled(not connected and state != ConnectionState.CONNECTING)
        self.disconnect_btn.setEnabled(connected or state == ConnectionState.RECONNECTING)
        try:
            self.monitor_tab.set_conn(state, detail)
        except Exception:
            pass

    def _resubscribe(self) -> None:
        if self.discovering:
            self.mqtt.subscribe("#")
        else:
            self.mqtt.unsubscribe("#")
            self.mqtt.subscribe(f"{EX_ROOT}/#")
            self.mqtt.subscribe(f"{FA_ROOT}/#")

    # -- inbound path: network thread -> queue -> GUI timer ---------------
    def _on_mqtt_thread(self, msg: MqttMessage) -> None:
        try:
            self._inbox.put_nowait(msg)
        except Exception:
            pass

    def _tick(self) -> None:
        drained = 0
        while drained < 2000:
            try:
                msg = self._inbox.get_nowait()
            except Exception:
                break
            drained += 1
            now = time.monotonic()
            self._last_broker_rx_mono = now
            self._rate_times.append(now)
            if self.discovering:
                try:
                    self.discovery.ingest(msg)
                except Exception:
                    pass
            try:
                self.monitor.ingest(msg)
            except Exception:
                pass
            if len(self._terminal_pending) < (self._terminal_pending.maxlen or 2000):
                self._terminal_pending.append(msg)
        cutoff = time.monotonic() - 5.0
        while self._rate_times and self._rate_times[0] < cutoff:
            self._rate_times.popleft()
        span = (self._rate_times[-1] - self._rate_times[0]) if len(self._rate_times) > 1 else 0.0
        rate = (len(self._rate_times) / span) if span > 0.5 else 0.0
        try:
            self.rate_label.setText(f"{rate:.1f} msg/s")
        except Exception:
            pass
        self.monitor_tab.set_live(
            self.conn_state == ConnectionState.CONNECTED
            and self._last_broker_rx_mono is not None
            and time.monotonic() - self._last_broker_rx_mono <= 5.0
        )

        try:
            changes = self.monitor.evaluate()
        except Exception:
            changes = []
        for ch in changes:
            if ch.tier == 1 and ch.new.value == "DEAD" and self.settings.sound_alert_enabled:
                self._beep()

        try:
            self.monitor_tab.refresh(rate)
        except Exception:
            pass
        for _ in range(min(len(self._terminal_pending), 400)):
            m = self._terminal_pending.popleft()
            try:
                stamp = datetime.fromtimestamp(m.rx_time, tz=timezone.utc).astimezone().strftime("%H:%M:%S.%f")[:-3]
            except Exception:
                stamp = ""
            try:
                self.monitor_tab.terminal.append_message(stamp, m.topic, m.text, m.retain)
            except Exception:
                pass
        if self.discovering:
            try:
                self.topics_tab.refresh_discovery()
            except Exception:
                pass

    def _beep(self) -> None:
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
        except Exception:
            pass

    # -- topics file ----------------------------------------------------
    def _refresh_topic_views(self) -> None:
        self._entity_of = {t.topic: t.entity for t in self.topic_file.topics}
        try:
            self.monitor_tab.terminal.set_entity_resolver(lambda t: self._entity_of.get(t, ""))
            self.monitor_tab.terminal.set_entities(sorted(set(self._entity_of.values())))
            self.topics_tab.refresh_table()
            self.monitor_tab.refresh(0.0)
        except Exception:
            pass

    def reload_topics(self) -> None:
        self.topic_file = TopicConfigFile.load()
        self.monitor.set_topics(self.topic_file.topics)
        self._refresh_topic_views()
        if self.conn_state == ConnectionState.CONNECTED:
            self._resubscribe()

    # -- discovery ------------------------------------------------------
    def start_discovery(self) -> None:
        if not self.active_profile:
            QMessageBox.warning(self, "No profile", "Select a broker profile first.")
            return
        if self.conn_state != ConnectionState.CONNECTED:
            self.connect()
        self.discovery.start()
        self.discovering = True
        if self.conn_state == ConnectionState.CONNECTED:
            self.mqtt.subscribe("#")

    def stop_discovery(self) -> None:
        self.discovering = False
        try:
            self.discovery.stop()
        except Exception:
            pass
        if self.conn_state == ConnectionState.CONNECTED:
            self._resubscribe()

    def test_connection(self, profile: BrokerProfile, done: Callable[[bool, str], None]) -> None:
        import threading

        def _work() -> None:
            from paho.mqtt import client as _mqtt
            cid = "ojt-g1-monitor-test"
            try:
                try:
                    c = _mqtt.Client(
                        callback_api_version=_mqtt.CallbackAPIVersion.VERSION2,
                        client_id=cid, protocol=_mqtt.MQTTv311,
                    )
                except (AttributeError, TypeError):
                    c = _mqtt.Client(client_id=cid, protocol=_mqtt.MQTTv311)
                c.publish = _raise_forbidden  # type: ignore[method-assign]
                if profile.username:
                    c.username_pw_set(profile.username, profile.password)
                c.connect(profile.host, int(profile.port), keepalive=10)
                c.disconnect()
                done(True, f"Reached {profile.host}:{profile.port} OK")
            except Exception as exc:
                done(False, str(exc))

        threading.Thread(target=_work, daemon=True).start()

    def closeEvent(self, event) -> None:
        try:
            self.mqtt.disconnect()
            self.state_logger.close()
        finally:
            super().closeEvent(event)


def _raise_forbidden(*_a: object, **_k: object):
    from ..mqtt.client import PublishForbiddenError
    raise PublishForbiddenError("READ-ONLY: publishing is forbidden.")
