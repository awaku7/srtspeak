from __future__ import annotations

"""Japanese kanji to hiragana preprocessing via xAI Responses API."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import os
import re
import time
from dataclasses import replace
from datetime import UTC, datetime

from srtspeak.core.perf import log_perf
from srtspeak.core.progress import ProgressEvent
from srtspeak.core.xai_responses import (
    DEFAULT_GROK_MODEL,
    ResponsesAPIError,
    request_responses_text,
)


class JaYomiError(ValueError):
    """Raised when ja_yomi conversion fails."""


_GROK_MODEL = DEFAULT_GROK_MODEL
_CACHE_VERSION = 2
_TIMEOUT_S = 300
_LOG_FILE = None

# Preserve xAI inline speech controls while the Japanese yomi pass rewrites text.
_INLINE_SPEECH_TAG_RE = re.compile(
    r"\[[A-Za-z][A-Za-z0-9_-]*(?:\s+[^\]]*)?\]"
    r"|</?[A-Za-z][A-Za-z0-9_-]*(?:\s+[^<>]*?)?\s*/?>"
)


def _mask_inline_speech_tags(text: str) -> tuple[str, list[tuple[str, str]]]:
    tags: list[tuple[str, str]] = []

    def _replace(match: re.Match[str]) -> str:
        token = f"SRTSPEECHTAG{len(tags):04d}TOKEN"
        while token in text:
            token = f"_{token}"
        tags.append((token, match.group(0)))
        return token

    return _INLINE_SPEECH_TAG_RE.sub(_replace, text), tags


def _restore_inline_speech_tags(text: str, tags: list[tuple[str, str]]) -> str | None:
    positions: list[int] = []
    for token, _tag in tags:
        if text.count(token) != 1:
            return None
        positions.append(text.index(token))
    if positions != sorted(positions):
        return None
    for token, tag in tags:
        text = text.replace(token, tag)
    return text

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
                f.write(f"[{datetime.now(UTC).isoformat()}] {msg}\n")
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
    try:
        text = request_responses_text(
            api_key=api_key,
            model=_GROK_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You convert Japanese text to pure hiragana. "
                        "Rules:\n"
                        "1. Convert ALL kanji in each text to hiragana\n"
                        "2. Keep punctuation, numbers, symbols, whitespace as-is\n"
                        "3. Return the exact same number of items as input\n"
                        "4. Preserve each item's original index\n"
                        "5. If text has no kanji, return it unchanged\n"
                        "6. Preserve SRTSPEECHTAG...TOKEN placeholders exactly, "
                        "in the same order; they stand for speech tags and are not spoken text"
                    ),
                },
                {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
            ],
            schema_name="hiragana_cues",
            schema=_JSON_SCHEMA,
            strict=True,
            max_output_tokens=8000,
            timeout=_TIMEOUT_S,
        )
        result = json.loads(text)
        if not isinstance(result, dict):
            raise TypeError("expected a JSON object")
        _log(f"RESPONSE OK: {len(result.get('cues', []))} cues")
        return result
    except ResponsesAPIError as exc:
        _log(f"RESPONSES API ERROR: {exc}")
        raise JaYomiError(f"Grok Responses API error: {exc}") from exc
    except (KeyError, IndexError, json.JSONDecodeError, TypeError, ValueError) as e:
        _log(f"PARSE ERROR: {e}")
        raise JaYomiError(f"Grok Responses output parse failed: {e}") from e
    """Return True if text contains any CJK kanji."""
def _has_kanji(text: str) -> bool:
    """Return True if text contains any CJK kanji."""
    for ch in text:
        if 0x4E00 <= ord(ch) <= 0x9FFF:
            return True
    return False
BATCH_SIZE = 5


def convert_cues_batch(cues, api_key):
    items = []
    tags_by_index: dict[int, list[tuple[str, str]]] = {}
    for cue in cues:
        masked_text, tags = _mask_inline_speech_tags(cue.text)
        tags_by_index[cue.index] = tags
        items.append({"index": cue.index, "text": masked_text})
    _log(f"REQUEST: {len(items)} cues")
    result = _call_chat_json(items, api_key)

    cues_out = result.get("cues", [])
    if len(cues_out) != len(cues):
        _log(f"MISMATCH: got {len(cues_out)} cues, expected {len(cues)}")
        raise JaYomiError(f"Grok Responses returned {len(cues_out)} cues for {len(cues)} expected")

    index_map = {}
    for entry in cues_out:
        idx = entry.get("index")
        txt = entry.get("text", "")
        if idx is not None:
            index_map[idx] = txt.strip()

    out = []
    for cue in cues:
        yomi = index_map.get(cue.index)
        if yomi is None:
            out.append(cue)
            continue
        restored = _restore_inline_speech_tags(yomi, tags_by_index[cue.index])
        if restored is None:
            # Safety first: never emit a conversion that lost or reordered markup.
            _log(f"SPEECH TAG MISMATCH at index {cue.index}; keeping original text")
            out.append(cue)
        elif restored == cue.text:
            out.append(cue)
        else:
            out.append(replace(cue, text=restored))

    return out


def apply_ja_yomi(cues, *, enabled, lang, api_key=None, progress_cb=None, cancel_token=None, work_dir=None, no_cache=False, parallel_requests=2):
    """Return cues with ja_yomi applied, using cache for resumability."""
    if not 1 <= parallel_requests <= 4:
        raise ValueError("parallel_requests must be between 1 and 4")
    if not should_apply_ja_yomi(enabled=enabled, lang=lang):
        return list(cues)
    if not api_key:
        return list(cues)

    stage_started = time.perf_counter()
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
                    cache_model = cache.pop("_model", None)
                    cache_version = cache.pop("_cache_version", 0)
                    if (
                        cache_hash != input_hash
                        or cache_model != _GROK_MODEL
                        or cache_version != _CACHE_VERSION
                    ):
                        cache = {}
                        _log("SRT, model, or yomi rules changed; cache invalidated")
                _log(f"Loaded {len(cache)} cached ja_yomi entries")
            except (FileNotFoundError, _json.JSONDecodeError):
                cache = {}

    out = []
    pending = []  # cues that need API call (index, cue)

    cache_hits = 0
    no_kanji_skips = 0
    for cue in cues:
        key = str(cue.index)
        cached = cache.get(key)
        if cached is not None:
            out.append(replace(cue, text=cached))
            cache_hits += 1
        elif not _has_kanji(cue.text):
            out.append(cue)
            no_kanji_skips += 1
        else:
            pending.append((key, cue))

    total_batches = math.ceil(len(pending) / BATCH_SIZE) if pending else 0
    api_calls = 0
    api_seconds = 0.0
    log_perf(
        event="stage_start",
        stage="ja_yomi",
        model=_GROK_MODEL,
        cue_count=len(cues),
        cache_hits=cache_hits,
        no_kanji_skips=no_kanji_skips,
        api_cues=len(pending),
        batch_size=BATCH_SIZE,
        batches=total_batches,
        no_cache=no_cache,
    )

    # Process pending cues in batches
    batch_plans = []
    for bi in range(0, len(pending), BATCH_SIZE):
        batch_items = pending[bi : bi + BATCH_SIZE]
        batch_plans.append(
            (bi // BATCH_SIZE + 1, batch_items, [item[1] for item in batch_items])
        )

    def _run_batch(plan):
        current_batch, _batch_items, batch = plan
        _log(f"BATCH {current_batch}/{total_batches}: {len(batch)} cues")
        started = time.perf_counter()
        try:
            converted = convert_cues_batch(batch, api_key)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            log_perf(
                event="api_call",
                operation="ja_yomi",
                target="ja",
                model=_GROK_MODEL,
                batch=f"{current_batch}/{total_batches}",
                cue_count=len(batch),
                cue_chars=sum(len(c.text) for c in batch),
                elapsed_s=round(elapsed, 3),
                status="error",
                error_type=type(exc).__name__,
            )
            raise
        elapsed = time.perf_counter() - started
        log_perf(
            event="api_call",
            operation="ja_yomi",
            target="ja",
            model=_GROK_MODEL,
            batch=f"{current_batch}/{total_batches}",
            cue_count=len(batch),
            cue_chars=sum(len(c.text) for c in batch),
            elapsed_s=round(elapsed, 3),
            status="ok",
        )
        return current_batch, plan[1], batch, converted, elapsed

    def _commit_batch(result):
        nonlocal api_calls, api_seconds
        _current_batch, batch_items, _batch, converted, elapsed = result
        api_calls += 1
        api_seconds += elapsed
        for cv, (key, orig_cue) in zip(converted, batch_items):
            if cv.text != orig_cue.text:
                cache[key] = cv.text
            out.append(cv)
        if cache_path:
            try:
                with open(cache_path, "w", encoding="utf-8") as _f:
                    cache["_srt_hash"] = input_hash
                    cache["_model"] = _GROK_MODEL
                    cache["_cache_version"] = _CACHE_VERSION
                    _json.dump(cache, _f, ensure_ascii=False)
            except OSError:
                pass

    if parallel_requests == 1:
        for plan in batch_plans:
            if cancel_token:
                cancel_token.check()
            batch = plan[2]
            if progress_cb:
                done = min(len(out) + len(batch), len(cues))
                progress_cb(
                    ProgressEvent(
                        percent=done / max(len(cues), 1) * 100.0,
                        stage="ja_yomi",
                        current=done,
                        total=len(cues),
                        message=f"hiragana batch {plan[0]}/{total_batches}",
                        lang="ja",
                    )
                )
            _commit_batch(_run_batch(plan))
    else:
        with ThreadPoolExecutor(max_workers=parallel_requests) as executor:
            futures = [executor.submit(_run_batch, plan) for plan in batch_plans]
            completed_cues = len(out)
            for future in as_completed(futures):
                if cancel_token:
                    cancel_token.check()
                result = future.result()
                _commit_batch(result)
                completed_cues += len(result[2])
                if progress_cb:
                    progress_cb(
                        ProgressEvent(
                            percent=completed_cues / max(len(cues), 1) * 100.0,
                            stage="ja_yomi",
                            current=completed_cues,
                            total=len(cues),
                            message=f"hiragana batch {result[0]}/{total_batches} done",
                            lang="ja",
                        )
                    )
    out.sort(key=lambda c: c.index)
    wall_seconds = time.perf_counter() - stage_started
    log_perf(
        event="stage_summary",
        stage="ja_yomi",
        cache_hits=cache_hits,
        no_kanji_skips=no_kanji_skips,
        api_cues=len(pending),
        api_calls=api_calls,
        api_seconds=round(api_seconds, 3),
        wall_seconds=round(wall_seconds, 3),
        non_api_seconds=round(max(0.0, wall_seconds - api_seconds), 3),
    )
    return out
