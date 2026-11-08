"""GUI must stay open after job completion; quit only on main window close."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

APP_PY = Path(__file__).resolve().parents[1] / "src" / "srtspeak" / "gui" / "app.py"


@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_PY.read_text(encoding="utf-8")


def test_quit_on_last_window_closed_is_false(app_src: str) -> None:
    assert "setQuitOnLastWindowClosed(False)" in app_src
    assert "setQuitOnLastWindowClosed(True)" not in app_src


def test_main_window_wa_quit_on_close_false(app_src: str) -> None:
    assert "win.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)" in app_src


def test_result_boxes_wa_quit_on_close_false(app_src: str) -> None:
    assert app_src.count("WA_QuitOnClose, False") >= 3


def test_close_event_explicit_app_quit(app_src: str) -> None:
    assert "def closeEvent(self, event)" in app_src
    assert "QTimer.singleShot(0, app.quit)" in app_src
    assert "completion must never quit the app" in app_src


def test_show_pending_dialog_raises_main_window(app_src: str) -> None:
    assert "if not self.isVisible():" in app_src
    assert "self.activateWindow()" in app_src


@pytest.mark.skipif(
    os.environ.get("SRTSPEAK_SKIP_QT", "") == "1",
    reason="SRTSPEAK_SKIP_QT=1",
)
def test_result_dialog_does_not_quit_app() -> None:
    """Offscreen: closing a non-modal result box must leave the app running."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)

    win = QMainWindow()
    from PySide6.QtCore import Qt

    win.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    win.resize(320, 200)
    win.show()

    box = QMessageBox(win)
    box.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    box.setModal(False)
    box.setWindowTitle("Done")
    box.setText("finished")
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.show()

    state = {"quit": False, "still": False}

    def after_close() -> None:
        state["still"] = win.isVisible()
        # Do not call app.quit here via last-window; only explicit later.
        QTimer.singleShot(50, finish)

    def finish() -> None:
        state["quit"] = not app.closingDown() if hasattr(app, "closingDown") else True
        app.quit()

    def close_box() -> None:
        box.close()
        QTimer.singleShot(50, after_close)

    QTimer.singleShot(0, close_box)
    rc = app.exec()

    assert state["still"] is True
    assert rc == 0
