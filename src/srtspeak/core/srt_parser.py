"""SRT parser (stdlib only).

User-facing anomaly messages use English gettext msgids (see ``srtspeak.i18n``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from srtspeak.i18n import _


_TS_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)
_ARROW_RE = re.compile(r"\s*-->\s*")


class SrtParseError(ValueError):
    """SRT parse failure. ``issues`` holds individual problem strings."""

    def __init__(self, issues: str | list[str]) -> None:
        if isinstance(issues, str):
            issue_list = [issues]
        else:
            issue_list = [str(x) for x in issues if str(x).strip()]
        if not issue_list:
            issue_list = [_("unknown parse error")]
        self.issues: list[str] = issue_list
        super().__init__(self._format())

    def _format(self) -> str:
        if len(self.issues) == 1:
            return _("SRT parse error: {detail}").format(detail=self.issues[0])
        lines = [_("SRT parse error: the following problems were found:")]
        for i, issue in enumerate(self.issues, 1):
            lines.append(f"  {i}. {issue}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def window_ms(self) -> int:
        return self.end_ms - self.start_ms


def _ms_to_ts(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, rem = divmod(ms, 3_600_000)
    mi, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{milli:03d}"


def parse_timestamp_ms(value: str) -> int:
    m = _TS_RE.fullmatch(value.strip())
    if not m:
        raise SrtParseError(
            _("invalid timestamp: {value} (expected HH:MM:SS,mmm or HH:MM:SS.mmm)").format(
                value=repr(value)
            )
        )
    h = int(m.group("h"))
    mi = int(m.group("m"))
    s = int(m.group("s"))
    ms_raw = m.group("ms")
    # pad/truncate to milliseconds
    ms = int((ms_raw + "000")[:3])
    return ((h * 60 + mi) * 60 + s) * 1000 + ms


def _split_blocks(text: str) -> list[str]:
    # normalize newlines, strip BOM already handled by caller encoding
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return re.split(r"\n\s*\n+", normalized)


def _parse_block(block: str, block_no: int) -> tuple[Cue | None, list[str]]:
    """Parse one block. Success: (Cue, []); failure: (None, issues)."""
    issues: list[str] = []
    lines = [ln for ln in block.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return None, []

    # index
    try:
        index = int(lines[0].strip())
    except ValueError:
        issues.append(
            _("block {block_no}: cue index is not a number: {value}").format(
                block_no=block_no,
                value=repr(lines[0]),
            )
        )
        return None, issues

    label = _("cue {index}").format(index=index)

    if len(lines) < 2:
        issues.append(
            _("{label}: missing timing line").format(label=label)
        )
        return None, issues

    timing = lines[1].strip()
    parts = _ARROW_RE.split(timing)
    if len(parts) != 2:
        issues.append(
            _("{label}: invalid timing line: {timing} (expected start --> end)").format(
                label=label,
                timing=repr(timing),
            )
        )
        return None, issues

    start_ms: int | None = None
    end_ms: int | None = None
    try:
        start_ms = parse_timestamp_ms(parts[0].strip())
    except SrtParseError as exc:
        detail = exc.issues[0] if exc.issues else str(exc)
        issues.append(
            _("{label}: start {detail}").format(label=label, detail=detail)
        )

    end_token = parts[1].strip().split()[0] if parts[1].strip() else ""
    try:
        end_ms = parse_timestamp_ms(end_token)
    except SrtParseError as exc:
        detail = exc.issues[0] if exc.issues else str(exc)
        issues.append(
            _("{label}: end {detail}").format(label=label, detail=detail)
        )

    if start_ms is not None and end_ms is not None and end_ms <= start_ms:
        issues.append(
            _(
                "{label}: end time is not after start time "
                "({start} → {end}, non-positive duration)"
            ).format(
                label=label,
                start=_ms_to_ts(start_ms),
                end=_ms_to_ts(end_ms),
            )
        )

    text_lines = lines[2:]
    text = "\n".join(ln.strip() for ln in text_lines).strip()
    # remove simple HTML-ish tags often found in SRT
    text = re.sub(r"<[^>]+>", "", text).strip()
    if not text:
        issues.append(_("{label}: text is empty").format(label=label))
    elif len(text) > 15_000:
        issues.append(
            _("{label}: text exceeds 15000 characters ({n} characters)").format(
                label=label,
                n=len(text),
            )
        )

    if issues:
        return None, issues

    assert start_ms is not None and end_ms is not None
    return (
        Cue(index=index, start_ms=start_ms, end_ms=end_ms, text=text),
        [],
    )


def parse_srt(source: str) -> list[Cue]:
    """Parse SRT text into cues. Anomalies raise :class:`SrtParseError`.

    Collect as many issues as practical into ``issues``.
    """
    cues: list[Cue] = []
    issues: list[str] = []

    blocks = _split_blocks(source)
    for block_no, block in enumerate(blocks, 1):
        cue, block_issues = _parse_block(block, block_no)
        if block_issues:
            issues.extend(block_issues)
            continue
        if cue is not None:
            cues.append(cue)

    if not cues and not issues:
        raise SrtParseError(
            _("no cues found in SRT (empty file or invalid format)")
        )

    if not cues and issues:
        raise SrtParseError(issues)

    # overlap check: half-open [start, end); adjacent equal is OK
    ordered = sorted(cues, key=lambda c: (c.start_ms, c.index))
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.start_ms < prev.end_ms:
            issues.append(
                _(
                    "cues {a} and {b} overlap in time: "
                    "[{sa},{ea}) and [{sb},{eb}) "
                    "(half-open [start,end); adjacent is allowed)"
                ).format(
                    a=prev.index,
                    b=cur.index,
                    sa=_ms_to_ts(prev.start_ms),
                    ea=_ms_to_ts(prev.end_ms),
                    sb=_ms_to_ts(cur.start_ms),
                    eb=_ms_to_ts(cur.end_ms),
                )
            )

    if issues:
        raise SrtParseError(issues)

    # return in file/index order as parsed
    return cues


def apply_limit(cues: list[Cue], limit: int | None) -> list[Cue]:
    if limit is None:
        return list(cues)
    if limit < 1:
        raise ValueError(_("limit must be >= 1"))
    return list(cues[:limit])
