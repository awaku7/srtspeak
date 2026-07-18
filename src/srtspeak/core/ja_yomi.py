from __future__ import annotations

"""Japanese kanji to hiragana preprocessing for TTS (kanjiconv)."""

from dataclasses import replace
from functools import lru_cache
from typing import Sequence

from srtspeak.core.srt_parser import Cue


class JaYomiError(ValueError):
    """Raised when ja_yomi is required but kanjiconv is unavailable."""


_INSTALL_HINT = (
    "kanjiconv is required for ja_yomi; install with: pip install kanjiconv "
    '(or pip install -e ".[ja]")'
)


@lru_cache(maxsize=1)
def _get_converter() -> object:
    try:
        from kanjiconv import KanjiConv
    except ImportError as exc:  # pragma: no cover
        raise JaYomiError(_INSTALL_HINT) from exc
    # separator="" keeps a natural reading string for TTS (no token delimiters)
    return KanjiConv(separator="", use_custom_readings=True)


def kanjiconv_available() -> bool:
    """Return True if kanjiconv can be imported and constructed."""
    try:
        _get_converter()
        return True
    except JaYomiError:
        return False


def to_hiragana(text: str) -> str:
    """Convert kanji readings to hiragana via kanjiconv.

    Empty input is returned unchanged. Raises JaYomiError if kanjiconv is missing.
    """
    if text == "":
        return text
    conv = _get_converter()
    result = conv.to_hiragana(text)  # type: ignore[attr-defined]
    if not isinstance(result, str):
        raise JaYomiError("kanjiconv.to_hiragana returned non-str")
    return result


def should_apply_ja_yomi(*, enabled: bool, lang: str) -> bool:
    """True only when the flag is on and the internal lang key is ja."""
    return bool(enabled) and lang == "ja"


def apply_ja_yomi(
    cues: Sequence[Cue],
    *,
    enabled: bool,
    lang: str,
) -> list[Cue]:
    """Return cues with text converted to hiragana when applicable.

    Non-ja languages or disabled flag: return a shallow list copy unchanged.
    When applicable, missing kanjiconv raises JaYomiError (exit 2 via CLI).
    """
    if not should_apply_ja_yomi(enabled=enabled, lang=lang):
        return list(cues)
    _get_converter()
    out: list[Cue] = []
    for cue in cues:
        yomi = to_hiragana(cue.text)
        if yomi == cue.text:
            out.append(cue)
        else:
            out.append(replace(cue, text=yomi))
    return out