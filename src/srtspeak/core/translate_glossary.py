"""Glossary JSON load/save/merge and LLM suggest for SRT translate."""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence

from srtspeak.core.progress import ProgressEvent
from srtspeak.core.srt_parser import Cue

ProgressCb = Callable[[ProgressEvent], None]


class GlossaryError(ValueError):
    """Glossary load/suggest failure."""


_GROK_CHAT_URL = "https://api.x.ai/v1/chat/completions"
_TIMEOUT_S = 300

_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tone": {"type": "string"},
        "do_not_translate": {
            "type": "array",
            "items": {"type": "string"},
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "keep": {"type": "string"},
                    "note": {"type": "string"},
                    "en": {"type": "string"},
                    "ja": {"type": "string"},
                    "pt-BR": {"type": "string"},
                    "pt-PT": {"type": "string"},
                    "es": {"type": "string"},
                    "fr": {"type": "string"},
                    "de": {"type": "string"},
                    "it": {"type": "string"},
                    "ko": {"type": "string"},
                    "zh": {"type": "string"},
                    "id": {"type": "string"},
                    "vi": {"type": "string"},
                    "th": {"type": "string"},
                    "ru": {"type": "string"},
                    "ar": {"type": "string"},
                    "hi": {"type": "string"},
                    "tr": {"type": "string"},
                    "nl": {"type": "string"},
                    "pl": {"type": "string"},
                    "sv": {"type": "string"},
                },
                "required": ["source"],
                "additionalProperties": True,
            },
        },
    },
    "required": ["terms"],
    "additionalProperties": True,
}

# Katakana runs (loanwords / names), long enough to be terms
_KATAKANA_RE = re.compile(r"[\u30A0-\u30FF]{3,}")
# CJK sequences 2+ (will filter by frequency)
_CJK_RE = re.compile(r"[\u4E00-\u9FFF]{2,}")
# Latin Proper-like tokens
_LATIN_RE = re.compile(r"\b[A-Z][A-Za-z0-9_\-]{2,}\b")
# ALL CAPS / code-like
_CAPS_RE = re.compile(r"\b[A-Z][A-Z0-9_\-]{2,}\b")

_TERM_DROP_KEYS = frozenset({"count"})
_TOP_DROP_KEYS = frozenset({"meta"})


def load_glossary(path: Path | None) -> dict[str, Any]:
    """Load glossary JSON. Missing path → empty dict."""
    if path is None:
        return {}
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GlossaryError(f"glossary load failed: {exc}") from exc
    if not isinstance(data, dict):
        raise GlossaryError("glossary must be a JSON object")
    return data


def save_glossary(path: Path, data: dict[str, Any]) -> None:
    """Write glossary JSON (UTF-8, indented).

    Drops runtime-only keys (``meta``, per-term ``count``) so files stay
    hand-editable and stable for translate cache hashing.
    """
    if not isinstance(data, dict):
        raise GlossaryError("glossary must be a JSON object")
    path.parent.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {}
    tone = data.get("tone")
    if isinstance(tone, str) and tone.strip():
        out["tone"] = tone.strip()
    dnt = data.get("do_not_translate") or []
    if isinstance(dnt, list):
        cleaned_dnt = [str(x).strip() for x in dnt if str(x).strip()]
        if cleaned_dnt:
            out["do_not_translate"] = cleaned_dnt
    terms = data.get("terms") or []
    if not isinstance(terms, list):
        raise GlossaryError("glossary.terms must be a list")
    cleaned_terms: list[dict[str, Any]] = []
    seen_src: set[str] = set()
    for t in terms:
        if not isinstance(t, dict):
            continue
        src = str(t.get("source", "")).strip()
        if not src or src in seen_src:
            continue
        seen_src.add(src)
        entry: dict[str, Any] = {"source": src}
        for k, v in t.items():
            if k == "source" or k in _TERM_DROP_KEYS:
                continue
            if v in (None, ""):
                continue
            entry[str(k)] = v
        cleaned_terms.append(entry)
    out["terms"] = cleaned_terms
    for k, v in data.items():
        if k in out or k in _TOP_DROP_KEYS or k in (
            "tone",
            "do_not_translate",
            "terms",
        ):
            continue
        out[k] = v
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_term_candidates(
    cues: Sequence[Cue],
    *,
    min_count: int = 2,
    max_candidates: int = 80,
) -> list[dict[str, Any]]:
    """Heuristic term candidates from cue texts (no API)."""
    counts: Counter[str] = Counter()
    for cue in cues:
        text = cue.text or ""
        for m in _KATAKANA_RE.findall(text):
            counts[m] += 1
        # Latin tokens once (ALLCAPS and ProperCase); avoid double-count
        seen_latin: set[str] = set()
        for rx in (_CAPS_RE, _LATIN_RE):
            for m in rx.findall(text):
                if m not in seen_latin:
                    seen_latin.add(m)
                    counts[m] += 1
        # CJK runs + sliding windows for longer phrases
        for m in _CJK_RE.findall(text):
            if 2 <= len(m) <= 8:
                counts[m] += 1
            if len(m) > 4:
                for n in (2, 3, 4):
                    for i in range(0, len(m) - n + 1):
                        counts[m[i : i + n]] += 1

    stop = {
        "こと",
        "もの",
        "よう",
        "ため",
        "さん",
        "して",
        "ます",
        "です",
        "した",
        "いる",
        "あり",
        "この",
        "その",
        "あの",
        "という",
    }
    items: list[tuple[str, int]] = []
    for term, n in counts.items():
        if n < min_count:
            continue
        if term in stop:
            continue
        if len(term) < 2:
            continue
        items.append((term, n))
    items.sort(key=lambda x: (-len(x[0]), -x[1], x[0]))
    chosen: list[tuple[str, int]] = []
    for term, n in items:
        if any(term != t and term in t and n <= cn + 1 for t, cn in chosen):
            continue
        chosen.append((term, n))
        if len(chosen) >= max_candidates:
            break
    return [{"source": t, "count": n} for t, n in chosen]


