"""Small SRT editor with per-cue xAI delivery controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from srtspeak.core.speech_profiles import (
    MAX_TTS_SPEED,
    MIN_TTS_SPEED,
    CueSpeechProfile,
    save_speech_profiles,
)
from srtspeak.core.srt_parser import (
    Cue,
    SrtParseError,
    format_srt,
    format_timestamp_ms,
    parse_srt,
    parse_timestamp_ms,
)

STYLE_OPTIONS = (
    ("通常", ""),
    ("柔らかく <soft>", "soft"),
    ("ささやく <whisper>", "whisper"),
    ("大きく <loud>", "loud"),
    ("強さを増す <build-intensity>", "build-intensity"),
    ("強さを抑える <decrease-intensity>", "decrease-intensity"),
    ("高い声 <higher-pitch>", "higher-pitch"),
    ("低い声 <lower-pitch>", "lower-pitch"),
    ("ゆっくり <slow>", "slow"),
    ("速く <fast>", "fast"),
    ("歌うように <sing-song>", "sing-song"),
    ("歌う <singing>", "singing"),
    ("強調 <emphasis>", "emphasis"),
)


class SrtEditorDialog(QDialog):
    """Edit subtitle text/timing and separate TTS-only speech directions."""

    def __init__(
        self,
        srt_path: Path,
        cues: list[Cue],
        profiles: dict[int, CueSpeechProfile],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.srt_path = Path(srt_path)
        self.saved_path: Path | None = None
        self._rows: list[dict[str, object]] = [
            {
                "start": format_timestamp_ms(cue.start_ms),
                "end": format_timestamp_ms(cue.end_ms),
                "text": cue.text,
                "tts_text": profiles.get(cue.index, CueSpeechProfile()).tts_text or "",
                "style": profiles.get(cue.index, CueSpeechProfile()).style or "",
                "speed": profiles.get(cue.index, CueSpeechProfile()).speed,
            }
            for cue in cues
        ]
        self._active_row: int | None = None
        self.setWindowTitle("SRT編集・Grok音声表現")
        self.setMinimumSize(820, 600)

        root = QVBoxLayout(self)
        help_label = QLabel(
            "字幕本文と時間を編集できます。Grok向けの音声指示は字幕に表示されず、"
            "同名の .srtspeak.json に保存されます。\n"
            "TTS本文には [pause] / [laugh]、スタイルには soft・whisper・"
            "higher-pitch・lower-pitch などを指定できます。"
        )
        help_label.setWordWrap(True)
        root.addWidget(help_label)

        body = QHBoxLayout()
        self.cue_list = QListWidget()
        self.cue_list.setMinimumWidth(250)
        self.cue_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.cue_list.setToolTip("Ctrl / Shift を使って複数の字幕を選択できます。")
        self.cue_list.currentRowChanged.connect(self._select_row)
        body.addWidget(self.cue_list)

        form = QFormLayout()
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("HH:MM:SS,mmm")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("HH:MM:SS,mmm")
        form.addRow("開始時刻", self.start_edit)
        form.addRow("終了時刻", self.end_edit)

        self.caption_edit = QPlainTextEdit()
        self.caption_edit.setPlaceholderText("字幕として表示する本文")
        self.caption_edit.setMinimumHeight(110)
        form.addRow("字幕本文", self.caption_edit)

        self.tts_text_edit = QPlainTextEdit()
        self.tts_text_edit.setPlaceholderText(
            "空欄なら字幕本文を使用。例: <whisper>内緒だよ。</whisper> [pause]"
        )
        self.tts_text_edit.setMinimumHeight(100)
        form.addRow("TTS本文（任意）", self.tts_text_edit)

        self.style_combo = QComboBox()
        for label, tag in STYLE_OPTIONS:
            self.style_combo.addItem(label, tag)
        form.addRow("抑揚・スタイル", self.style_combo)

        speed_row = QHBoxLayout()
        self.speed_override = QCheckBox("この字幕だけ話速を上書き")
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(MIN_TTS_SPEED, MAX_TTS_SPEED)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSuffix("×")
        self.speed_spin.setEnabled(False)
        self.speed_override.toggled.connect(self.speed_spin.setEnabled)
        speed_row.addWidget(self.speed_override)
        speed_row.addWidget(self.speed_spin)
        speed_row.addStretch(1)
        speed_widget = QWidget()
        speed_widget.setLayout(speed_row)
        form.addRow("話速", speed_widget)

        body.addLayout(form, 1)
        root.addLayout(body, 1)

        bulk_row = QHBoxLayout()
        bulk_row.addWidget(QLabel("選択字幕に一括設定"))
        self.bulk_style_combo = QComboBox()
        for label, tag in STYLE_OPTIONS:
            self.bulk_style_combo.addItem(label, tag)
        self.bulk_style_btn = QPushButton("選択字幕へ適用")
        self.bulk_style_btn.clicked.connect(self._apply_bulk_style)
        bulk_row.addWidget(self.bulk_style_combo, 1)
        bulk_row.addWidget(self.bulk_style_btn)
        root.addLayout(bulk_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        add_btn = QPushButton("字幕を追加")
        add_btn.clicked.connect(self._add_cue)
        self.delete_btn = QPushButton("選択字幕を削除")
        self.delete_btn.clicked.connect(self._delete_cue)
        save_btn = QPushButton("別名でSRT保存")
        save_btn.clicked.connect(self._save_as)
        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(add_btn)
        actions.addWidget(self.delete_btn)
        actions.addStretch(1)
        overwrite_btn = QPushButton("上書き保存")
        overwrite_btn.clicked.connect(self._overwrite)
        actions.addWidget(overwrite_btn)
        actions.addWidget(save_btn)
        actions.addWidget(close_btn)
        root.addLayout(actions)

        self._refresh_cue_list()
        if self._rows:
            self.cue_list.setCurrentRow(0)
        else:
            self._set_fields_enabled(False)

    def _set_fields_enabled(self, enabled: bool) -> None:
        for widget in (
            self.start_edit,
            self.end_edit,
            self.caption_edit,
            self.tts_text_edit,
            self.style_combo,
            self.speed_override,
            self.delete_btn,
        ):
            widget.setEnabled(enabled)
        self.speed_spin.setEnabled(enabled and self.speed_override.isChecked())

    def _store_current(self) -> None:
        row = self._active_row
        if row is None or not 0 <= row < len(self._rows):
            return
        self._rows[row] = {
            "start": self.start_edit.text().strip(),
            "end": self.end_edit.text().strip(),
            "text": self.caption_edit.toPlainText().strip(),
            "tts_text": self.tts_text_edit.toPlainText().strip(),
            "style": str(self.style_combo.currentData() or ""),
            "speed": self.speed_spin.value() if self.speed_override.isChecked() else None,
        }
        self._update_list_item(row)

    def _select_row(self, row: int) -> None:
        if self._active_row is not None:
            self._store_current()
        if row < 0 or row >= len(self._rows):
            self._active_row = None
            self._set_fields_enabled(False)
            return
        self._active_row = row
        data = self._rows[row]
        self.start_edit.setText(str(data["start"]))
        self.end_edit.setText(str(data["end"]))
        self.caption_edit.setPlainText(str(data["text"]))
        self.tts_text_edit.setPlainText(str(data["tts_text"]))
        style_index = self.style_combo.findData(str(data["style"]))
        self.style_combo.setCurrentIndex(max(0, style_index))
        speed = data["speed"]
        self.speed_override.setChecked(speed is not None)
        self.speed_spin.setValue(float(speed) if speed is not None else 1.0)
        self._set_fields_enabled(True)
        self.status_label.setText(f"字幕 {row + 1} / {len(self._rows)}")

    def _refresh_cue_list(self) -> None:
        current = self.cue_list.currentRow()
        self.cue_list.blockSignals(True)
        self.cue_list.clear()
        for row in range(len(self._rows)):
            from PySide6.QtWidgets import QListWidgetItem

            self.cue_list.addItem(QListWidgetItem(""))
            self._update_list_item(row)
        self.cue_list.blockSignals(False)
        if self._rows:
            self.cue_list.setCurrentRow(min(max(current, 0), len(self._rows) - 1))
        else:
            self._active_row = None
            self._set_fields_enabled(False)

    def _update_list_item(self, row: int) -> None:
        if not 0 <= row < self.cue_list.count() or row >= len(self._rows):
            return
        data = self._rows[row]
        preview = " ".join(str(data["text"]).split())
        if len(preview) > 42:
            preview = preview[:39] + "..."
        self.cue_list.item(row).setText(
            f"{row + 1:04d}  {data['start']}  {preview or '(本文なし)'}"
        )

    def _apply_bulk_style(self) -> None:
        selected_rows = sorted(
            self.cue_list.row(item) for item in self.cue_list.selectedItems()
        )
        if not selected_rows:
            self.status_label.setText("スタイルを適用する字幕を選択してください。")
            return
        self._store_current()
        style = str(self.bulk_style_combo.currentData() or "")
        for row in selected_rows:
            self._rows[row]["style"] = style
            self._update_list_item(row)
        if self._active_row in selected_rows:
            style_index = self.style_combo.findData(style)
            self.style_combo.setCurrentIndex(max(style_index, 0))
        self.status_label.setText(f"{len(selected_rows)} 件の字幕にスタイルを適用しました。")

    def _add_cue(self) -> None:
        self._store_current()
        start_ms = 0
        if self._rows:
            try:
                start_ms = parse_timestamp_ms(str(self._rows[-1]["end"]))
            except ValueError:
                start_ms = 0
        self._rows.append(
            {
                "start": format_timestamp_ms(start_ms),
                "end": format_timestamp_ms(start_ms + 2_000),
                "text": "",
                "tts_text": "",
                "style": "",
                "speed": None,
            }
        )
        self._active_row = None
        self._refresh_cue_list()
        self.cue_list.setCurrentRow(len(self._rows) - 1)
        self.caption_edit.setFocus()

    def _delete_cue(self) -> None:
        row = self.cue_list.currentRow()
        if row < 0:
            return
        self._store_current()
        del self._rows[row]
        self._active_row = None
        self._refresh_cue_list()
        if self._rows:
            self.cue_list.setCurrentRow(min(row, len(self._rows) - 1))

    def _collect(self) -> tuple[list[Cue], dict[int, CueSpeechProfile]]:
        self._store_current()
        if not self._rows:
            raise ValueError("SRTに最低1件の字幕が必要です。")
        cues: list[Cue] = []
        profiles: dict[int, CueSpeechProfile] = {}
        previous_end = -1
        for index, data in enumerate(self._rows, 1):
            start_ms = parse_timestamp_ms(str(data["start"]))
            end_ms = parse_timestamp_ms(str(data["end"]))
            text = str(data["text"]).strip()
            if end_ms <= start_ms:
                raise ValueError(f"字幕 {index}: 終了時刻は開始時刻より後にしてください。")
            if start_ms < previous_end:
                raise ValueError(f"字幕 {index}: 前の字幕と時間が重なっています。")
            if not text:
                raise ValueError(f"字幕 {index}: 本文が空です。")
            cue = Cue(index=index, start_ms=start_ms, end_ms=end_ms, text=text)
            cues.append(cue)
            previous_end = end_ms

            profile = CueSpeechProfile(
                tts_text=str(data["tts_text"]).strip() or None,
                style=str(data["style"]) or None,
                speed=float(data["speed"]) if data["speed"] is not None else None,
            )
            profile.validate()
            if not profile.is_empty:
                profiles[index] = profile

        # Run the same syntax/text validation as normal builds without shifting edited timings.
        parse_srt(format_srt(cues), fix_overlap=False)
        return cues, profiles

    def _write_output(
        self,
        target: Path,
        cues: list[Cue],
        profiles: dict[int, CueSpeechProfile],
    ) -> bool:
        serialized = format_srt(cues)
        tmp = target.with_name(target.name + ".tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(serialized, encoding="utf-8", newline="\n")
            tmp.replace(target)
            save_speech_profiles(target, profiles)
        except (OSError, ValueError) as exc:
            tmp.unlink(missing_ok=True)
            QMessageBox.critical(self, "SRT保存エラー", str(exc))
            return False
        self.saved_path = target
        self.accept()
        return True

    def _overwrite(self) -> None:
        try:
            cues, profiles = self._collect()
        except (ValueError, SrtParseError) as exc:
            QMessageBox.warning(self, "SRTを保存できません", str(exc))
            return
        if not self.srt_path.is_file():
            QMessageBox.warning(
                self,
                "上書き保存できません",
                "元のSRTが見つかりません。『別名でSRT保存』を使ってください。",
            )
            return
        answer = QMessageBox.question(
            self,
            "SRTを上書き保存",
            f"元のSRTと音声設定を上書きします。\n{self.srt_path}\n\n続行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._write_output(self.srt_path, cues, profiles)

    def _save_as(self) -> None:
        try:
            cues, profiles = self._collect()
        except (ValueError, SrtParseError) as exc:
            QMessageBox.warning(self, "SRTを保存できません", str(exc))
            return

        default_path = self.srt_path.with_name(f"{self.srt_path.stem}_edited.srt")
        output, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "編集したSRTを保存",
            str(default_path),
            "SRT files (*.srt)",
        )
        if not output:
            return
        target = Path(output).expanduser().resolve()
        if target.suffix.lower() != ".srt":
            target = target.with_suffix(".srt")
        self._write_output(target, cues, profiles)
