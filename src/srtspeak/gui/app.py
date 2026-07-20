"""PySide6 GUI: Build + Translate tabs (optional extra [gui])."""

from __future__ import annotations

import json
import os
import queue
import sys
from pathlib import Path


def main() -> int:
    try:
        from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QFileDialog,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMessageBox,
            QProgressBar,
            QPushButton,
            QSpinBox,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
    except ImportError as exc:
        print(f"PySide6 required: {exc}", file=sys.stderr)
        return 2

    from srtspeak.core.cancel import BuildCancelled, CancellationToken
    from srtspeak.core.languages import (
        guess_lang_from_filename,
        internal_lang_from_code,
        list_language_options,
        normalize_language_code,
        resolve_language_code,
    )
    from srtspeak.core.models import BuildConfig, TranslateConfig
    from srtspeak.core.pipeline import BuildService
    from srtspeak.core.progress import ProgressEvent
    from srtspeak.core.secrets import (
        api_key_status,
        clear_api_key_secure,
        has_api_key_secure,
        resolve_api_key,
        save_api_key_secure,
        secure_store_available,
        secure_store_backend_label,
    )
    from srtspeak.core.srt_parser import SrtEncodingError, SrtParseError, parse_srt, read_srt_text
    from srtspeak.core.srt_translate import TranslateError, run_translate
    from srtspeak.core.translate_glossary import (
        GlossaryError,
        load_glossary,
        merge_glossary,
        save_glossary,
        suggest_glossary,
    )
    from srtspeak.core.util import resolve_out_dir
    from srtspeak.core.voices import DEFAULT_VOICE_ID, list_builtin_voices
    from srtspeak.i18n import _, setup_i18n
    from srtspeak.progress_i18n import format_gui_progress_label, localize_message, localize_stage

    setup_i18n(None)

    _SETTINGS_FILE = Path("gui_settings.json")

    def _load_settings() -> dict:
        try:
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_settings(data: dict) -> None:
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _diag_log_dir() -> Path:
        """Fixed diagnostic log dir (not out/srt_gen; not process cwd)."""
        return Path("work")

    def _log_crash(err: str) -> None:
        try:
            d = _diag_log_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "gui_crash_py.log", "a", encoding="utf-8") as f:
                f.write(f"[CRASH] {err}\n")
        except OSError:
            pass

    def _log_progress(msg: str) -> None:
        """Append GUI progress diagnostics when SRTSPEAK_GUI_PROGRESS_LOG=1.

        Default OFF. Path: work/gui_progress.log (never under out/srt_gen).
        """
        flag = os.environ.get("SRTSPEAK_GUI_PROGRESS_LOG", "0").strip().lower()
        if flag not in ("1", "true", "yes", "on"):
            return
        try:
            import time as _time

            d = _diag_log_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "gui_progress.log", "a", encoding="utf-8") as f:
                f.write(f"{_time.strftime('%H:%M:%S')} {msg}\n")
        except OSError:
            pass

    class BuildWorker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(
            self,
            config: BuildConfig,
            api_key: str | None,
            token: CancellationToken,
            progress_q: queue.SimpleQueue | None = None,
        ) -> None:
            super().__init__()
            self.config = config
            self.api_key = api_key
            self.token = token
            self.progress_q = progress_q

        def _emit_progress(self, ev: object) -> None:
            # Queue is thread-safe; Signal alone can stall until QThread ends on some hosts.
            if self.progress_q is not None:
                try:
                    self.progress_q.put(ev)
                except Exception:  # noqa: BLE001
                    pass
            self.progress.emit(ev)

        @Slot()
        def run(self) -> None:
            try:
                svc = BuildService(
                    self.config,
                    api_key=self.api_key,
                    progress_cb=self._emit_progress,
                    cancel_token=self.token,
                )
                report = svc.run()
                self.finished.emit(report)
            except BuildCancelled:
                self.failed.emit("cancelled")
            except Exception as exc:  # noqa: BLE001
                import traceback

                _log_crash(traceback.format_exc())
                self.failed.emit(str(exc))

    class TranslateWorker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(
            self,
            config: TranslateConfig,
            api_key: str,
            token: CancellationToken,
            progress_q: queue.SimpleQueue | None = None,
        ) -> None:
            super().__init__()
            self.config = config
            self.api_key = api_key
            self.token = token
            self.progress_q = progress_q

        def _emit_progress(self, ev: object) -> None:
            try:
                _log_progress(
                    "worker.emit "
                    f"type={type(ev).__name__} "
                    f"mod={getattr(type(ev), '__module__', '?')} "
                    f"pct={getattr(ev, 'percent', None)!r} "
                    f"stage={getattr(ev, 'stage', None)!r} "
                    f"msg={getattr(ev, 'message', None)!r}"
                )
            except Exception:  # noqa: BLE001
                pass
            if self.progress_q is not None:
                try:
                    self.progress_q.put(ev)
                except Exception:  # noqa: BLE001
                    pass
            self.progress.emit(ev)

        @Slot()
        def run(self) -> None:
            try:
                report = run_translate(
                    self.config,
                    api_key=self.api_key,
                    progress_cb=self._emit_progress,
                    cancel_token=self.token,
                )
                self.finished.emit(report)
            except BuildCancelled:
                self.failed.emit("cancelled")
            except TranslateError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # noqa: BLE001
                import traceback

                _log_crash(traceback.format_exc())
                self.failed.emit(str(exc))

    class GlossaryWorker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(
            self,
            *,
            srt_path: Path,
            source_lang: str,
            targets: list[str],
            out_path: Path,
            api_key: str,
            merge_existing: bool,
            token: CancellationToken,
            limit: int | None,
            progress_q: queue.SimpleQueue | None = None,
        ) -> None:
            super().__init__()
            self.srt_path = srt_path
            self.source_lang = source_lang
            self.targets = targets
            self.out_path = out_path
            self.api_key = api_key
            self.merge_existing = merge_existing
            self.token = token
            self.limit = limit
            self.progress_q = progress_q

        def _emit_progress(self, ev: object) -> None:
            if self.progress_q is not None:
                try:
                    self.progress_q.put(ev)
                except Exception:  # noqa: BLE001
                    pass
            self.progress.emit(ev)

        @Slot()
        def run(self) -> None:
            try:
                from srtspeak.core.srt_parser import apply_limit, parse_srt, read_srt_text

                self.token.check()
                cues = parse_srt(read_srt_text(self.srt_path)[0])
                cues = apply_limit(cues, self.limit)
                suggested = suggest_glossary(
                    cues,
                    source_lang=self.source_lang,
                    targets=self.targets,
                    api_key=self.api_key,
                    progress_cb=self._emit_progress,
                )
                self.token.check()
                if self.merge_existing and self.out_path.is_file():
                    base = load_glossary(self.out_path)
                    if base:
                        suggested = merge_glossary(base, suggested, prefer="base")
                save_glossary(self.out_path, suggested)
                self.finished.emit(
                    {
                        "status": "ok",
                        "path": str(self.out_path),
                        "terms": len(suggested.get("terms") or []),
                        "tone": suggested.get("tone") or "",
                    }
                )
            except BuildCancelled:
                self.failed.emit("cancelled")
            except GlossaryError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:  # noqa: BLE001
                import traceback

                _log_crash(traceback.format_exc())
                self.failed.emit(str(exc))

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("srtspeak")
            self._token = CancellationToken()
            self._thread: QThread | None = None
            self._worker: QObject | None = None
            self._session_key: str | None = None
            self._pending_result: tuple[str, object] | None = None
            self._job_kind: str | None = None
            self._last_result_kind: str = "build"
            self._latest_progress: ProgressEvent | None = None
            self._progress_seen: bool = False
            self._progress_q: queue.SimpleQueue = queue.SimpleQueue()
            self._progress_timer = QTimer(self)
            self._progress_timer.setInterval(80)
            self._progress_timer.timeout.connect(self._flush_progress)

            root = QWidget()
            self.setCentralWidget(root)
            outer = QVBoxLayout(root)

            # Shared API key row
            key_row = QHBoxLayout()
            key_row.addWidget(QLabel(_("API key (XAI_API_KEY)")))
            self.key_edit = QLineEdit()
            self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            key_row.addWidget(self.key_edit)
            self.key_status = QLabel(self._key_status_text())
            key_row.addWidget(self.key_status)
            self.save_key_btn = QPushButton(_("Save on this PC"))
            self.save_key_btn.setEnabled(secure_store_available())
            self.save_key_btn.setToolTip(
                _(
                    "Save via OS credential store "
                    "(Windows Credential Locker / macOS Keychain / "
                    "Linux Secret Service). Backend: "
                )
                + secure_store_backend_label()
                if secure_store_available()
                else _(
                    "No secure store. Install: pip install keyring "
                    "(or set XAI_API_KEY)."
                )
            )
            self.clear_key_btn = QPushButton(_("Clear saved"))
            self.clear_key_btn.setEnabled(
                secure_store_available() and has_api_key_secure()
            )
            self.save_key_btn.clicked.connect(self._save_api_key_secure)
            self.clear_key_btn.clicked.connect(self._clear_api_key_secure)
            key_row.addWidget(self.save_key_btn)
            key_row.addWidget(self.clear_key_btn)
            outer.addLayout(key_row)

            self.tabs = QTabWidget()
            outer.addWidget(self.tabs)

            self._build_tab = QWidget()
            self._translate_tab = QWidget()
            self.tabs.addTab(self._build_tab, _("Build"))
            self.tabs.addTab(self._translate_tab, _("Translate"))

            self._init_build_tab()
            self._init_translate_tab()

            # Shared progress + actions
            self.bar = QProgressBar()
            self.bar.setRange(0, 1000)
            self.label = QLabel(_("Ready"))
            self.label.setTextFormat(Qt.TextFormat.PlainText)
            self.label.setWordWrap(True)
            self.label.setMinimumHeight(18)
            outer.addWidget(self.bar)
            outer.addWidget(self.label)

            btns = QHBoxLayout()
            self.start_btn = QPushButton(_("Start"))
            self.cancel_btn = QPushButton(_("Cancel"))
            self.cancel_btn.setEnabled(False)
            self.start_btn.clicked.connect(self._start)
            self.cancel_btn.clicked.connect(self._cancel)
            btns.addWidget(self.start_btn)
            btns.addWidget(self.cancel_btn)
            outer.addLayout(btns)

            self.tabs.currentChanged.connect(self._on_tab_changed)
            self._load_and_apply_settings()
            self._refresh_key_ui()
            self._on_tab_changed(self.tabs.currentIndex())

        def _key_status_text(self) -> str:
            st = api_key_status()
            if st == "set (env)":
                return _("Status: using environment variable")
            if st == "set (keyring)":
                return _("Status: saved on this PC (keyring)")
            if st == "set (dpapi)":
                return _("Status: saved on this PC (DPAPI)")
            return _("Status: not set (enter key above for this session)")

        def _refresh_key_ui(self) -> None:
            self.key_status.setText(self._key_status_text())
            avail = secure_store_available()
            if hasattr(self, "save_key_btn"):
                self.save_key_btn.setEnabled(avail)
            if hasattr(self, "clear_key_btn"):
                self.clear_key_btn.setEnabled(avail and has_api_key_secure())

        def _save_api_key_secure(self) -> None:
            if not secure_store_available():
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _(
                        "No secure store. Install: pip install keyring "
                        "(or set XAI_API_KEY)."
                    ),
                )
                return
            typed = self.key_edit.text().strip()
            key = typed or resolve_api_key(prompt=False, session_key=self._session_key)
            if not key:
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _(
                        "Enter an API key above first "
                        "(or set XAI_API_KEY in the environment)."
                    ),
                )
                return
            try:
                backend = save_api_key_secure(key)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("Could not save key: ") + str(exc),
                )
                return
            self._session_key = key
            # Do not leave plaintext lingering in the field after save.
            self.key_edit.clear()
            self._refresh_key_ui()
            QMessageBox.information(
                self,
                _("Saved"),
                _(
                    "API key saved in the OS credential store "
                    "(this user only).\n"
                    "Backend: "
                )
                + str(backend),
            )

        def _clear_api_key_secure(self) -> None:
            removed = clear_api_key_secure()
            self._refresh_key_ui()
            if removed:
                QMessageBox.information(
                    self,
                    _("Cleared"),
                    _("Saved API key removed from this PC."),
                )
            else:
                QMessageBox.information(
                    self,
                    _("Cleared"),
                    _("No saved API key found."),
                )

        def _on_tab_changed(self, _index: int) -> None:
            if self._job_running():
                return
            tab = self.tabs.currentWidget()
            if tab is self._translate_tab:
                self.start_btn.setText(_("Translate"))
            else:
                self.start_btn.setText(_("Start"))

        # ----- Build tab -----
        def _init_build_tab(self) -> None:
            layout = QVBoxLayout(self._build_tab)
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

            self.lang_combo = QComboBox()
            for opt in list_language_options():
                label = _("{name} ({code})").format(name=_(opt.label), code=opt.code)
                self.lang_combo.addItem(label, opt.code)
            self._select_language_code(self.lang_combo, "ja")
            detect_btn = QPushButton(_("Detect"))
            detect_btn.clicked.connect(self._detect_language_build)
            row_lang = QHBoxLayout()
            row_lang.addWidget(self.lang_combo)
            row_lang.addWidget(detect_btn)
            wrap_lang = QWidget()
            wrap_lang.setLayout(row_lang)
            form.addRow(_("Language"), wrap_lang)

            self.voice_combo = QComboBox()
            for v in list_builtin_voices():
                self.voice_combo.addItem(
                    f"{v.voice_id} — {_(v.description)}", v.voice_id
                )
            idx = self.voice_combo.findData(DEFAULT_VOICE_ID)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
            form.addRow(_("Voice"), self.voice_combo)

            self.out_edit = QLineEdit("out")
            form.addRow(_("Output folder"), self.out_edit)

            self.base_wav_edit = QLineEdit()
            browse_bw = QPushButton("…")
            browse_bw.clicked.connect(self._browse_base_wav)
            row_bw = QHBoxLayout()
            row_bw.addWidget(self.base_wav_edit)
            row_bw.addWidget(browse_bw)
            wrap_bw = QWidget()
            wrap_bw.setLayout(row_bw)
            form.addRow(_("Base WAV (mix onto)"), wrap_bw)

            self.limit_spin = QSpinBox()
            self.limit_spin.setRange(0, 100000)
            self.limit_spin.setSpecialValueText(_("all"))
            self.limit_spin.setValue(0)
            self.limit_spin.setToolTip(
                _("Process only the first N cues. 0 = all cues in the SRT.")
            )
            form.addRow(_("Max cues (0 = all)"), self.limit_spin)

            self.dry_run_cb = QCheckBox(_("Dry-run (estimate only, no TTS)"))
            form.addRow("", self.dry_run_cb)
            self.ja_yomi_cb = QCheckBox(_("Japanese yomi (kanji → hiragana)"))
            self.ja_yomi_cb.setChecked(True)
            form.addRow("", self.ja_yomi_cb)
            self.no_cache_cb = QCheckBox(
                _("Ignore existing TTS/ja_yomi caches (still write fresh)")
            )
            form.addRow("", self.no_cache_cb)
            self.strip_emoticons_cb = QCheckBox(
                _("Strip kaomoji for TTS only (emoji kept; SRT unchanged)")
            )
            self.strip_emoticons_cb.setChecked(True)
            form.addRow("", self.strip_emoticons_cb)

            layout.addLayout(form)
            layout.addStretch(1)

        # ----- Translate tab -----
        def _init_translate_tab(self) -> None:
            layout = QVBoxLayout(self._translate_tab)
            form = QFormLayout()

            self.tr_srt_edit = QLineEdit()
            self.tr_srt_edit.editingFinished.connect(self._on_tr_srt_changed)
            browse = QPushButton("…")
            browse.clicked.connect(self._browse_tr_srt)
            row = QHBoxLayout()
            row.addWidget(self.tr_srt_edit)
            row.addWidget(browse)
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(_("Source SRT"), wrap)

            self.tr_cue_label = QLabel(_("Cues: —"))
            form.addRow("", self.tr_cue_label)

            self.tr_source_combo = QComboBox()
            for opt in list_language_options():
                label = _("{name} ({code})").format(name=_(opt.label), code=opt.code)
                self.tr_source_combo.addItem(label, opt.code)
            self._select_language_code(self.tr_source_combo, "ja")
            detect_btn = QPushButton(_("Detect"))
            detect_btn.clicked.connect(self._detect_language_translate)
            row_src = QHBoxLayout()
            row_src.addWidget(self.tr_source_combo)
            row_src.addWidget(detect_btn)
            wrap_src = QWidget()
            wrap_src.setLayout(row_src)
            form.addRow(_("Source language"), wrap_src)

            tgt_box = QGroupBox(_("Target languages"))
            tgt_layout = QVBoxLayout(tgt_box)
            self.tr_target_list = QListWidget()
            self.tr_target_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
            for opt in list_language_options():
                label = _("{name} ({code})").format(name=_(opt.label), code=opt.code)
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, opt.code)
                self.tr_target_list.addItem(item)
            # sensible defaults
            for code in ("en", "pt-BR"):
                self._set_target_checked(code, True)
            tgt_layout.addWidget(self.tr_target_list)
            btn_row = QHBoxLayout()
            btn_all = QPushButton(_("Select all"))
            btn_none = QPushButton(_("Clear"))
            btn_all.clicked.connect(self._tr_select_all_targets)
            btn_none.clicked.connect(self._tr_clear_targets)
            btn_row.addWidget(btn_all)
            btn_row.addWidget(btn_none)
            tgt_layout.addLayout(btn_row)
            form.addRow(tgt_box)

            self.tr_out_edit = QLineEdit("srt_gen")
            form.addRow(_("Output folder"), self.tr_out_edit)

            self.tr_glossary_edit = QLineEdit()
            browse_g = QPushButton("…")
            browse_g.clicked.connect(self._browse_glossary)
            suggest_g = QPushButton(_("Suggest"))
            suggest_g.setToolTip(
                _("Generate glossary from source SRT via Grok Chat")
            )
            suggest_g.clicked.connect(self._suggest_glossary)
            row_g = QHBoxLayout()
            row_g.addWidget(self.tr_glossary_edit)
            row_g.addWidget(browse_g)
            row_g.addWidget(suggest_g)
            wrap_g = QWidget()
            wrap_g.setLayout(row_g)
            form.addRow(_("Glossary (JSON)"), wrap_g)

            self.tr_length_combo = QComboBox()
            for mode, label in (
                ("off", _("Off")),
                ("hint", _("Hint (default)")),
                ("enforce", _("Enforce (2nd pass)")),
                ("report-only", _("Report only")),
            ):
                self.tr_length_combo.addItem(label, mode)
            self.tr_length_combo.setCurrentIndex(1)
            form.addRow(_("Length mode"), self.tr_length_combo)

            self.tr_limit_spin = QSpinBox()
            self.tr_limit_spin.setRange(0, 100000)
            self.tr_limit_spin.setSpecialValueText(_("all"))
            self.tr_limit_spin.setValue(0)
            form.addRow(_("Max cues (0 = all)"), self.tr_limit_spin)

            self.tr_batch_spin = QSpinBox()
            self.tr_batch_spin.setRange(1, 50)
            self.tr_batch_spin.setValue(8)
            form.addRow(_("Batch size"), self.tr_batch_spin)

            self.tr_dry_run_cb = QCheckBox(_("Dry-run (estimate only, no Chat)"))
            form.addRow("", self.tr_dry_run_cb)
            self.tr_fail_fast_cb = QCheckBox(_("Fail fast (stop on first target error)"))
            form.addRow("", self.tr_fail_fast_cb)
            self.tr_no_cache_cb = QCheckBox(
                _("Ignore existing translate caches (still write fresh)")
            )
            form.addRow("", self.tr_no_cache_cb)

            self.tr_naming_combo = QComboBox()
            self.tr_naming_combo.addItem(_("{stem}_{lang}.srt"), "stem")
            self.tr_naming_combo.addItem("GRAN_TENKU_{lang}.srt", "gran_tenku")
            form.addRow(_("File naming"), self.tr_naming_combo)

            layout.addLayout(form)
            layout.addStretch(1)

        def _set_target_checked(self, code: str, checked: bool) -> None:
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for i in range(self.tr_target_list.count()):
                item = self.tr_target_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == code:
                    item.setCheckState(state)

        def _tr_select_all_targets(self) -> None:
            for i in range(self.tr_target_list.count()):
                item = self.tr_target_list.item(i)
                if item:
                    item.setCheckState(Qt.CheckState.Checked)

        def _tr_clear_targets(self) -> None:
            for i in range(self.tr_target_list.count()):
                item = self.tr_target_list.item(i)
                if item:
                    item.setCheckState(Qt.CheckState.Unchecked)

        def _selected_targets(self) -> list[str]:
            out: list[str] = []
            for i in range(self.tr_target_list.count()):
                item = self.tr_target_list.item(i)
                if item and item.checkState() == Qt.CheckState.Checked:
                    code = item.data(Qt.ItemDataRole.UserRole)
                    if code:
                        out.append(str(code))
            return out

        def _select_language_code(self, combo: QComboBox, code: str) -> None:
            idx = combo.findData(code)
            if idx < 0:
                try:
                    resolved = resolve_language_code(lang=code, explicit=None)
                except ValueError:
                    resolved = code
                idx = combo.findData(resolved)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        def _current_code(self, combo: QComboBox) -> str:
            data = combo.currentData()
            return str(data) if data else "ja"

        # ----- settings -----
        def _load_and_apply_settings(self) -> None:
            s = _load_settings()
            if s.get("srt_path"):
                self.srt_edit.setText(s["srt_path"])
                self._refresh_cue_count(self.srt_edit, self.cue_count_label)
            code = s.get("language_code", "")
            if code:
                self._select_language_code(self.lang_combo, code)
            voice = s.get("voice_id", "")
            if voice:
                idx = self.voice_combo.findData(voice)
                if idx >= 0:
                    self.voice_combo.setCurrentIndex(idx)
            if s.get("out_dir"):
                self.out_edit.setText(s["out_dir"])
            if s.get("base_wav"):
                self.base_wav_edit.setText(s["base_wav"])
            if "limit" in s:
                self.limit_spin.setValue(int(s["limit"]))
            if "dry_run" in s:
                self.dry_run_cb.setChecked(bool(s["dry_run"]))
            if "ja_yomi" in s:
                self.ja_yomi_cb.setChecked(bool(s["ja_yomi"]))
            if "strip_emoticons" in s:
                self.strip_emoticons_cb.setChecked(bool(s["strip_emoticons"]))
            if "no_cache" in s:
                self.no_cache_cb.setChecked(bool(s["no_cache"]))

            # translate
            if s.get("tr_srt_path"):
                self.tr_srt_edit.setText(s["tr_srt_path"])
                self._refresh_cue_count(self.tr_srt_edit, self.tr_cue_label)
            elif s.get("srt_path"):
                self.tr_srt_edit.setText(s["srt_path"])
                self._refresh_cue_count(self.tr_srt_edit, self.tr_cue_label)
            src = s.get("tr_source_lang", "")
            if src:
                self._select_language_code(self.tr_source_combo, src)
            targets = s.get("tr_targets") or []
            if isinstance(targets, list) and targets:
                self._tr_clear_targets()
                for t in targets:
                    self._set_target_checked(str(t), True)
            if s.get("tr_out_dir"):
                self.tr_out_edit.setText(s["tr_out_dir"])
            if s.get("tr_glossary"):
                self.tr_glossary_edit.setText(s["tr_glossary"])
            lm = s.get("tr_length_mode", "")
            if lm:
                idx = self.tr_length_combo.findData(lm)
                if idx >= 0:
                    self.tr_length_combo.setCurrentIndex(idx)
            if "tr_limit" in s:
                self.tr_limit_spin.setValue(int(s["tr_limit"]))
            if "tr_batch_size" in s:
                self.tr_batch_spin.setValue(int(s["tr_batch_size"]))
            if "tr_dry_run" in s:
                self.tr_dry_run_cb.setChecked(bool(s["tr_dry_run"]))
            if "tr_fail_fast" in s:
                self.tr_fail_fast_cb.setChecked(bool(s["tr_fail_fast"]))
            if "tr_no_cache" in s:
                self.tr_no_cache_cb.setChecked(bool(s["tr_no_cache"]))
            naming = s.get("tr_naming", "")
            if naming:
                idx = self.tr_naming_combo.findData(naming)
                if idx >= 0:
                    self.tr_naming_combo.setCurrentIndex(idx)
            tab = s.get("active_tab")
            if tab == "translate":
                self.tabs.setCurrentWidget(self._translate_tab)

        def _save_current_settings(self) -> None:
            s = {
                "srt_path": self.srt_edit.text().strip(),
                "language_code": self._current_code(self.lang_combo),
                "voice_id": self.voice_combo.currentData() or "",
                "out_dir": self.out_edit.text().strip(),
                "base_wav": self.base_wav_edit.text().strip(),
                "limit": self.limit_spin.value(),
                "dry_run": self.dry_run_cb.isChecked(),
                "ja_yomi": self.ja_yomi_cb.isChecked(),
                "strip_emoticons": self.strip_emoticons_cb.isChecked(),
                "no_cache": self.no_cache_cb.isChecked(),
                "tr_srt_path": self.tr_srt_edit.text().strip(),
                "tr_source_lang": self._current_code(self.tr_source_combo),
                "tr_targets": self._selected_targets(),
                "tr_out_dir": self.tr_out_edit.text().strip(),
                "tr_glossary": self.tr_glossary_edit.text().strip(),
                "tr_length_mode": self.tr_length_combo.currentData() or "hint",
                "tr_limit": self.tr_limit_spin.value(),
                "tr_batch_size": self.tr_batch_spin.value(),
                "tr_dry_run": self.tr_dry_run_cb.isChecked(),
                "tr_fail_fast": self.tr_fail_fast_cb.isChecked(),
                "tr_no_cache": self.tr_no_cache_cb.isChecked(),
                "tr_naming": self.tr_naming_combo.currentData() or "stem",
                "active_tab": (
                    "translate"
                    if self.tabs.currentWidget() is self._translate_tab
                    else "build"
                ),
            }
            _save_settings(s)

        # ----- browse / detect -----
        def _apply_filename_lang_guess(self, path: str | Path, combo: QComboBox) -> bool:
            """If filename hints a language, select it on combo. Return True if applied."""
            guessed = guess_lang_from_filename(path)
            if not guessed:
                return False
            try:
                code = resolve_language_code(lang=str(guessed), explicit=None)
            except ValueError:
                code = str(guessed)
            self._select_language_code(combo, code)
            return True

        def _browse_srt(self) -> None:
            path, _u = QFileDialog.getOpenFileName(
                self,
                _("Open SRT"),
                "",
                _("SRT files (*.srt);;All files (*.*)"),
            )
            if path:
                self.srt_edit.setText(path)
                self._apply_filename_lang_guess(path, self.lang_combo)
                self._refresh_cue_count(self.srt_edit, self.cue_count_label)

        def _browse_tr_srt(self) -> None:
            path, _u = QFileDialog.getOpenFileName(
                self,
                _("Open SRT"),
                "",
                _("SRT files (*.srt);;All files (*.*)"),
            )
            if path:
                self.tr_srt_edit.setText(path)
                self._apply_filename_lang_guess(path, self.tr_source_combo)
                self._refresh_cue_count(self.tr_srt_edit, self.tr_cue_label)

        def _browse_base_wav(self) -> None:
            path, _u = QFileDialog.getOpenFileName(
                self,
                _("Select base WAV"),
                "",
                _("WAV files (*.wav);;All files (*.*)"),
            )
            if path:
                self.base_wav_edit.setText(path)

        def _browse_glossary(self) -> None:
            path, _u = QFileDialog.getOpenFileName(
                self,
                _("Select glossary JSON"),
                "",
                _("JSON files (*.json);;All files (*.*)"),
            )
            if path:
                self.tr_glossary_edit.setText(path)

        def _detect_language_build(self) -> None:
            self._detect_into(self.srt_edit, self.lang_combo)

        def _detect_language_translate(self) -> None:
            self._detect_into(self.tr_srt_edit, self.tr_source_combo)

        def _detect_into(self, path_edit: QLineEdit, combo: QComboBox) -> None:
            srt_path = Path(path_edit.text().strip())
            if not srt_path.is_file():
                QMessageBox.warning(self, _("Error"), _("SRT file not found."))
                return
            try:
                text, _enc = read_srt_text(srt_path)
            except SrtEncodingError as exc:
                QMessageBox.warning(self, _("Error"), str(exc))
                return
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _("Cannot read SRT: {e}").format(e=exc),
                )
                return
            lines = [
                ln.strip()
                for ln in text.splitlines()
                if ln.strip()
                and not ln.strip().isdigit()
                and "-->" not in ln
            ]
            sample = "\n".join(lines[:10])
            if not sample:
                QMessageBox.warning(self, _("Error"), _("No text found in SRT."))
                return
            typed = self.key_edit.text().strip() or None
            api_key = (
                typed
                or os.environ.get("XAI_API_KEY")
                or os.environ.get("UAGENT_GROK_API_KEY")
            )
            if not api_key:
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _("API key required for language detection."),
                )
                return
            import json as _json
            import urllib.request

            payload = _json.dumps(
                {
                    "model": "grok-4.5",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a language detection assistant. "
                                "Respond with ONLY the BCP-47 language code "
                                "(e.g., ja, en, id, zh, ko, th, vi). "
                                "No explanation, no extra text."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"What language is this text?\n\n{sample}",
                        },
                    ],
                    "temperature": 0.0,
                    "max_tokens": 10,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                "https://api.x.ai/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = _json.loads(resp.read().decode("utf-8"))
                code = result["choices"][0]["message"]["content"].strip().lower()
                try:
                    code = resolve_language_code(lang=code, explicit=code)
                except ValueError:
                    pass
                self._select_language_code(combo, code)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self,
                    _("Error"),
                    _("Detection failed: {e}").format(e=exc),
                )

        def _on_srt_path_changed(self) -> None:
            path = self.srt_edit.text().strip()
            if path:
                self._apply_filename_lang_guess(path, self.lang_combo)
            self._refresh_cue_count(self.srt_edit, self.cue_count_label)

        def _on_tr_srt_changed(self) -> None:
            path = self.tr_srt_edit.text().strip()
            if path:
                self._apply_filename_lang_guess(path, self.tr_source_combo)
            self._refresh_cue_count(self.tr_srt_edit, self.tr_cue_label)

        def _refresh_cue_count(self, edit: QLineEdit, label: QLabel) -> None:
            path_text = edit.text().strip()
            if not path_text:
                label.setText(_("Cues: —"))
                return
            path = Path(path_text)
            if not path.is_file():
                label.setText(_("Cues: file not found"))
                return
            try:
                text, _enc = read_srt_text(path)
                cues = parse_srt(text)
            except SrtEncodingError as exc:
                label.setText(
                    _("Cues: encoding error ({detail})").format(detail=str(exc))
                )
                return
            except SrtParseError as exc:
                label.setText(
                    _("Cues: parse error ({detail})").format(detail=str(exc))
                )
                return
            except OSError as exc:
                label.setText(
                    _("Cues: read error ({detail})").format(detail=exc)
                )
                return
            label.setText(_("Cues in SRT: {count}").format(count=len(cues)))

        # ----- job control -----
        def _job_running(self) -> bool:
            return self._thread is not None and self._thread.isRunning()

        def _cleanup_worker_thread(self) -> None:
            worker = self._worker
            thread = self._thread
            self._worker = None
            self._thread = None
            self._job_kind = None
            if worker is not None:
                worker.deleteLater()
            if thread is not None:
                thread.deleteLater()

        def _suggest_glossary(self) -> None:
            if self._job_running():
                return
            srt = Path(self.tr_srt_edit.text().strip())
            if not srt.is_file():
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("SRT file not found:\n{path}").format(path=srt),
                )
                return
            try:
                source_lang = normalize_language_code(
                    self._current_code(self.tr_source_combo)
                )
            except ValueError as exc:
                QMessageBox.critical(self, _("Error"), str(exc))
                return
            targets = self._selected_targets()
            if not targets:
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("Select at least one target language."),
                )
                return
            typed = self.key_edit.text().strip()
            self._session_key = typed or self._session_key
            api_key = resolve_api_key(prompt=False, session_key=self._session_key) or ""
            if not api_key:
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _(
                        "XAI_API_KEY is not set.\n"
                        "Set the environment variable or enter the key above."
                    ),
                )
                return
            out_text = self.tr_glossary_edit.text().strip()
            if not out_text:
                out_text = "glossary.json"
                self.tr_glossary_edit.setText(out_text)
            out_path = Path(out_text)
            limit = self.tr_limit_spin.value() or None
            merge_existing = out_path.is_file()
            if merge_existing:
                ret = QMessageBox.question(
                    self,
                    _("Merge glossary?"),
                    _(
                        "Glossary file already exists:\n{path}\n\n"
                        "Yes = merge (existing entries win)\n"
                        "No = overwrite with new suggestions"
                    ).format(path=out_path),
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if ret == QMessageBox.StandardButton.Cancel:
                    return
                if ret == QMessageBox.StandardButton.No:
                    merge_existing = False
            self.tabs.setCurrentWidget(self._translate_tab)
            self._begin_job(
                kind="glossary",
                worker=GlossaryWorker(
                    srt_path=srt,
                    source_lang=source_lang,
                    targets=targets,
                    out_path=out_path,
                    api_key=api_key,
                    merge_existing=merge_existing,
                    token=CancellationToken(),
                    limit=limit,
                    progress_q=self._progress_q,
                ),
            )

        def _start(self) -> None:
            self._save_current_settings()
            if self._job_running():
                return
            if self._thread is not None and not self._thread.isRunning():
                self._cleanup_worker_thread()
            if self.tabs.currentWidget() is self._translate_tab:
                self._start_translate()
            else:
                self._start_build()

        def _start_build(self) -> None:
            srt = Path(self.srt_edit.text().strip())
            if not srt.is_file():
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("SRT file not found:\n{path}").format(path=srt),
                )
                return
            language_code = self._current_code(self.lang_combo)
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
                strip_emoticons=self.strip_emoticons_cb.isChecked(),
                no_cache=self.no_cache_cb.isChecked(),
                base_wav=(
                    Path(self.base_wav_edit.text().strip())
                    if self.base_wav_edit.text().strip()
                    else None
                ),
                work_dir=Path("work"),
            )
            self._begin_job(
                kind="build",
                worker=BuildWorker(cfg, api_key, CancellationToken(), self._progress_q),
            )

        def _start_translate(self) -> None:
            srt = Path(self.tr_srt_edit.text().strip())
            if not srt.is_file():
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("SRT file not found:\n{path}").format(path=srt),
                )
                return
            try:
                source_lang = normalize_language_code(
                    self._current_code(self.tr_source_combo)
                )
            except ValueError as exc:
                QMessageBox.critical(self, _("Error"), str(exc))
                return
            targets = self._selected_targets()
            if not targets:
                QMessageBox.critical(
                    self,
                    _("Error"),
                    _("Select at least one target language."),
                )
                return
            dry = self.tr_dry_run_cb.isChecked()
            typed = self.key_edit.text().strip()
            self._session_key = typed or self._session_key
            api_key = resolve_api_key(prompt=False, session_key=self._session_key) or ""
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
            gloss = self.tr_glossary_edit.text().strip()
            limit = self.tr_limit_spin.value() or None
            try:
                cfg = TranslateConfig(
                    srt_path=srt,
                    source_lang=source_lang,
                    targets=targets,
                    out_dir=Path(self.tr_out_edit.text().strip() or "srt_gen"),
                    work_dir=Path("work"),
                    batch_size=int(self.tr_batch_spin.value()),
                    glossary_path=Path(gloss) if gloss else None,
                    length_mode=str(self.tr_length_combo.currentData() or "hint"),
                    limit=limit,
                    dry_run=dry,
                    fail_fast=self.tr_fail_fast_cb.isChecked(),
                    naming=str(self.tr_naming_combo.currentData() or "stem"),
                    no_cache=self.tr_no_cache_cb.isChecked(),
                )
                cfg.validate()
            except ValueError as exc:
                QMessageBox.critical(self, _("Error"), str(exc))
                return
            self._begin_job(
                kind="translate",
                worker=TranslateWorker(cfg, api_key, CancellationToken(), self._progress_q),
            )

        def _begin_job(self, *, kind: str, worker: QObject) -> None:
            self._token = worker.token  # type: ignore[attr-defined]
            self._pending_result = None
            self._job_kind = kind
            self._thread = QThread(self)
            self._worker = worker
            worker.moveToThread(self._thread)
            self._thread.started.connect(worker.run)  # type: ignore[attr-defined]
            worker.progress.connect(  # type: ignore[attr-defined]
                self._on_progress, Qt.ConnectionType.QueuedConnection
            )
            worker.finished.connect(  # type: ignore[attr-defined]
                self._on_worker_finished, Qt.ConnectionType.QueuedConnection
            )
            worker.failed.connect(  # type: ignore[attr-defined]
                self._on_worker_failed, Qt.ConnectionType.QueuedConnection
            )
            worker.finished.connect(self._thread.quit)  # type: ignore[attr-defined]
            worker.failed.connect(self._thread.quit)  # type: ignore[attr-defined]
            self._thread.finished.connect(self._on_thread_finished)
            self.start_btn.setEnabled(False)
            self.tabs.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.cancel_btn.setText(_("Cancel"))
            self.label.setText(_("Running…"))
            self.bar.setValue(0)
            self._latest_progress = None
            self._progress_seen = False
            # Drop stale events from a previous job.
            while True:
                try:
                    self._progress_q.get_nowait()
                except queue.Empty:
                    break
            self._progress_timer.start()
            _log_progress(f"begin_job kind={kind} thread_start")
            self._thread.start()

        def _cancel(self) -> None:
            self._token.cancel()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(_("Cancelling…"))

        @Slot(object)
        def _on_progress(self, ev: object) -> None:
            # Accept ProgressEvent or any duck-typed object with percent+stage.
            # Dual-import / Signal packing can break isinstance across modules.
            ok = isinstance(ev, ProgressEvent)
            if not ok:
                name_ok = type(ev).__name__ == "ProgressEvent"
                duck_ok = hasattr(ev, "percent") and hasattr(ev, "stage")
                ok = name_ok or duck_ok
            if not ok:
                _log_progress(
                    "on_progress DROP "
                    f"type={type(ev)!r} name={type(ev).__name__!r} "
                    f"mod={getattr(type(ev), '__module__', '?')!r}"
                )
                return
            # Prefer queue path (same as worker). Signal is backup if queue put failed.
            try:
                self._progress_q.put(ev)
            except Exception:  # noqa: BLE001
                self._latest_progress = ev  # type: ignore[assignment]
            _log_progress(
                "on_progress keep "
                f"pct={getattr(ev, 'percent', None)!r} "
                f"stage={getattr(ev, 'stage', None)!r} "
                f"msg={getattr(ev, 'message', None)!r} "
                f"seen={self._progress_seen}"
            )
            self._progress_seen = True
            self._flush_progress()

        @Slot()
        def _flush_progress(self) -> None:
            # Primary path: drain thread-safe queue (works even if Signal stalls).
            drained = 0
            while True:
                try:
                    self._latest_progress = self._progress_q.get_nowait()
                    drained += 1
                except queue.Empty:
                    break
            ev = self._latest_progress
            if ev is None:
                return
            if drained:
                self._progress_seen = True
            try:
                try:
                    pct = float(getattr(ev, "percent", 0.0) or 0.0)
                except (TypeError, ValueError):
                    pct = 0.0
                if pct != pct:  # NaN
                    pct = 0.0
                self.bar.setValue(max(0, min(1000, int(pct * 10))))
                text = format_gui_progress_label(ev)
                self.label.setText(text)
                _log_progress(
                    f"flush ok drained={drained} bar={self.bar.value()} label={text!r}"
                )
            except Exception as exc:  # noqa: BLE001
                # Keep latest so the next timer tick can retry; never kill the timer slot
                _log_crash(f"flush_progress: {exc!r}")
                _log_progress(f"flush FAIL {exc!r}")
                return
            self._latest_progress = None

        @Slot(object)
        def _on_worker_finished(self, report: object) -> None:
            self._pending_result = ("ok", report)

        @Slot(str)
        def _on_worker_failed(self, msg: str) -> None:
            self._pending_result = ("err", msg)

        def _format_build_summary(self, report: object) -> tuple[str, str, str]:
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

        def _format_translate_summary(self, report: object) -> tuple[str, str, str]:
            if not isinstance(report, dict):
                body = _("Translate finished.")
                return _("Done"), body, body
            status = str(report.get("status", "?"))
            summary = report.get("summary") or {}
            ok = summary.get("ok", 0)
            failed = summary.get("failed", 0)
            skipped = summary.get("skipped", 0)
            title = _("Translate result")
            label = _(
                "Translate: {status}  ok={ok} failed={failed} skipped={skipped}"
            ).format(status=status, ok=ok, failed=failed, skipped=skipped)
            lines = [
                _("Translate finished.\nStatus: {status}").format(status=status),
                "",
                _("Source: {lang}").format(lang=report.get("source_lang", "?")),
                _("Cues: {count}").format(count=report.get("cue_count", "?")),
                _("OK: {ok}  Failed: {failed}  Skipped: {skipped}").format(
                    ok=ok, failed=failed, skipped=skipped
                ),
                "",
            ]
            targets = report.get("targets") or {}
            if isinstance(targets, dict):
                for tgt, info in targets.items():
                    if not isinstance(info, dict):
                        continue
                    if info.get("ok"):
                        path = info.get("path") or _("(dry-run)")
                        lines.append(f"✓ {tgt}: {path}")
                        for w in info.get("warnings") or []:
                            lines.append(f"  ! {w}")
                    else:
                        errs = info.get("errors") or []
                        err_s = "; ".join(str(e) for e in errs) if errs else "?"
                        lines.append(f"✗ {tgt}: {err_s}")
            report_path = str(report.get("report_path") or "")
            if not report_path and report.get("out_dir"):
                report_path = str(Path(str(report["out_dir"])) / "translate_report.json")
            lines.append("")
            lines.append(_("Report:\n{path}").format(path=report_path or _("(unknown)")))
            return title, label, "\n".join(lines)

        def _format_glossary_summary(self, report: object) -> tuple[str, str, str]:
            if not isinstance(report, dict):
                body = _("Glossary finished.")
                return _("Done"), body, body
            path = report.get("path") or "?"
            n = report.get("terms", 0)
            tone = report.get("tone") or ""
            title = _("Glossary result")
            label = _("Glossary: {n} terms → {path}").format(n=n, path=path)
            body = _(
                "Glossary written.\n"
                "\n"
                "Terms: {n}\n"
                "Tone: {tone}\n"
                "\n"
                "Path:\n{path}\n"
                "\n"
                "Review and edit before translate."
            ).format(n=n, tone=tone or _("(none)"), path=path)
            return title, label, body

        def _show_pending_dialog(self, kind: str, payload: object) -> None:
            if kind == "ok":
                if self._last_result_kind == "glossary":
                    title, _label, body = self._format_glossary_summary(payload)
                elif self._last_result_kind == "translate":
                    title, _label, body = self._format_translate_summary(payload)
                else:
                    title, _label, body = self._format_build_summary(payload)
                QMessageBox.information(self, title, body)
                return
            msg = str(payload)
            if msg == "cancelled":
                QMessageBox.warning(
                    self,
                    _("Cancelled"),
                    _("Operation was cancelled."),
                )
            else:
                QMessageBox.critical(self, _("Error"), msg)

        @Slot()
        def _on_thread_finished(self) -> None:
            self._progress_timer.stop()
            self._flush_progress()
            pending = self._pending_result
            self._pending_result = None
            result_kind = self._job_kind or "build"
            self._last_result_kind = result_kind
            self._cleanup_worker_thread()
            self.start_btn.setEnabled(True)
            self.tabs.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(_("Cancel"))
            self._on_tab_changed(self.tabs.currentIndex())
            if pending is None:
                self.label.setText(_("Ready"))
                return
            kind, payload = pending
            if kind == "ok":
                if result_kind == "glossary":
                    _t, label, _b = self._format_glossary_summary(payload)
                    # keep path in glossary field
                    if isinstance(payload, dict) and payload.get("path"):
                        self.tr_glossary_edit.setText(str(payload["path"]))
                elif result_kind == "translate":
                    _t, label, _b = self._format_translate_summary(payload)
                else:
                    _t, label, _b = self._format_build_summary(payload)
                self.bar.setValue(1000)
                self.label.setText(label)
                QTimer.singleShot(
                    0, lambda k=kind, p=payload: self._show_pending_dialog(k, p)
                )
                return
            msg = str(payload)
            if msg == "cancelled":
                self.label.setText(_("Cancelled"))
            else:
                self.label.setText(msg)
            QTimer.singleShot(
                0, lambda k=kind, p=payload: self._show_pending_dialog(k, p)
            )

        def closeEvent(self, event) -> None:  # noqa: N802
            self._save_current_settings()
            self._progress_timer.stop()
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
    win.resize(640, 720)
    win.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
