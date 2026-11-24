from __future__ import annotations

import os
from pathlib import Path

import pytest

from srtspeak.core.speech_profiles import CueSpeechProfile
from srtspeak.core.srt_parser import Cue


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_editor_collects_caption_and_separate_grok_directions(
    qapp, tmp_path: Path
) -> None:
    from srtspeak.gui.srt_editor import SrtEditorDialog

    dialog = SrtEditorDialog(
        tmp_path / "source.srt",
        [Cue(index=1, start_ms=0, end_ms=1500, text="Hello")],
        {},
    )
    dialog.tts_text_edit.setPlainText("Hello [pause]")
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData("whisper"))
    dialog.speed_override.setChecked(True)
    dialog.speed_spin.setValue(0.85)

    cues, profiles = dialog._collect()

    assert cues == [Cue(index=1, start_ms=0, end_ms=1500, text="Hello")]
    assert profiles == {
        1: CueSpeechProfile(tts_text="Hello [pause]", style="whisper", speed=0.85)
    }
    dialog.close()


def test_editor_rejects_overlapping_or_empty_cues(qapp, tmp_path: Path) -> None:
    from srtspeak.gui.srt_editor import SrtEditorDialog

    dialog = SrtEditorDialog(
        tmp_path / "source.srt",
        [
            Cue(index=1, start_ms=0, end_ms=1000, text="First"),
            Cue(index=2, start_ms=1000, end_ms=2000, text="Second"),
        ],
        {},
    )
    dialog.cue_list.setCurrentRow(1)
    dialog.start_edit.setText("00:00:00,900")
    with pytest.raises(ValueError, match="重なっています"):
        dialog._collect()

    dialog.start_edit.setText("00:00:01,000")
    dialog.caption_edit.setPlainText(" ")
    with pytest.raises(ValueError, match="本文が空"):
        dialog._collect()
    dialog.close()


def test_editor_applies_style_to_multiple_selected_cues(qapp, tmp_path: Path) -> None:
    from srtspeak.gui.srt_editor import SrtEditorDialog

    dialog = SrtEditorDialog(
        tmp_path / "source.srt",
        [
            Cue(index=1, start_ms=0, end_ms=1000, text="First"),
            Cue(index=2, start_ms=1000, end_ms=2000, text="Second"),
            Cue(index=3, start_ms=2000, end_ms=3000, text="Third"),
        ],
        {},
    )
    dialog.cue_list.item(1).setSelected(True)
    dialog.cue_list.item(2).setSelected(True)
    dialog.bulk_style_combo.setCurrentIndex(
        dialog.bulk_style_combo.findData("whisper")
    )

    dialog._apply_bulk_style()
    _cues, profiles = dialog._collect()

    assert {index: profile.style for index, profile in profiles.items()} == {
        1: "whisper",
        2: "whisper",
        3: "whisper",
    }
    dialog.close()


def test_editor_overwrite_saves_srt_and_sidecar(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from srtspeak.core.speech_profiles import load_speech_profiles
    from srtspeak.core.srt_parser import parse_srt
    from srtspeak.gui.srt_editor import SrtEditorDialog

    source = tmp_path / "source.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOriginal\n", encoding="utf-8"
    )
    dialog = SrtEditorDialog(
        source,
        parse_srt(source.read_text(encoding="utf-8")),
        {},
    )
    dialog.caption_edit.setPlainText("Updated caption")
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData("soft"))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    dialog._overwrite()

    saved_cues = parse_srt(source.read_text(encoding="utf-8"))
    assert saved_cues[0].text == "Updated caption"
    assert load_speech_profiles(source)[1].style == "soft"
    assert dialog.saved_path == source
    dialog.close()
