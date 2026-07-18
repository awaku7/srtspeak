"""i18n (Babel/gettext) tests — English msgids, ja/en locales."""

from __future__ import annotations

from pathlib import Path

import pytest

from srtspeak.i18n import _, available_locales, get_locale, set_locale
from srtspeak.core.srt_parser import SrtParseError, parse_srt, parse_timestamp_ms, apply_limit


LOCALES_DIR = Path(__file__).resolve().parents[1] / "src" / "srtspeak" / "locales"


@pytest.fixture(autouse=True)
def _restore_locale():
    prev = get_locale()
    yield
    set_locale(prev)


def test_locales_dir_layout() -> None:
    assert (LOCALES_DIR / "srtspeak.pot").is_file()
    assert (LOCALES_DIR / "ja" / "LC_MESSAGES" / "srtspeak.po").is_file()
    assert (LOCALES_DIR / "ja" / "LC_MESSAGES" / "srtspeak.mo").is_file()
    assert (LOCALES_DIR / "en" / "LC_MESSAGES" / "srtspeak.po").is_file()


def test_available_locales_includes_en_ja() -> None:
    locs = available_locales()
    assert "en" in locs
    assert "ja" in locs


def test_set_locale_en_passthrough() -> None:
    set_locale("en")
    assert get_locale() == "en"
    assert _("{label}: text is empty") == "{label}: text is empty"
    assert _("SRT parse error: {detail}").format(detail="x") == "SRT parse error: x"


def test_set_locale_ja_translates() -> None:
    set_locale("ja")
    assert get_locale() == "ja"
    assert _("{label}: text is empty") == "{label}: テキストが空です"
    assert "SRT解析エラー" in _("SRT parse error: {detail}").format(detail="x")


def test_parse_error_english() -> None:
    set_locale("en")
    with pytest.raises(SrtParseError) as ei:
        parse_srt("1\n00:00:00,000 --> 00:00:01,000\n\n")
    msg = str(ei.value)
    assert "empty" in msg.lower() or "text is empty" in msg
    assert "cue 1" in msg.lower() or "Cue 1" in msg or "cue 1" in msg
    assert "SRT parse error" in msg


def test_parse_error_japanese() -> None:
    set_locale("ja")
    with pytest.raises(SrtParseError) as ei:
        parse_srt("1\n00:00:00,000 --> 00:00:01,000\n\n")
    msg = str(ei.value)
    assert "空" in msg
    assert "SRT解析エラー" in msg


def test_timestamp_error_en_and_ja() -> None:
    set_locale("en")
    with pytest.raises(SrtParseError) as ei:
        parse_timestamp_ms("bad")
    assert "invalid timestamp" in str(ei.value).lower()
    assert "bad" in str(ei.value)

    set_locale("ja")
    with pytest.raises(SrtParseError) as ei:
        parse_timestamp_ms("bad")
    assert "タイムスタンプ" in str(ei.value)


def test_overlap_en() -> None:
    set_locale("en")
    text = (
        "1\n00:00:00,000 --> 00:00:02,000\na\n\n"
        "2\n00:00:01,000 --> 00:00:03,000\nb\n"
    )
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value).lower()
    assert "overlap" in msg


def test_multiple_issues_header_en() -> None:
    set_locale("en")
    text = (
        "1\n00:00:02,000 --> 00:00:01,000\nhello\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n\n\n"
        "3\n00:00:03,500 --> 00:00:05,000\nworld\n"
    )
    with pytest.raises(SrtParseError) as ei:
        parse_srt(text)
    msg = str(ei.value)
    assert "following problems" in msg.lower()
    assert len(ei.value.issues) >= 2


def test_apply_limit_message_en_ja() -> None:
    set_locale("en")
    with pytest.raises(ValueError) as ei:
        apply_limit([], 0)
    assert "limit" in str(ei.value).lower()

    set_locale("ja")
    with pytest.raises(ValueError) as ei:
        apply_limit([], 0)
    assert "limit" in str(ei.value).lower() or "1" in str(ei.value)


def test_detect_locale_env_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from srtspeak.i18n import _detect_locale

    monkeypatch.setenv("SRTSPEAK_LOCALE", "ja")
    assert _detect_locale() == "ja"

    monkeypatch.setenv("SRTSPEAK_LOCALE", "en_US")
    assert _detect_locale() == "en"

    monkeypatch.delenv("SRTSPEAK_LOCALE", raising=False)
    monkeypatch.setenv("LC_ALL", "ja_JP.UTF-8")
    monkeypatch.delenv("LANG", raising=False)
    assert _detect_locale() == "ja"

    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr("srtspeak.i18n._locale_mod.getlocale", lambda: (None, None))
    monkeypatch.setattr(
        "srtspeak.i18n._locale_mod.getdefaultlocale",
        lambda: (None, None),
        raising=False,
    )
    assert _detect_locale() == "en"


def test_setup_i18n_none_follows_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from srtspeak.i18n import setup_i18n

    monkeypatch.setenv("SRTSPEAK_LOCALE", "ja")
    assert setup_i18n(None) == "ja"
    assert _("{label}: text is empty") == "{label}: テキストが空です"

    monkeypatch.setenv("SRTSPEAK_LOCALE", "en")
    assert setup_i18n(None) == "en"
    assert _("{label}: text is empty") == "{label}: text is empty"


def test_msgid_keys_are_english_in_pot() -> None:
    pot = (LOCALES_DIR / "srtspeak.pot").read_text(encoding="utf-8")
    assert 'msgid "invalid timestamp:' in pot or 'msgid "invalid timestamp' in pot
    assert "タイムスタンプ" not in pot.split("msgid")[1] if "msgid" in pot else True
    # pot source language messages must be English
    assert 'msgid "{label}: text is empty"' in pot
    assert 'msgid "no cues found in SRT' in pot
    assert 'msgid "Language"' in pot
    assert 'msgid "Start"' in pot
    assert 'msgid "Authoritative and strong"' in pot

def test_dry_run_result_messages_en_ja() -> None:
    """GUI dry-run summary strings must translate under ja locale."""
    dry_title = "Dry-run result"
    dry_label = "Dry-run: {cues} cues, {chars} chars, ~${cost} USD"
    dry_body = (
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
    )

    set_locale("en")
    assert _(dry_title) == dry_title
    assert _(dry_label) == dry_label
    assert _(dry_body) == dry_body
    assert _("on") == "on"
    assert _("off") == "off"

    set_locale("ja")
    assert _(dry_title) == "ドライラン結果"
    assert "ドライラン" in _(dry_label)
    assert "キュー" in _(dry_label)
    body = _(dry_body)
    assert "ドライラン完了" in body
    assert "言語:" in body
    assert "推定コスト" in body
    assert "日本語読み" in body
    assert _("on") == "オン"
    assert _("off") == "オフ"
    assert _("(unknown)") == "（不明）"
    assert "トラック長" in _("Track duration: {ms:.0f} ms")