def merge_glossary(
    base: dict[str, Any],
    incoming: dict[str, Any],
    *,
    prefer: str = "base",
) -> dict[str, Any]:
    """Merge two glossaries. prefer=base keeps existing term fields on conflict."""
    if prefer not in ("base", "incoming"):
        raise GlossaryError("prefer must be base or incoming")
    out: dict[str, Any] = {}
    if prefer == "base":
        tone = base.get("tone") or incoming.get("tone") or ""
    else:
        tone = incoming.get("tone") or base.get("tone") or ""
    if tone:
        out["tone"] = tone

    dnt: list[str] = []
    for src in (base.get("do_not_translate") or []) + (
        incoming.get("do_not_translate") or []
    ):
        s = str(src).strip()
        if s and s not in dnt:
            dnt.append(s)
    if dnt:
        out["do_not_translate"] = dnt

    def _index(terms: Any) -> dict[str, dict[str, Any]]:
        m: dict[str, dict[str, Any]] = {}
        if not isinstance(terms, list):
            return m
        for t in terms:
            if not isinstance(t, dict):
                continue
            src = str(t.get("source", "")).strip()
            if src:
                m[src] = dict(t)
        return m

    a = _index(base.get("terms"))
    b = _index(incoming.get("terms"))
    keys = list(a.keys()) + [k for k in b if k not in a]
    merged_terms: list[dict[str, Any]] = []
    for k in keys:
        if k in a and k in b:
            if prefer == "base":
                entry = dict(b[k])
                entry.update(a[k])  # base wins
            else:
                entry = dict(a[k])
                entry.update(b[k])
            entry["source"] = k
            merged_terms.append(entry)
        elif k in a:
            merged_terms.append(dict(a[k]))
        else:
            merged_terms.append(dict(b[k]))
    out["terms"] = merged_terms
    return out


