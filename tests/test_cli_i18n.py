"""CLI i18n smoke tests."""

from __future__ import annotations

import io
import sys

import pytest

from srtspeak.cli import main
from srtspeak.i18n import _, get_locale, set_locale


@pytest.fixture(autouse=True)
def _restore_locale():
    prev = get_locale()
    yield
    set_locale(prev)


def test_cli_help_ja_translates_options() -> None:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        with pytest.raises(SystemExit) as ei:
            main(["--locale", "ja", "build", "--help"])
        assert ei.value.code == 0
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "入力 SRT パス" in out
    assert "1言語をビルド" in out or "build" in out


def test_cli_srt_not_found_ja() -> None:
    err = io.StringIO()
    old_err = sys.stderr
    sys.stderr = err
    try:
        code = main(["--locale", "ja", "build", "--srt", "no_such_file.srt"])
    finally:
        sys.stderr = old_err
    assert code == 2
    assert "SRT が見つかりません" in err.getvalue()


def test_cli_languages_ja_labels() -> None:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = main(["--locale", "ja", "languages"])
    finally:
        sys.stdout = old
    assert code == 0
    out = buf.getvalue()
    assert "日本語" in out
    assert "英語" in out


def test_cli_help_en_keeps_english() -> None:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        with pytest.raises(SystemExit) as ei:
            main(["--locale", "en", "build", "--help"])
        assert ei.value.code == 0
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "input SRT path" in out
