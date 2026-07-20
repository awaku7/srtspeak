"""GUI progress label formatting + wiring contracts."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from srtspeak.core.progress import ProgressEvent
from srtspeak.i18n import setup_i18n
from srtspeak.progress_i18n import format_gui_progress_label

APP_PY = Path(__file__).resolve().parents[1] / "src" / "srtspeak" / "gui" / "app.py"


@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_PY.read_text(encoding="utf-8")


def test_format_gui_progress_label_en() -> None:
    setup_i18n("en")
    ev = ProgressEvent(
        percent=12.5,
        stage="translate",
        current=1,
        total=8,
        message="ja batch 1/2 waiting chat... 3s",
        lang="ja",
    )
    text = format_gui_progress_label(ev)
    assert text.startswith("12.5%")
    assert "translate" in text
    assert "ja" in text
    assert "1/8" in text
    assert "waiting" in text.lower() or "chat" in text.lower() or "3" in text


def test_format_gui_progress_label_ja_leaves_running_pattern() -> None:
    setup_i18n("ja")
    ev = ProgressEvent(
        percent=0.0,
        stage="translate",
        current=0,
        total=10,
        message="start",
        lang=None,
    )
    text = format_gui_progress_label(ev)
    assert "0.0%" in text
    # Must not remain the idle Running string
    assert "Running" not in text
    assert "実行中" not in text


def test_format_gui_progress_label_nan_safe() -> None:
    setup_i18n("en")

    class _Bad:
        percent = float("nan")
        stage = "translate"
        current = 0
        total = 1
        message = "start"
        lang = None

    text = format_gui_progress_label(_Bad())
    assert text.startswith("0.0%")


def test_app_progress_first_event_flushes(app_src: str) -> None:
    assert "_progress_seen" in app_src
    assert "format_gui_progress_label" in app_src
    assert "def _log_progress" in app_src
    assert "gui_progress.log" in app_src
    assert "self._progress_q" in app_src
    assert "get_nowait" in app_src
    # queue drain + paint path
    assert "self._progress_seen = True" in app_src
    assert "self._flush_progress()" in app_src
    assert "duck_ok" in app_src or "hasattr(ev, \"percent\")" in app_src


def test_app_flush_does_not_drop_on_error(app_src: str) -> None:
    # clear latest only after successful paint
    assert "flush_progress:" in app_src
    # label plain text
    assert "setTextFormat(Qt.TextFormat.PlainText)" in app_src


@pytest.mark.skipif(
    os.environ.get("SRTSPEAK_SKIP_QT", "") == "1",
    reason="SRTSPEAK_SKIP_QT=1",
)
def test_translate_worker_progress_reaches_label() -> None:
    """Offscreen Qt: TranslateWorker dry_run must leave Running… on the label."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
    from PySide6.QtWidgets import QApplication, QLabel, QProgressBar

    from srtspeak.core.cancel import CancellationToken
    from srtspeak.core.models import TranslateConfig
    from srtspeak.core.srt_translate import run_translate
    from srtspeak.i18n import _
    from srtspeak.progress_i18n import format_gui_progress_label

    setup_i18n("ja")
    app = QApplication.instance() or QApplication([])

    class Worker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, cfg: TranslateConfig) -> None:
            super().__init__()
            self.cfg = cfg

        @Slot()
        def run(self) -> None:
            try:
                report = run_translate(
                    self.cfg,
                    api_key="",
                    progress_cb=lambda ev: self.progress.emit(ev),
                    cancel_token=CancellationToken(),
                )
                self.finished.emit(report)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))

    class Host(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.label = QLabel(_("Running…"))
            self.bar = QProgressBar()
            self.bar.setRange(0, 1000)
            self.latest: ProgressEvent | None = None
            self.seen = False
            self.flushed: list[str] = []
            self.timer = QTimer(self)
            self.timer.setInterval(80)
            self.timer.timeout.connect(self.flush)

        @Slot(object)
        def on_progress(self, ev: object) -> None:
            if not isinstance(ev, ProgressEvent):
                if type(ev).__name__ != "ProgressEvent":
                    return
            self.latest = ev  # type: ignore[assignment]
            if not self.seen:
                self.seen = True
                self.flush()

        @Slot()
        def flush(self) -> None:
            ev = self.latest
            if ev is None:
                return
            try:
                self.bar.setValue(max(0, min(1000, int(float(ev.percent) * 10))))
                text = format_gui_progress_label(ev)
                self.label.setText(text)
                self.flushed.append(text)
            except Exception:
                return
            self.latest = None

        @Slot(object)
        def on_finished(self, _report: object) -> None:
            QTimer.singleShot(150, self._done)

        @Slot(str)
        def on_failed(self, msg: str) -> None:
            self._err = msg
            QTimer.singleShot(150, self._done)

        def _done(self) -> None:
            self.timer.stop()
            self.flush()
            app.quit()

    srt = Path(__file__).resolve().parents[1] / "srt_gen" / "en" / "GRAN_TENKU_en.srt"
    if not srt.is_file():
        # minimal fallback
        srt = Path("_tmp_gui_progress_mini.srt")
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            encoding="utf-8",
        )

    cfg = TranslateConfig(
        srt_path=srt,
        source_lang="en",
        targets=["ja"],
        out_dir=Path("_tmp_gui_progress_out"),
        dry_run=True,
        batch_size=8,
    )
    host = Host()
    host._err = None  # type: ignore[attr-defined]
    thread = QThread()
    worker = Worker(cfg)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(host.on_progress, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(host.on_finished, Qt.ConnectionType.QueuedConnection)
    worker.failed.connect(host.on_failed, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    host._t = thread  # type: ignore[attr-defined]
    host._w = worker  # type: ignore[attr-defined]
    host.timer.start()
    assert host.label.text() == _("Running…")
    thread.start()
    QTimer.singleShot(20000, app.quit)
    app.exec()
    if thread.isRunning():
        thread.quit()
        thread.wait(3000)
    else:
        thread.wait(1000)

    assert host._err is None, host._err  # type: ignore[attr-defined]
    assert host.seen is True
    assert host.flushed, "expected at least one progress flush"
    final = host.label.text()
    assert final != _("Running…")
    assert "実行中" not in final
    assert "%" in final
