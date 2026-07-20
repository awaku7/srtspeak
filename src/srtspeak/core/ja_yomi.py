from __future__ import annotations

"""Japanese kanji to hiragana preprocessing for TTS via Grok Chat API (structured JSON)."""

import json
import os
import urllib.request
import urllib.error
from dataclasses import replace
from datetime import datetime
from typing import Any, Sequence

from srtspeak.core.cancel import BuildCancelled
from srtspeak.core.srt_parser import Cue
from srtspeak.core.progress import ProgressEvent


class JaYomiError(ValueError):
    """Raised when ja_yomi conversion fails."""


_GROK_CHAT_URL = "https://api.x.ai/v1/chat/completions"
_GROK_MODEL = "grok-4.5"
_TIMEOUT_S = 300
_LOG_FILE = None

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "cues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["index", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cues"],
    "additionalProperties": False,
}


def _log(msg):
    if _LOG_FILE:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {msg}\n")
        except OSError:
            pass


def init_ja_yomi_log(log_dir):
    global _LOG_FILE
    if log_dir is None:
        _LOG_FILE = None
        return
    path = os.path.join(str(log_dir), "srtspeak_ja_yomi.log")
    try:
        os.makedirs(str(log_dir), exist_ok=True)
        _LOG_FILE = path
        _log("--- ja_yomi log started ---")
    except OSError:
        _LOG_FILE = None


def should_apply_ja_yomi(*, enabled, lang):
    return bool(enabled) and lang == "ja"


def _call_chat_json(items, api_key):
    body = json.dumps({
        "model": _GROK_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You convert Japanese text to pure hiragana. "
                "Rules:\n"
                "1. Convert ALL kanji in each text to hiragana\n"
                "2. Keep punctuation, numbers, symbols, whitespace as-is\n"
                "3. Return the exact same number of items as input\n"
                "4. Preserve each item's original index\n"
                "5. If text has no kanji, return it unchanged"
            )},
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "hiragana_cues",
                "schema": _JSON_SCHEMA,
                "strict": True,
            },
        },
        "max_tokens": 8000,
    }).encode("utf-8")

    req = urllib.request.Request(
        _GROK_CHAT_URL, data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=_TIMEOUT_S)
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        result = json.loads(data["choices"][0]["message"]["content"])
        _log(f"RESPONSE OK: {len(result.get('cues', []))} cues")
        return result
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        _log(f"HTTP ERROR {e.code}: {err_body}")
        raise JaYomiError(f"Grok Chat API error {e.code}: {err_body}") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        _log(f"PARSE ERROR: {e}")
        raise JaYomiError(f"Grok Chat response parse failed: {e}") from e
    """Return True if text contains any CJK kanji."""
def _has_kanji(text: str) -> bool:
    """Return True if text contains any CJK kanji."""
    for ch in text:
        if 0x4E00 <= ord(ch) <= 0x9FFF:
            return True
    return False
BATCH_SIZE = 5


def convert_cues_batch(cues, api_key):
    items = [{"index": c.index, "text": c.text} for c in cues]
    _log(f"REQUEST: {len(items)} cues")
    result = _call_chat_json(items, api_key)

    cues_out = result.get("cues", [])
    if len(cues_out) != len(cues):
        _log(f"MISMATCH: got {len(cues_out)} cues, expected {len(cues)}")
        raise JaYomiError(f"Grok Chat returned {len(cues_out)} cues for {len(cues)} expected")

    index_map = {}
    for entry in cues_out:
        idx = entry.get("index")
        txt = entry.get("text", "")
        if idx is not None:
            index_map[idx] = txt.strip()

    out = []
    for cue in cues:
        yomi = index_map.get(cue.index)
        if yomi is None or yomi == cue.text:
            out.append(cue)
        else:
            out.append(replace(cue, text=yomi))

    return out


def apply_ja_yomi(cues, *, enabled, lang, api_key=None, progress_cb=None, cancel_token=None, work_dir=None, no_cache=False):
    """Return cues with ja_yomi applied, using cache for resumability."""
    if not should_apply_ja_yomi(enabled=enabled, lang=lang):
        return list(cues)
    if not api_key:
        return list(cues)

    # Load cache
    import json as _json
    cache = {}
    import hashlib as _hashlib
    input_hash = _hashlib.sha256("|".join(c.text for c in cues).encode("utf-8")).hexdigest()[:16]
    cache_path = None
    if work_dir:
        import os as _os
        cache_path = _os.path.join(str(work_dir), "ja_yomi_cache.json")
        if not no_cache:
            try:
                with open(cache_path, "r", encoding="utf-8") as _f:
                    cache = _json.load(_f)
                    cache_hash = cache.pop("_srt_hash", "")
                    if cache_hash != input_hash:
                        cache = {}
                        _log("SRT changed, cache invalidated")
                _log(f"Loaded {len(cache)} cached ja_yomi entries")
            except (FileNotFoundError, _json.JSONDecodeError):
                cache = {}

    out = []
    pending = []  # cues that need API call (index, cue)
    for cue in cues:
        key = str(cue.index)
        cached = cache.get(key)
        if cached is not None:
            out.append(replace(cue, text=cached))
        elif not _has_kanji(cue.text):
            out.append(cue)
        else:
            pending.append((key, cue))

    # Process pending cues in batches
    for bi in range(0, len(pending), BATCH_SIZE):
        batch_items = pending[bi:bi + BATCH_SIZE]
        batch = [item[1] for item in batch_items]
        keys = [item[0] for item in batch_items]

        if cancel_token:
            cancel_token.check()

        import math
        total_batches = max(1, math.ceil(len(pending) / BATCH_SIZE))
        current_batch = bi // BATCH_SIZE + 1
        _log(f"BATCH {current_batch}/{total_batches}: {len(batch)} cues")

        if progress_cb:
            done = min(len(out) + len(batch), len(cues))
            progress_cb(ProgressEvent(
                percent=done / max(len(cues), 1) * 100.0,
                stage="ja_yomi",
                current=done,
                total=len(cues),
                message=f"hiragana batch {current_batch}/{total_batches}",
                lang="ja",
            ))

        converted = convert_cues_batch(batch, api_key)
        for idx, (cv, (key, orig_cue)) in enumerate(zip(converted, batch_items)):
            if cv.text != orig_cue.text:
                cache[key] = cv.text
            out.append(cv)

        # Persist cache after each batch
        if cache_path:
            try:
                with open(cache_path, "w", encoding="utf-8") as _f:
                    cache["_srt_hash"] = input_hash
                    _json.dump(cache, _f, ensure_ascii=False)
            except OSError:
                pass

    out.sort(key=lambda c: c.index)
    return out
