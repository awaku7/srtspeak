"""Progress display i18n — localize stage/message at CLI/GUI boundary only."""

from __future__ import annotations

import pytest

from srtspeak.i18n import get_locale, set_locale
from srtspeak.progress_i18n import localize_message, localize_stage


@pytest.fixture(autouse=True)
def _restore_locale():
    prev = get_locale()
    yield
    set_locale(prev)


def test_localize_stage_en_passthrough() -> None:
    set_locale("en")
    assert localize_stage("tts") == "tts"
    assert localize_stage("translate") == "translate"
    assert localize_stage("glossary") == "glossary"
    assert localize_stage("ja_yomi") == "ja_yomi"
    assert localize_stage("unknown_stage_xyz") == "unknown_stage_xyz"


def test_localize_stage_ja() -> None:
    set_locale("ja")
    assert localize_stage("parse") == "解析"
    assert localize_stage("tts") == "TTS"
    assert localize_stage("fit") == "フィット"
    assert localize_stage("timeline") == "タイムライン"
    assert localize_stage("report") == "レポート"
    assert localize_stage("translate") == "翻訳"
    assert localize_stage("translate_compress") == "翻訳圧縮"
    assert localize_stage("translate_write") == "翻訳書き込み"
    assert localize_stage("glossary") == "用語集"
    assert localize_stage("ja_yomi") == "ひらがな化"
    # unknown stays as-is
    assert localize_stage("unknown_stage_xyz") == "unknown_stage_xyz"


def test_localize_message_exact_en() -> None:
    set_locale("en")
    assert localize_message("parse srt") == "parse srt"
    assert localize_message("done") == "done"
    assert localize_message("extract candidates") == "extract candidates"
    assert localize_message("finalize glossary") == "finalize glossary"


def test_localize_message_exact_ja() -> None:
    set_locale("ja")
    assert localize_message("parse srt") == "SRT解析"
    assert localize_message("parsed") == "解析完了"
    assert localize_message("dry_run done") == "ドライラン完了"
    assert localize_message("tts done") == "TTS完了"
    assert localize_message("tts api") == "TTS API"
    assert localize_message("fit done") == "フィット完了"
    assert localize_message("timeline done") == "タイムライン完了"
    assert localize_message("report done") == "レポート完了"
    assert localize_message("start") == "開始"
    assert localize_message("done") == "完了"
    assert localize_message("extract candidates") == "候補抽出"
    assert localize_message("chat suggest") == "Chat提案"
    assert localize_message("finalize glossary") == "用語集確定"


def test_localize_message_patterns_en() -> None:
    set_locale("en")
    assert localize_message("cache hit 3/10") == "cache hit 3/10"
    assert localize_message("en batch 2/5") == "en batch 2/5"
    assert localize_message("en batch 2/5 done") == "en batch 2/5 done"
    assert localize_message("pt-BR compress index 7") == "pt-BR compress index 7"
    assert localize_message("waiting chat... 12s") == "waiting chat... 12s"
    assert localize_message("candidates=42") == "candidates=42"
    assert localize_message("write foo_en.srt") == "write foo_en.srt"
    assert localize_message("en finished") == "en finished"
    assert localize_message("en dry-run") == "en dry-run"
    assert localize_message("hiragana batch 1/3") == "hiragana batch 1/3"


def test_localize_message_patterns_ja() -> None:
    set_locale("ja")
    assert localize_message("cache hit 3/10") == "キャッシュヒット 3/10"
    assert localize_message("en batch 2/5") == "en バッチ 2/5"
    assert localize_message("en batch 2/5 done") == "en バッチ 2/5 完了"
    assert localize_message("pt-BR compress index 7") == "pt-BR 圧縮 index 7"
    assert localize_message("waiting chat... 12s") == "Chat待機中… 12s"
    assert localize_message("candidates=42") == "候補数=42"
    assert localize_message("write foo_en.srt") == "書き込み foo_en.srt"
    assert localize_message("en finished") == "en 完了"
    assert localize_message("en dry-run") == "en ドライラン"
    assert localize_message("hiragana batch 1/3") == "ひらがな バッチ 1/3"


def test_localize_message_unknown_passthrough() -> None:
    set_locale("ja")
    assert localize_message("totally unknown msg 99") == "totally unknown msg 99"
    assert localize_message("") == ""


def test_localize_message_batch_waiting() -> None:
    set_locale("en")
    assert (
        localize_message("en batch 2/5 waiting chat... 12s")
        == "en batch 2/5 waiting chat... 12s"
    )
    set_locale("ja")
    assert (
        localize_message("en batch 2/5 waiting chat... 12s")
        == "en バッチ 2/5 Chat待機中… 12s"
    )
    assert (
        localize_message("pt-BR batch 1/3 waiting chat... 3s")
        == "pt-BR バッチ 1/3 Chat待機中… 3s"
    )