def _call_glossary_chat(
    *,
    sample_lines: list[str],
    candidates: list[dict[str, Any]],
    source_lang: str,
    targets: list[str],
    api_key: str,
    model: str,
) -> dict[str, Any]:
    tgt_s = ", ".join(targets)
    cand_s = json.dumps(candidates[:60], ensure_ascii=False)
    sample = "\n".join(sample_lines[:40])
    system = (
        "You build a translation glossary for subtitles / TTS narration.\n"
        "Return JSON only (schema).\n"
        "Rules:\n"
        "1. terms[].source must be exact substrings from the source language.\n"
        "2. Prefer proper nouns, place names, work titles, recurring technical terms.\n"
        "3. For brand/work titles that should stay fixed in all languages, set keep.\n"
        "4. For normal terms, set per-target fields using BCP-47 keys "
        f"from this list when possible: {tgt_s}.\n"
        "5. Do not invent terms absent from the sample/candidates.\n"
        "6. Keep the list concise (max ~40 terms).\n"
        "7. tone: short label for narration style if clear.\n"
        "8. do_not_translate: tokens that must remain unchanged.\n"
    )
    user = {
        "source_lang": source_lang,
        "targets": targets,
        "candidates": json.loads(cand_s),
        "sample_cues": sample,
    }
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(user, ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "glossary",
                    "schema": _JSON_SCHEMA,
                    "strict": False,
                },
            },
            "temperature": 0.2,
            "max_tokens": 6000,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        _GROK_CHAT_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        return json.loads(data["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise GlossaryError(f"Grok Chat API error {e.code}: {err_body}") from e
    except (KeyError, IndexError, json.JSONDecodeError, OSError) as e:
        raise GlossaryError(f"Grok Chat glossary parse failed: {e}") from e


def suggest_glossary(
    cues: Sequence[Cue],
    *,
    source_lang: str,
    targets: Sequence[str],
    api_key: str,
    model: str = "grok-4.5",
    min_count: int = 2,
    progress_cb: ProgressCb | None = None,
    chat_fn: Callable[..., dict[str, Any]] | None = None,
    heartbeat_s: float = 1.5,
) -> dict[str, Any]:
    """Suggest glossary via heuristics + Grok Chat.

    Emits progress during the long Chat wait via a background heartbeat so
    CLI/GUI do not sit silent between ~40% and finalize.
    """
    if not api_key:
        raise GlossaryError("api_key is required")
    if not targets:
        raise GlossaryError("targets must not be empty")
    if not cues:
        raise GlossaryError("no cues")

    def _emit(percent: float, message: str) -> None:
        if progress_cb is None:
            return
        progress_cb(
            ProgressEvent(
                percent=float(percent),
                stage="glossary",
                current=int(percent),
                total=100,
                message=message,
            )
        )

    _emit(5.0, "extract candidates")
    candidates = extract_term_candidates(list(cues), min_count=min_count)
    sample_lines = [c.text for c in cues[:80]]
    _emit(25.0, f"candidates={len(candidates)}")

    call = chat_fn or _call_glossary_chat
    _emit(40.0, "chat suggest")

    result_box: dict[str, Any] = {}
    error_box: list[BaseException] = []

    def _runner() -> None:
        try:
            result_box["raw"] = call(
                sample_lines=sample_lines,
                candidates=candidates,
                source_lang=source_lang,
                targets=list(targets),
                api_key=api_key,
                model=model,
            )
        except BaseException as exc:  # noqa: BLE001 — re-raised on join
            error_box.append(exc)

    worker = threading.Thread(target=_runner, name="glossary-chat", daemon=True)
    worker.start()
    started = time.monotonic()
    interval = max(0.05, float(heartbeat_s))
    while worker.is_alive():
        worker.join(timeout=interval)
        if not worker.is_alive():
            break
        elapsed = time.monotonic() - started
        # Asymptotic climb 40 -> 90 while waiting on Chat
        frac = 1.0 - (1.0 / (1.0 + elapsed / 30.0))
        pct = min(90.0, 40.0 + 50.0 * frac)
        _emit(pct, f"waiting chat... {int(elapsed)}s")

    if error_box:
        raise error_box[0]
    raw = result_box.get("raw")
    if not isinstance(raw, dict):
        raise GlossaryError("glossary response must be an object")

    _emit(92.0, "finalize glossary")
    terms = raw.get("terms") or []
    if not isinstance(terms, list):
        raise GlossaryError("glossary.terms must be a list")

    count_map = {c["source"]: c.get("count", 0) for c in candidates}
    # Full corpus for existence filter (not only sample window)
    corpus = "\n".join(c.text or "" for c in cues)
    cleaned: list[dict[str, Any]] = []
    dropped_missing: list[str] = []
    seen: set[str] = set()
    for t in terms:
        if not isinstance(t, dict):
            continue
        src = str(t.get("source", "")).strip()
        if not src or src in seen:
            continue
        if src not in corpus:
            dropped_missing.append(src)
            continue
        seen.add(src)
        entry = {k: v for k, v in t.items() if v not in (None, "")}
        entry["source"] = src
        if src in count_map and "count" not in entry:
            entry["count"] = count_map[src]
        cleaned.append(entry)

    dnt_raw = [
        str(x).strip()
        for x in (raw.get("do_not_translate") or [])
        if str(x).strip()
    ]

    out: dict[str, Any] = {
        "tone": str(raw.get("tone") or "").strip(),
        "do_not_translate": dnt_raw,
        "terms": cleaned,
        "meta": {
            "source_lang": source_lang,
            "targets": list(targets),
            "candidate_count": len(candidates),
            "model": model,
            "dropped_not_in_source": dropped_missing[:50],
            "dropped_not_in_source_count": len(dropped_missing),
        },
    }
    if not out["tone"]:
        out.pop("tone", None)
    if not out["do_not_translate"]:
        out.pop("do_not_translate", None)
    _emit(100.0, "done")
    return out
