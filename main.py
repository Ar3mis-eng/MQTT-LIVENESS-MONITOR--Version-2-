"""MQTT Topic Liveness Monitor — READ-ONLY desktop application.

Run with:  .venv/Scripts/python main.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication

from app.config.config_manager import data_dir
from app.gui.main_window import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(data_dir() / "app.log", encoding="utf-8"),
        ],
    )
    logging.getLogger().info("Starting MQTT Topic Liveness Monitor (READ-ONLY)")
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("MQTT Topic Liveness Monitor")
    win = MainWindow()
    win.show()
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
