"""Sanitize subtitle text for TTS without mutating stored SRT cues.

Policy: keep emoji; strip kaomoji / chat-face marks only (regex, conservative).
"""

from __future__ import annotations

import re

# Kaomoji only — must NOT match normal parentheticals like （税込） or (see note).
# Face-like: eyes/mouth symbols inside short parens.
_KAOMOJI_RE = re.compile(
    r"(?:"
    r"m\([ \t]?_[ \t]?_[ \t]?\)m"  # m(_ _)m
    r"|\([^()\n]{0,4}[;；^￣¯>＞<＜TTt×xX+＋*＊★☆@＠][^()\n]{0,6}"
    r"[_＿\-ー−~～^￣¯.．・∀∇□○●ωω▽△▲][^()\n]{0,6}"
    r"[;；^￣¯>＞<＜TTt×xX+＋*＊★☆@＠]?[^()\n]{0,4}\)"  # (^_^) (T_T) (;_;)
    r"|（[^（）\n]{0,4}[;；´`^￣¯>＞<＜★☆・･ﾟ][^（）\n]{0,8}"
    r"[_＿\-ー−~～^￣¯.．・∀∇□○●ωω▽△▲][^（）\n]{0,8}"
    r"[;；´`^￣¯>＞<＜★☆・･ﾟ]?[^（）\n]{0,4}）"  # （´∀｀）（・∀・）
    r"|(?<![A-Za-z])orz(?![A-Za-z])"
    r"|(?<![A-Za-z])OTL(?![A-Za-z])"
    r")"
)

_WS_RE = re.compile(r"[ \t\u3000]{2,}")


def sanitize_for_tts(text: str, *, collapse_ws: bool = True) -> str:
    """Remove light kaomoji for speakable TTS text. Emoji is kept as-is."""
    if not text:
        return ""
    out = _KAOMOJI_RE.sub("", text)
    if collapse_ws:
        out = _WS_RE.sub(" ", out)
        out = re.sub(r" +([,.;:!?、。！？])", r"\1", out)
        out = out.strip()
    return out


def strip_emoticons_enabled_text(text: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return sanitize_for_tts(text)


def tts_speak_text(text: str, *, enabled: bool) -> str:
    """Text actually sent to TTS / used in TTS cache key.

    If stripping yields empty, fall back to original so the cue still speaks.
    SRT cue text must remain unchanged by the caller.
    """
    if not enabled:
        return text
    cleaned = sanitize_for_tts(text)
    if cleaned.strip():
        return cleaned
    return text
