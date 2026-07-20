"""Localize ProgressEvent stage/message at CLI/GUI display boundary.

Core keeps English stage ids and English messages (tests assert them).
Presentation layers call these helpers before showing progress to users.
"""

from __future__ import annotations

import re

from srtspeak.i18n import _


def format_gui_progress_label(ev: object) -> str:
    """Format one ProgressEvent for the GUI status label (localized).

    Accepts ProgressEvent or duck-typed objects with the same attributes
    so dual-import edge cases still render.
    """
    try:
        percent = float(getattr(ev, "percent", 0.0) or 0.0)
    except (TypeError, ValueError):
        percent = 0.0
    if percent != percent:  # NaN
        percent = 0.0
    percent = max(0.0, min(100.0, percent))
    stage = str(getattr(ev, "stage", "") or "")
    lang = getattr(ev, "lang", None) or ""
    lang_s = str(lang) if lang else ""
    try:
        current = int(getattr(ev, "current", 0) or 0)
    except (TypeError, ValueError):
        current = 0
    try:
        total = int(getattr(ev, "total", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    message = str(getattr(ev, "message", "") or "")
    return _(
        "{percent:.1f}%  {stage}  {lang}{current}/{total}  {message}"
    ).format(
        percent=percent,
        stage=localize_stage(stage),
        lang=(f"{lang_s}  " if lang_s else ""),
        current=current,
        total=total,
        message=localize_message(message),
    )


def localize_stage(stage: str) -> str:
    """Return translated display label for a progress stage id."""
    if stage == "parse":
        return _("parse")
    if stage == "tts":
        return _("tts")
    if stage == "fit":
        return _("fit")
    if stage == "timeline":
        return _("timeline")
    if stage == "report":
        return _("report")
    if stage == "translate":
        return _("translate")
    if stage == "translate_compress":
        return _("translate_compress")
    if stage == "translate_write":
        return _("translate_write")
    if stage == "glossary":
        return _("glossary")
    if stage == "ja_yomi":
        return _("ja_yomi")
    return stage


def localize_message(message: str) -> str:
    """Return translated display text for a known progress message.

    Unknown messages pass through unchanged so new core strings stay visible.
    """
    if not message:
        return ""

    # Exact matches (static English emit strings from core).
    if message == "parse srt":
        return _("parse srt")
    if message == "parsed":
        return _("parsed")
    if message == "dry_run done":
        return _("dry_run done")
    if message == "tts":
        return _("tts")
    if message == "tts done":
        return _("tts done")
    if message == "tts api":
        return _("tts api")
    if message == "fit":
        return _("fit")
    if message == "fit done":
        return _("fit done")
    if message == "timeline":
        return _("timeline")
    if message == "timeline done":
        return _("timeline done")
    if message == "report done":
        return _("report done")
    if message == "start":
        return _("start")
    if message == "done":
        return _("done")
    if message == "extract candidates":
        return _("extract candidates")
    if message == "chat suggest":
        return _("chat suggest")
    if message == "finalize glossary":
        return _("finalize glossary")

    m = _RE_CACHE_HIT.match(message)
    if m:
        return _("cache hit {current}/{total}").format(
            current=m.group(1), total=m.group(2)
        )

    # Before generic {target} batch — "hiragana" is not a BCP-47 target.
    m = _RE_HIRAGANA.match(message)
    if m:
        return _("hiragana batch {current}/{total}").format(
            current=m.group(1), total=m.group(2)
        )

    m = _RE_BATCH_WAITING.match(message)
    if m:
        return _("{target} batch {current}/{total} waiting chat... {seconds}s").format(
            target=m.group(1),
            current=m.group(2),
            total=m.group(3),
            seconds=m.group(4),
        )

    m = _RE_BATCH_DONE.match(message)
    if m:
        return _("{target} batch {current}/{total} done").format(
            target=m.group(1), current=m.group(2), total=m.group(3)
        )

    m = _RE_BATCH.match(message)
    if m:
        return _("{target} batch {current}/{total}").format(
            target=m.group(1), current=m.group(2), total=m.group(3)
        )

    m = _RE_COMPRESS.match(message)
    if m:
        return _("{target} compress index {index}").format(
            target=m.group(1), index=m.group(2)
        )

    m = _RE_WAITING.match(message)
    if m:
        return _("waiting chat... {seconds}s").format(seconds=m.group(1))

    m = _RE_CANDIDATES.match(message)
    if m:
        return _("candidates={count}").format(count=m.group(1))

    m = _RE_WRITE.match(message)
    if m:
        return _("write {name}").format(name=m.group(1))

    m = _RE_FINISHED.match(message)
    if m:
        return _("{target} finished").format(target=m.group(1))

    m = _RE_DRY_RUN.match(message)
    if m:
        return _("{target} dry-run").format(target=m.group(1))

    return message


# BCP-47-ish target tokens: letters, digits, hyphen (e.g. en, pt-BR, zh-Hans).
_TARGET = r"([A-Za-z0-9][A-Za-z0-9-]*)"

_RE_CACHE_HIT = re.compile(r"^cache hit (\d+)/(\d+)$")
_RE_BATCH_WAITING = re.compile(
    rf"^{_TARGET} batch (\d+)/(\d+) waiting chat\.\.\. (\d+)s$"
)
_RE_BATCH_DONE = re.compile(rf"^{_TARGET} batch (\d+)/(\d+) done$")
_RE_BATCH = re.compile(rf"^{_TARGET} batch (\d+)/(\d+)$")
_RE_COMPRESS = re.compile(rf"^{_TARGET} compress index (\d+)$")
_RE_WAITING = re.compile(r"^waiting chat\.\.\. (\d+)s$")
_RE_CANDIDATES = re.compile(r"^candidates=(\d+)$")
_RE_WRITE = re.compile(r"^write (.+)$")
_RE_FINISHED = re.compile(rf"^{_TARGET} finished$")
_RE_DRY_RUN = re.compile(rf"^{_TARGET} dry-run$")
_RE_HIRAGANA = re.compile(r"^hiragana batch (\d+)/(\d+)$")
