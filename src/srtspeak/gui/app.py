"""Minimal PySide6 GUI entry (optional)."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        from PySide6.QtCore import QObject, QThread, Signal, Slot
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QProgressBar,
            QSpinBox,
            QVBoxLayout,
            QWidget,
            QCheckBox,
        )
    except ImportError as exc:
        print(f"PySide6 required: {exc}", file=sys.stderr)
        return 2

    from srtspeak.core.cancel import BuildCancelled, CancellationToken
    from srtspeak.core.languages import (
        guess_lang_from_filename,
        internal_lang_from_code,
        list_language_options,
        resolve_language_code,
    )
    from srtspeak.core.models import BuildConfig
    from srtspeak.core.pipeline import BuildService
    from srtspeak.core.progress import ProgressEvent
    from srtspeak.core.secrets import api_key_status, resolve_api_key
    from srtspeak.core.srt_parser import SrtParseError, parse_srt
    from srtspeak.core.util import resolve_out_dir
    from srtspeak.core.voices import DEFAULT_VOICE_ID, list_builtin_voices
    from srtspeak.i18n import _, setup_i18n

    setup_i18n(None)

    class Worker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(
            self,
            config: BuildConfig,
            api_key: str | None,
            token: CancellationToken,
        ) -> None:
            super().__init__()
            self.config = config
            self.api_key = api_key
            self.token = token

        @Slot()
        def run(self) -> None:
            try:
                svc = BuildService(
                    self.config,
                    api_key=self.api_key,
                    progress_cb=lambda ev: self.progress.emit(ev),
                    cancel_token=self.token,
                )
                report = svc.run()
                self.finished.emit(report)
            except BuildCancelled:
                self.failed.emit("cancelled")
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("srtspeak")
            self._token = CancellationToken()
            self._thread: QThread | None = None
            self._worker: Worker | None = None
            self._session_key: str | None = None
            self._pending_result: tuple[str, object] | None = None

            root = QWidget()
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)
            form = QFormLayout()

            self.srt_edit = QLineEdit()
            self.srt_edit.editingFinished.connect(self._on_srt_path_changed)
            browse = QPushButton("…")
            browse.clicked.connect(self._browse_srt)
            row = QHBoxLayout()
            row.addWidget(self.srt_edit)
            row.addWidget(browse)
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(_("SRT file"), wrap)

            self.cue_count_label = QLabel(_("Cues: —"))
            form.addRow("", self.cue_count_label)

            # Single language selector: API BCP-47 code (language_code).
            # Internal out-dir key (lang) is derived automatically.
            self.lang_combo = QComboBox()
            for opt in list_language_options():
                label = _("{name} ({code})").format(name=_(opt.label), code=opt.code)
                self.lang_combo.addItem(label, opt.code)
            self._select_language_code("ja")
            form.addRow(_("Language"), self.lang_combo)

            self.voice_combo = QComboBox()
            for v in list_builtin_voices():
                # voice_id is a proper name; description is localizable
                self.voice_combo.addItem(
                    f"{v.voice_id} — {_(v.description)}", v.voice_id
                )
            idx = self.voice_combo.findData(DEFAULT_VOICE_ID)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
            form.addRow(_("Voice"), self.voice_combo)

            self.out_edit = QLineEdit("out")
            form.addRow(_("Output folder"), self.out_edit)

            self.limit_spin = QSpinBox()
            self.limit_spin.setRange(0, 100000)
            self.limit_spin.setSpecialValueText(_("all"))
            self.limit_spin.setValue(0)
            self.limit_spin.setToolTip(
                _(
                    "Process only the first N cues. 0 = all cues in the SRT."
                )
            )
            form.addRow(_("Max cues (0 = all)"), self.limit_spin)

            self.dry_run_cb = QCheckBox(_("Dry-run (estimate only, no TTS)"))
            form.addRow("", self.dry_run_cb)
            self.ja_yomi_cb = QCheckBox(
                _("Japanese yomi (kanji → hiragana)")
            )
            self.ja_yomi_cb.setChecked(True)
            form.addRow("", self.ja_yomi_cb)

            self.key_edit = QLineEdit()
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.key_status = QLabel(self._key_status_text())
            form.addRow(_("API key (XAI_API_KEY)"), self.key_edit)
            form.addRow("", self.key_status)

            layout.addLayout(form)

            self.bar = QProgressBar()
            self.bar.setRange(0, 1000)
            self.label = QLabel(_("Ready"))
            layout.addWidget(self.bar)
            layout.addWidget(self.label)

            btns = QHBoxLayout()
            self.start_btn = QPushButton(_("Start"))
            self.cancel_btn = QPushButton(_("Cancel"))
            self.cancel_btn.setEnabled(False)
            self.start_btn.clicked.connect(self._start)
            self.cancel_btn.clicked.connect(self._cancel)
            btns.addWidget(self.start_btn)
            btns.addWidget(self.cancel_btn)
            layout.addLayout(btns)

        def _key_status_text(self) -> str:
            if api_key_status() == "set (env)":
                return _("Status: using environment variable")
            return _("Status: not set (enter key above for this session)")

        def _select_language_code(self, code: str) -> None:
            idx = self.lang_combo.findData(code)
            if idx < 0:
                # try resolve aliases / defaults
                try:
                    resolved = resolve_language_code(lang=code, explicit=None)
                except ValueError:
                    resolved = code
                idx = self.lang_combo.findData(resolved)
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)

        def _current_language_code(self) -> str:
            data = self.lang_combo.currentData()
            return str(data) if data else "ja"

        def _browse_srt(self) -> None:
            path, _unused = QFileDialog.getOpenFileName(
                self,
                _("Open SRT"),
                "",
                _("SRT files (*.srt);;All files (*.*)"),
            )
            if path:
                self.srt_edit.setText(path)
                guessed = guess_lang_from_filename(path)
                if guessed:
                    try:
                        code = resolve_language_code(lang=guessed, explicit=None)
                    except ValueError:
                        code = guessed
                    self._select_language_code(code)
                self._refresh_cue_count()

        def _on_srt_path_changed(self) -> None:
            self._refresh_cue_count()

        def _refresh_cue_count(self) -> None:
            path_text = self.srt_edit.text().strip()
            if not path_text:
                self.cue_count_label.setText(_("Cues: —"))
                return
            path = Path(path_text)
            if not path.is_file():
                self.cue_count_label.setText(_("Cues: file not found"))
                return
            try:
                text = path.read_text(encoding="utf-8-sig")
                cues = parse_srt(text)
            except SrtParseError as exc:
                self.cue_count_label.setText(
                    _("Cues: parse error ({detail})").format(detail=str(exc))
                )
                return
            except OSError as exc:
                self.cue_count_label.setText(
                    _("Cues: read error ({detail})").format(detail=exc)
                )
                return
            n = len(cues)
            self.cue_count_label.setText(
                _("Cues in SRT: {count}").format(count=n)
            )

        def _job_running(self) -> bool:
            return self._thread is not None and self._thread.isRunning()

        def _cleanup_worker_thread(self) -> None:
            """Drop refs after the QThread has fully stopped."""
            worker = self._worker
            thread = self._thread
            self._worker = None
            self._thread = None
            if worker is not None:
                worker.deleteLater()
            if thread is not None:
                thread.deleteLater()

        def _start(self) -> None:
            if self._job_running():
                return
            # Ensure previous thread objects are gone before starting again.
            if self._thread is not None and not self._thread.isRunning():
                self._cleanup_worker_thread()

            srt = Path(self.srt_edit.text().strip())
            if not srt.is_file():
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("SRT file not found:\n{path}").format(path=srt),
                )
                return
            language_code = self._current_language_code()
            try:
                language_code = resolve_language_code(
                    lang=language_code, explicit=language_code
                )
                lang = internal_lang_from_code(language_code)
            except ValueError as exc:
                QMessageBox.critical(self, _("Error"), str(exc))
                return
            voice_id = self.voice_combo.currentData() or DEFAULT_VOICE_ID
            limit = self.limit_spin.value() or None
            dry = self.dry_run_cb.isChecked()
            typed = self.key_edit.text().strip()
            self._session_key = typed or self._session_key
            api_key = resolve_api_key(prompt=False, session_key=self._session_key)
            if not dry and not api_key:
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _(
                        "XAI_API_KEY is not set.\n"
                        "Set the environment variable or enter the key above."
                    ),
                )
                return

            cfg = BuildConfig(
                srt_path=srt,
                lang=lang,
                language_code=language_code,
                out_dir=resolve_out_dir(self.out_edit.text().strip() or None, lang),
                voice_id=str(voice_id),
                limit=limit,
                dry_run=dry,
                ja_yomi=self.ja_yomi_cb.isChecked(),
            )
            self._token = CancellationToken()
            self._pending_result = None
            self._thread = QThread(self)
            self._worker = Worker(cfg, api_key, self._token)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(self._on_progress)
            # Keep worker alive until the thread actually finishes, then show UI.
            self._worker.finished.connect(self._on_worker_finished)
            self._worker.failed.connect(self._on_worker_failed)
            self._worker.finished.connect(self._thread.quit)
            self._worker.failed.connect(self._thread.quit)
            self._thread.finished.connect(self._on_thread_finished)
            self.start_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.setText(_("Cancel"))
            self.label.setText(_("Running…"))
            self.bar.setValue(0)
            self._thread.start()

        def _cancel(self) -> None:
            self._token.cancel()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(_("Cancelling…"))

        @Slot(object)
        def _on_progress(self, ev: object) -> None:
            if not isinstance(ev, ProgressEvent):
                return
            self.bar.setValue(int(ev.percent * 10))
            self.label.setText(
                _("{percent:.1f}%  {stage}  {current}/{total}  {message}").format(
                    percent=ev.percent,
                    stage=ev.stage,
                    current=ev.current,
                    total=ev.total,
                    message=ev.message or "",
                )
            )

        @Slot(object)
        def _on_worker_finished(self, report: object) -> None:
            self._pending_result = ("ok", report)

        @Slot(str)
        def _on_worker_failed(self, msg: str) -> None:
            self._pending_result = ("err", msg)

        def _format_report_summary(self, report: object) -> tuple[str, str, str]:
            """Return (window_title, label_text, dialog_body) for a finished report."""
            if not isinstance(report, dict):
                status = "?"
                body = _("Build finished.\nStatus: {status}").format(status=status)
                return _("Done"), _("Finished: {status}").format(status=status), body

            status = str(report.get("status", "?"))
            cues = report.get("processed_count", report.get("cue_count", "?"))
            total = report.get("cue_count", cues)
            lang = report.get("lang", "?")
            language_code = report.get("language_code", "?")
            voice_id = report.get("voice_id", "?")
            out_dir = report.get("out_dir") or ""
            track_path = report.get("track_path") or report.get("track") or ""
            report_path = ""
            if out_dir:
                report_path = str(Path(out_dir) / "report.json")
            elif track_path:
                report_path = str(Path(str(track_path)).with_name("report.json"))

            if status == "dry_run":
                chars = report.get("total_chars", 0)
                cost = report.get("estimated_cost_usd", 0.0)
                try:
                    cost_s = f"{float(cost):.4f}"
                except (TypeError, ValueError):
                    cost_s = str(cost)
                ja_yomi = report.get("ja_yomi", False)
                title = _("Dry-run result")
                label = _(
                    "Dry-run: {cues} cues, {chars} chars, ~${cost} USD"
                ).format(cues=cues, chars=chars, cost=cost_s)
                body = _(
                    "Dry-run complete (no TTS).\n"
                    "\n"
                    "Language: {lang} ({language_code})\n"
                    "Voice: {voice_id}\n"
                    "Cues: {cues}\n"
                    "Characters: {chars}\n"
                    "Estimated cost: ~${cost} USD\n"
                    "Japanese yomi: {ja_yomi}\n"
                    "\n"
                    "Report:\n{report_path}"
                ).format(
                    lang=lang,
                    language_code=language_code,
                    voice_id=voice_id,
                    cues=cues,
                    chars=chars,
                    cost=cost_s,
                    ja_yomi=_("on") if ja_yomi else _("off"),
                    report_path=report_path or _("(unknown)"),
                )
                return title, label, body

            title = _("Done")
            label = _("Finished: {status}").format(status=status)
            body_lines = [
                _("Build finished.\nStatus: {status}").format(status=status),
                "",
                _("Language: {lang} ({language_code})").format(
                    lang=lang, language_code=language_code
                ),
                _("Voice: {voice_id}").format(voice_id=voice_id),
                _("Cues: {processed}/{total}").format(processed=cues, total=total),
            ]
            if track_path:
                body_lines.append(_("Track:\n{path}").format(path=track_path))
            if report_path:
                body_lines.append(_("Report:\n{path}").format(path=report_path))
            dur = report.get("track_duration_ms")
            err = report.get("duration_error_ms")
            if dur is not None:
                body_lines.append(
                    _("Track duration: {ms:.0f} ms").format(ms=float(dur))
                )
            if err is not None:
                body_lines.append(
                    _("Duration error: {ms:.0f} ms").format(ms=float(err))
                )
            return title, label, "\n".join(body_lines)

        @Slot()
        def _on_thread_finished(self) -> None:
            pending = self._pending_result
            self._pending_result = None
            self._cleanup_worker_thread()
            self.start_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(_("Cancel"))
            if pending is None:
                self.label.setText(_("Ready"))
                return
            kind, payload = pending
            if kind == "ok":
                title, label, body = self._format_report_summary(payload)
                self.bar.setValue(1000)
                self.label.setText(label)
                QMessageBox.information(self, title, body)
                return
            msg = str(payload)
            if msg == "cancelled":
                self.label.setText(_("Cancelled"))
                QMessageBox.warning(
                    self,
                    _("Cancelled"),
                    _("Build was cancelled."),
                )
            else:
                self.label.setText(msg)
                QMessageBox.critical(self, _("Error"), msg)

        def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
            if self._job_running():
                self._token.cancel()
                thread = self._thread
                if thread is not None:
                    thread.quit()
                    if not thread.wait(5000):
                        thread.terminate()
                        thread.wait(2000)
                self._cleanup_worker_thread()
            super().closeEvent(event)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(580, 440)
    win.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
