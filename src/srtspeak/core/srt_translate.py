"""Multilingual SRT translation (timing-lock, language-only delta).

Uses Grok Chat structured JSON, same pattern as ja_yomi.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Sequence

from srtspeak.core.cancel import BuildCancelled, CancellationToken
from srtspeak.core.util import DEFAULT_WORK_DIR
from srtspeak.core.languages import normalize_language_code
from srtspeak.core.models import TranslateConfig
from srtspeak.core.progress import ProgressEvent
from srtspeak.core.report import write_json
from srtspeak.core.srt_parser import Cue, apply_limit, format_srt, parse_srt, read_srt_text

ProgressCb = Callable[[ProgressEvent], None]
ChatFn = Callable[..., dict[str, Any]]


class TranslateError(ValueError):
    """Translation pipeline failure."""


_GROK_CHAT_URL = "https://api.x.ai/v1/chat/completions"
_TIMEOUT_S = 300

_JSON_SCHEMA: dict[str, Any] = {
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

# chars/sec heuristics (design §4.4)
_CHARS_PER_SEC: dict[str, float] = {
    "ja": 8.0,
    "en": 16.0,
    "pt": 15.0,
    "es": 15.0,
    "fr": 15.0,
    "de": 15.0,
    "it": 15.0,
    "zh": 6.5,
    "ko": 6.5,
    "default": 14.0,
}
_SAFETY = 0.85


def budget_chars(window_ms: int, language_code: str, *, safety: float = _SAFETY) -> int:
    """Estimate max characters for a cue window."""
    primary = language_code.split("-", 1)[0].lower()
    cps = _CHARS_PER_SEC.get(primary, _CHARS_PER_SEC["default"])
    raw = (max(window_ms, 0) / 1000.0) * cps * safety
    return max(8, int(math.floor(raw)))


def validate_structure_lock(src: Sequence[Cue], out: Sequence[Cue]) -> None:
    """Assert language-only delta: count/index/ms identical."""
    if len(out) != len(src):
        raise TranslateError(
            f"cue count mismatch: out={len(out)} src={len(src)}"
        )
    for a, b in zip(src, out):
        if a.index != b.index:
            raise TranslateError(
                f"index mismatch: src={a.index} out={b.index}"
            )
        if a.start_ms != b.start_ms or a.end_ms != b.end_ms:
            raise TranslateError(
                f"timing mismatch at index {a.index}: "
                f"src=[{a.start_ms},{a.end_ms}) out=[{b.start_ms},{b.end_ms})"
            )


def quality_warnings(
    src: Sequence[Cue],
    out: Sequence[Cue],
    *,
    identical_ratio_warn: float = 0.25,
) -> list[str]:
    """Soft quality checks (structure already locked)."""
    warnings: list[str] = []
    if len(src) != len(out):
        return warnings
    empty_idx: list[int] = []
    identical_idx: list[int] = []
    for a, b in zip(src, out):
        bt = (b.text or "").strip()
        at = (a.text or "").strip()
        if not bt:
            empty_idx.append(a.index)
        elif bt == at:
            identical_idx.append(a.index)
    n = max(len(src), 1)
    if empty_idx:
        sample = empty_idx[:10]
        more = len(empty_idx) - len(sample)
        msg = f"empty translation at index {sample}"
        if more > 0:
            msg += f" (+{more} more)"
        warnings.append(msg)
    if identical_idx:
        ratio = len(identical_idx) / n
        if ratio >= identical_ratio_warn or len(identical_idx) >= 3:
            sample = identical_idx[:10]
            more = len(identical_idx) - len(sample)
            msg = (
                f"translation identical to source at {len(identical_idx)}/{n} cues "
                f"(index {sample}"
            )
            if more > 0:
                msg += f" +{more} more"
            msg += f"); ratio={ratio:.0%}"
            warnings.append(msg)
    return warnings


def merge_translated_cues(
    src: Sequence[Cue],
    translated: dict[int, str],
    *,
    on_empty: str = "fail",
) -> list[Cue]:
    """Build output cues from source structure + translated texts."""
    missing = [c.index for c in src if c.index not in translated]
    if missing:
        raise TranslateError(f"missing translated index: {missing[:10]}")
    out: list[Cue] = []
    for cue in src:
        text = translated[cue.index]
        if text is None or not str(text).strip():
            if on_empty == "keep-source":
                out.append(cue)
                continue
            raise TranslateError(f"empty translated text at index {cue.index}")
        cleaned = str(text).strip()
        if len(cleaned) > 15_000:
            raise TranslateError(
                f"text exceeds 15000 characters at index {cue.index}"
            )
        out.append(replace(cue, text=cleaned))
    validate_structure_lock(src, out)
    return out


def _srt_input_hash(cues: Sequence[Cue]) -> str:
    """Fingerprint of source cue texts (report / debug only)."""
    payload = "|".join(f"{c.index}:{c.text}" for c in cues)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cache_file_token(target: str, out_name: str) -> str:
    """Stable file token from output SRT path pieces (target dir + file name)."""
    tgt = _target_dir_name(target)
    # Windows-safe single path segment
    safe = out_name.replace("\\", "_").replace("/", "_").replace(":", "_")
    return f"{tgt}__{safe}.json"


def _load_out_cache(path: Path) -> dict[str, dict[str, str]]:
    """Load index -> {{src, tgt}} cache keyed by output file name."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for k, v in data.items():
        if str(k).startswith("_"):
            continue
        if isinstance(v, dict):
            src = v.get("src")
            tgt = v.get("tgt")
            if isinstance(src, str) and isinstance(tgt, str):
                out[str(k)] = {"src": src, "tgt": tgt}
        elif isinstance(v, str):
            # legacy flat value without src — not reusable safely
            continue
    return out


def _save_out_cache(
    path: Path,
    cache: dict[str, dict[str, str]],
    *,
    out_name: str,
    target: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "_version": 2,
        "_out_name": out_name,
        "_target": normalize_language_code(target),
    }
    for k, v in cache.items():
        if str(k).startswith("_"):
            continue
        if isinstance(v, dict) and "src" in v and "tgt" in v:
            payload[str(k)] = {"src": v["src"], "tgt": v["tgt"]}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _seed_cache_from_output_srt(
    cache: dict[str, dict[str, str]],
    *,
    src_cues: list[Cue],
    out_path: Path,
) -> int:
    """Seed cache entries from an existing output SRT (structure-lock required).

    Only fills missing indexes (or matching src). Returns number of seeded entries.
    """
    if not out_path.is_file():
        return 0
    try:
        out_cues = parse_srt(out_path.read_text(encoding="utf-8"))
        validate_structure_lock(src_cues, out_cues)
    except (OSError, UnicodeError, TranslateError, ValueError):
        return 0
    seeded = 0
    for sc, oc in zip(src_cues, out_cues, strict=True):
        key = str(sc.index)
        tgt_text = (oc.text or "").strip()
        if not tgt_text:
            continue
        prev = cache.get(key)
        if prev is None:
            cache[key] = {"src": sc.text, "tgt": tgt_text}
            seeded += 1
        elif prev.get("src") == sc.text and not (prev.get("tgt") or "").strip():
            cache[key] = {"src": sc.text, "tgt": tgt_text}
            seeded += 1
    return seeded


def _load_glossary(path: Path | None) -> dict[str, Any]:
    from srtspeak.core.translate_glossary import GlossaryError, load_glossary

    try:
        return load_glossary(path)
    except GlossaryError as exc:
        raise TranslateError(str(exc)) from exc


def _glossary_hash(glossary: dict[str, Any]) -> str:
    if not glossary:
        return ""
    raw = json.dumps(glossary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _glossary_prompt_block(glossary: dict[str, Any], target_lang: str) -> str:
    if not glossary:
        return ""
    lines: list[str] = []
    tone = glossary.get("tone")
    if tone:
        lines.append(f"Tone: {tone}")
    dnt = glossary.get("do_not_translate") or []
    if dnt:
        lines.append("Do not translate: " + ", ".join(str(x) for x in dnt))
    terms = glossary.get("terms") or []
    for t in terms:
        if not isinstance(t, dict):
            continue
        src = t.get("source", "")
        if t.get("keep"):
            lines.append(f'- "{src}" => keep "{t["keep"]}"')
            continue
        # prefer target-specific, then en, then any
        tgt_val = t.get(target_lang) or t.get(target_lang.split("-")[0])
        if tgt_val:
            lines.append(f'- "{src}" => "{tgt_val}"')
    if not lines:
        return ""
    return "Glossary:\n" + "\n".join(lines)


def default_chat_fn(
    items: list[dict[str, Any]],
    *,
    target_lang: str,
    source_lang: str,
    api_key: str,
    model: str,
    glossary: dict[str, Any] | None = None,
    length_mode: str = "off",
    context_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call Grok Chat with structured JSON (index+text only)."""
    glossary = glossary or {}
    gloss_block = _glossary_prompt_block(glossary, target_lang)
    length_note = ""
    if length_mode in ("hint", "enforce"):
        length_note = (
            "Each item may include max_chars; do not exceed it. "
            "Compress meaning without dropping key facts.\n"
        )
    system = (
        f"You translate subtitle cues from {source_lang} to {target_lang}.\n"
        "Rules:\n"
        "1. Output ONLY the translation for each cue text. No commentary.\n"
        "2. Keep the same number of items and the same index values.\n"
        "3. Do not merge or split cues.\n"
        "4. Prefer glossary terms when provided.\n"
        "5. Subtitle style: concise, match source tone.\n"
        "6. Do not invent HTML tags.\n"
        f"{length_note}"
        f"{gloss_block}"
    ).strip()
    user_payload: dict[str, Any] = {"cues": items}
    if context_items:
        user_payload["context_previous"] = context_items
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "translated_cues",
                    "schema": _JSON_SCHEMA,
                    "strict": True,
                },
            },
            "temperature": 0.2,
            "max_tokens": 8000,
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
        raise TranslateError(f"Grok Chat API error {e.code}: {err_body}") from e
    except (KeyError, IndexError, json.JSONDecodeError, OSError) as e:
        raise TranslateError(f"Grok Chat response parse failed: {e}") from e


def _normalize_targets(
    targets: Sequence[str], source_lang: str
) -> tuple[list[str], list[str]]:
    """Return (normalized targets, skipped same-as-source)."""
    out: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    src_norm = normalize_language_code(source_lang)
    for t in targets:
        code = normalize_language_code(t)
        if code in seen:
            raise TranslateError(f"duplicate target language: {code}")
        seen.add(code)
        if code == src_norm:
            skipped.append(code)
            continue
        out.append(code)
    return out, skipped


def _target_dir_name(target: str) -> str:
    """Directory/file token for a target; keep BCP-47 (pt-BR ≠ pt-PT)."""
    return normalize_language_code(target)


def _output_srt_name(cfg: TranslateConfig, target: str, source_stem: str) -> str:
    token = _target_dir_name(target)
    if cfg.naming == "gran_tenku":
        return f"GRAN_TENKU_{token}.srt"
    return f"{source_stem}_{token}.srt"


def _emit(
    cb: ProgressCb,
    *,
    percent: float,
    stage: str,
    current: int,
    total: int,
    message: str = "",
    lang: str | None = None,
) -> None:
    cb(
        ProgressEvent(
            percent=round(max(0.0, min(100.0, percent)), 4),
            stage=stage,
            current=current,
            total=total,
            message=message,
            lang=lang,
        )
    )



def _chat_with_heartbeat(
    chat_fn: ChatFn,
    items: list[dict[str, Any]],
    *,
    target_lang: str,
    source_lang: str,
    api_key: str,
    model: str,
    glossary: dict[str, Any] | None,
    length_mode: str,
    context_items: list[dict[str, Any]] | None,
    progress_cb: ProgressCb,
    heartbeat_s: float,
    percent: float,
    current_batch: int,
    total_batches: int,
    done_base: int,
    processed: int,
    total_all: int,
    cancel_token: CancellationToken | None,
) -> dict[str, Any]:
    """Run chat_fn; when heartbeat_s > 0, pulse waiting progress on a side thread."""
    base_msg = f"{target_lang} batch {current_batch}/{total_batches}"
    if heartbeat_s <= 0:
        return chat_fn(
            items,
            target_lang=target_lang,
            source_lang=source_lang,
            api_key=api_key,
            model=model,
            glossary=glossary,
            length_mode=length_mode,
            context_items=context_items,
        )

    result_box: dict[str, Any] = {}
    error_box: list[BaseException] = []

    def _runner() -> None:
        try:
            result_box["raw"] = chat_fn(
                items,
                target_lang=target_lang,
                source_lang=source_lang,
                api_key=api_key,
                model=model,
                glossary=glossary,
                length_mode=length_mode,
                context_items=context_items,
            )
        except BaseException as exc:  # noqa: BLE001 — re-raised after join
            error_box.append(exc)

    worker = threading.Thread(target=_runner, name="translate-chat", daemon=True)
    worker.start()
    started = time.monotonic()
    interval = max(0.05, float(heartbeat_s))
    while worker.is_alive():
        if cancel_token is not None:
            try:
                cancel_token.check()
            except BuildCancelled:
                # leave daemon worker; surface cancel to caller
                raise
        worker.join(timeout=interval)
        if not worker.is_alive():
            break
        elapsed = time.monotonic() - started
        # slight asymptotic bump within the current cue-slot (cap +4%)
        frac = 1.0 - (1.0 / (1.0 + elapsed / 45.0))
        pct = min(99.0, percent + 4.0 * frac)
        _emit(
            progress_cb,
            percent=pct,
            stage="translate",
            current=current_batch,
            total=total_batches,
            message=f"{base_msg} waiting chat... {int(elapsed)}s",
            lang=target_lang,
        )

    if error_box:
        raise error_box[0]
    raw = result_box.get("raw")
    if not isinstance(raw, dict):
        raise TranslateError("chat response must be an object")
    return raw

def _translate_one_target(
    *,
    src_cues: list[Cue],
    cfg: TranslateConfig,
    target: str,
    source_lang: str,
    api_key: str,
    glossary: dict[str, Any],
    gloss_hash: str,
    out_name: str,
    out_path: Path,
    work_root: Path,
    progress_cb: ProgressCb,
    cancel_token: CancellationToken | None,
    chat_fn: ChatFn,
    done_base: int,
    total_all: int,
) -> dict[str, Any]:
    del gloss_hash  # retained at call site for report; entry key is out file + src text
    cache_path = work_root / _cache_file_token(target, out_name)
    cache: dict[str, dict[str, str]] = {}
    if not cfg.no_cache:
        cache = _load_out_cache(cache_path)
        _seed_cache_from_output_srt(cache, src_cues=src_cues, out_path=out_path)

    translated_map: dict[int, str] = {}
    pending: list[Cue] = []
    for cue in src_cues:
        key = str(cue.index)
        entry = cache.get(key)
        if (
            entry is not None
            and entry.get("src") == cue.text
            and (entry.get("tgt") or "").strip()
        ):
            translated_map[cue.index] = entry["tgt"]
        else:
            pending.append(cue)

    processed = len(src_cues) - len(pending)
    _emit(
        progress_cb,
        percent=(done_base + processed) / max(total_all, 1) * 100.0,
        stage="translate",
        current=done_base + processed,
        total=total_all,
        message=f"cache hit {processed}/{len(src_cues)}",
        lang=target,
    )

    batch_size = cfg.batch_size
    for bi in range(0, len(pending), batch_size):
        if cancel_token is not None:
            cancel_token.check()
        batch = pending[bi : bi + batch_size]
        # context: previous 1-2 source cues (not translated)
        ctx: list[dict[str, Any]] = []
        if batch:
            pos_map = {c.index: i for i, c in enumerate(src_cues)}
            pos = pos_map.get(batch[0].index, 0)
            for j in range(max(0, pos - 2), pos):
                c = src_cues[j]
                ctx.append({"index": c.index, "text": c.text})

        items: list[dict[str, Any]] = []
        for cue in batch:
            item: dict[str, Any] = {"index": cue.index, "text": cue.text}
            if cfg.length_mode in ("hint", "enforce"):
                item["max_chars"] = budget_chars(cue.window_ms, target)
            items.append(item)

        total_batches = max(1, math.ceil(len(pending) / batch_size))
        current_batch = bi // batch_size + 1
        batch_pct = (done_base + processed) / max(total_all, 1) * 100.0
        _emit(
            progress_cb,
            percent=batch_pct,
            stage="translate",
            current=current_batch,
            total=total_batches,
            message=f"{target} batch {current_batch}/{total_batches}",
            lang=target,
        )

        batch_indexes = [c.index for c in batch]
        try:
            result = _chat_with_heartbeat(
                chat_fn,
                items,
                target_lang=target,
                source_lang=source_lang,
                api_key=api_key,
                model=cfg.model,
                glossary=glossary,
                length_mode=cfg.length_mode,
                context_items=ctx or None,
                progress_cb=progress_cb,
                heartbeat_s=float(getattr(cfg, "heartbeat_s", 1.5) or 0.0),
                percent=batch_pct,
                current_batch=current_batch,
                total_batches=total_batches,
                done_base=done_base,
                processed=processed,
                total_all=total_all,
                cancel_token=cancel_token,
            )
        except BuildCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TranslateError(
                f"batch {current_batch}/{total_batches} target={target} "
                f"indexes={batch_indexes} chat error: {exc}"
            ) from exc
        cues_out = result.get("cues", []) if isinstance(result, dict) else []
        if len(cues_out) != len(batch):
            # one retry
            try:
                result = _chat_with_heartbeat(
                    chat_fn,
                    items,
                    target_lang=target,
                    source_lang=source_lang,
                    api_key=api_key,
                    model=cfg.model,
                    glossary=glossary,
                    length_mode=cfg.length_mode,
                    context_items=ctx or None,
                    progress_cb=progress_cb,
                    heartbeat_s=float(getattr(cfg, "heartbeat_s", 1.5) or 0.0),
                    percent=batch_pct,
                    current_batch=current_batch,
                    total_batches=total_batches,
                    done_base=done_base,
                    processed=processed,
                    total_all=total_all,
                    cancel_token=cancel_token,
                )
            except BuildCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                raise TranslateError(
                    f"batch {current_batch}/{total_batches} target={target} "
                    f"indexes={batch_indexes} chat retry error: {exc}"
                ) from exc
            cues_out = result.get("cues", []) if isinstance(result, dict) else []
        if len(cues_out) != len(batch):
            got_idx = []
            if isinstance(cues_out, list):
                for entry in cues_out:
                    if isinstance(entry, dict) and entry.get("index") is not None:
                        got_idx.append(entry.get("index"))
            raise TranslateError(
                f"batch {current_batch}/{total_batches} target={target} "
                f"count mismatch: got {len(cues_out)} expected {len(batch)}; "
                f"expected_indexes={batch_indexes} got_indexes={got_idx}"
            )
        index_map: dict[int, str] = {}
        for entry in cues_out:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("index")
            txt = entry.get("text", "")
            if idx is not None:
                index_map[int(idx)] = str(txt)

        for cue in batch:
            if cue.index not in index_map:
                raise TranslateError(
                    f"batch {current_batch}/{total_batches} target={target} "
                    f"missing index in API response: {cue.index}; "
                    f"expected_indexes={batch_indexes} got_indexes={sorted(index_map)}"
                )
            text = index_map[cue.index]
            max_c = None
            if cfg.length_mode in ("hint", "enforce"):
                max_c = budget_chars(cue.window_ms, target)
            # optional compress pass
            if (
                cfg.length_mode == "enforce"
                and max_c is not None
                and len(text.strip()) > max_c
            ):
                if cancel_token is not None:
                    cancel_token.check()
                _emit(
                    progress_cb,
                    percent=(done_base + processed) / max(total_all, 1) * 100.0,
                    stage="translate_compress",
                    current=done_base + processed,
                    total=total_all,
                    message=f"{target} compress index {cue.index}",
                    lang=target,
                )
                comp_items = [
                    {
                        "index": cue.index,
                        "text": text,
                        "max_chars": max_c,
                    }
                ]
                # reuse chat with enforce instruction via length_mode
                comp = chat_fn(
                    comp_items,
                    target_lang=target,
                    source_lang=source_lang,
                    api_key=api_key,
                    model=cfg.model,
                    glossary=glossary,
                    length_mode="enforce",
                    context_items=None,
                )
                comp_cues = comp.get("cues") or []
                if comp_cues:
                    text = str(comp_cues[0].get("text", text))

            translated_map[cue.index] = text
            cache[str(cue.index)] = {"src": cue.text, "tgt": text.strip()}
            processed += 1

        _save_out_cache(
            cache_path, cache, out_name=out_name, target=target
        )
        _emit(
            progress_cb,
            percent=(done_base + processed) / max(total_all, 1) * 100.0,
            stage="translate",
            current=current_batch,
            total=total_batches,
            message=f"{target} batch {current_batch}/{total_batches} done",
            lang=target,
        )

    out_cues = merge_translated_cues(
        src_cues, translated_map, on_empty=cfg.on_empty
    )
    warnings = quality_warnings(src_cues, out_cues)
    return {
        "cues": out_cues,
        "cache_hits": len(src_cues) - len(pending),
        "api_cues": len(pending),
        "warnings": warnings,
    }


def run_translate(
    config: TranslateConfig,
    *,
    api_key: str,
    progress_cb: ProgressCb,
    cancel_token: CancellationToken | None = None,
    chat_fn: ChatFn | None = None,
) -> dict[str, Any]:
    """Run multi-target SRT translation. ``progress_cb`` is required."""
    if progress_cb is None:
        # Allow explicit quiet callers; production CLI/GUI always pass a real cb.
        def progress_cb(_ev: ProgressEvent) -> None:
            return None
    config.validate()
    if not api_key and not config.dry_run:
        raise TranslateError("api_key is required")

    chat = chat_fn or default_chat_fn
    source_lang = normalize_language_code(config.source_lang)
    targets, skipped = _normalize_targets(config.targets, source_lang)
    if not targets and not skipped:
        raise TranslateError("no target languages")
    if not targets and skipped:
        raise TranslateError(
            f"all targets skipped (same as source): {skipped}"
        )

    text, srt_encoding = read_srt_text(config.srt_path)
    src_cues = parse_srt(text)
    src_cues = apply_limit(src_cues, config.limit)
    if not src_cues:
        raise TranslateError("no cues after limit")

    glossary = _load_glossary(config.glossary_path)
    gloss_hash = _glossary_hash(glossary)
    srt_hash = _srt_input_hash(src_cues)

    # Cache files named after output SRT (stable across re-runs / cwd).
    work_root = Path(config.work_dir or DEFAULT_WORK_DIR) / "translate" / "by_out"
    work_root.mkdir(parents=True, exist_ok=True)
    out_root = Path(config.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    total_all = len(targets) * len(src_cues)
    done_base = 0
    source_stem = config.srt_path.stem
    target_results: dict[str, Any] = {}
    ok_n = 0
    fail_n = 0

    _emit(
        progress_cb,
        percent=0.0,
        stage="translate",
        current=0,
        total=total_all,
        message="start",
        lang=None,
    )

    if config.dry_run:
        # estimate only
        for tgt in targets:
            over = 0
            chars = 0
            for c in src_cues:
                chars += len(c.text)
                b = budget_chars(c.window_ms, tgt)
                # rough: assume translation ~ same length * 1.1 for en from ja
                if int(len(c.text) * 1.1) > b:
                    over += 1
            target_results[tgt] = {
                "ok": True,
                "dry_run": True,
                "path": None,
                "cues": len(src_cues),
                "source_chars": chars,
                "budget_over_estimate": over,
                "batches": math.ceil(len(src_cues) / config.batch_size),
            }
            ok_n += 1
            done_base += len(src_cues)
            _emit(
                progress_cb,
                percent=done_base / max(total_all, 1) * 100.0,
                stage="translate",
                current=done_base,
                total=total_all,
                message=f"{tgt} dry-run",
                lang=tgt,
            )
        report_path = out_root / "translate_report.json"
        report = {
            "status": "dry_run",
            "source_lang": source_lang,
            "source_path": str(config.srt_path),
            "source_encoding": srt_encoding,
            "out_dir": str(out_root),
            "report_path": str(report_path),
            "cue_count": len(src_cues),
            "skipped_targets": skipped,
            "targets": target_results,
            "summary": {
                "ok": ok_n,
                "failed": fail_n,
                "skipped": len(skipped),
            },
        }
        write_json(report_path, report)
        _emit(
            progress_cb,
            percent=100.0,
            stage="translate",
            current=total_all,
            total=total_all,
            message="done",
        )
        return report

    for tgt in targets:
        if cancel_token is not None:
            cancel_token.check()
        try:
            tgt_dir = out_root / _target_dir_name(tgt)
            tgt_dir.mkdir(parents=True, exist_ok=True)
            out_name = _output_srt_name(config, tgt, source_stem)
            out_path = tgt_dir / out_name
            one = _translate_one_target(
                src_cues=src_cues,
                cfg=config,
                target=tgt,
                source_lang=source_lang,
                api_key=api_key,
                glossary=glossary,
                gloss_hash=gloss_hash,
                out_name=out_name,
                out_path=out_path,
                work_root=work_root,
                progress_cb=progress_cb,
                cancel_token=cancel_token,
                chat_fn=chat,
                done_base=done_base,
                total_all=total_all,
            )
            out_cues: list[Cue] = one["cues"]
            # write + re-parse verify
            _emit(
                progress_cb,
                percent=(done_base + len(src_cues)) / max(total_all, 1) * 100.0,
                stage="translate_write",
                current=done_base + len(src_cues),
                total=total_all,
                message=f"write {out_path.name}",
                lang=tgt,
            )
            srt_text = format_srt(out_cues)
            out_path.write_text(srt_text, encoding="utf-8")
            reparsed = parse_srt(out_path.read_text(encoding="utf-8"))
            validate_structure_lock(src_cues, reparsed)
            warns = list(one.get("warnings") or [])
            target_results[tgt] = {
                "ok": True,
                "path": str(out_path),
                "cues": len(out_cues),
                "cache_hits": one["cache_hits"],
                "api_cues": one["api_cues"],
                "warnings": warns,
                "errors": [],
            }
            ok_n += 1
        except BuildCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            err_s = str(exc)
            detail: dict[str, Any] = {"message": err_s}
            # best-effort parse batch marker from message
            if "batch " in err_s and "target=" in err_s:
                detail["kind"] = "batch_failure"
            target_results[tgt] = {
                "ok": False,
                "path": None,
                "cues": 0,
                "warnings": [],
                "errors": [err_s],
                "error_detail": detail,
            }
            fail_n += 1
            if config.fail_fast:
                done_base += len(src_cues)
                break
        done_base += len(src_cues)
        _emit(
            progress_cb,
            percent=done_base / max(total_all, 1) * 100.0,
            stage="translate",
            current=min(done_base, total_all),
            total=total_all,
            message=f"{tgt} finished",
            lang=tgt,
        )

    status = "ok" if fail_n == 0 else ("partial" if ok_n else "error")
    warn_n = 0
    for info in target_results.values():
        if isinstance(info, dict):
            warn_n += len(info.get("warnings") or [])
    if warn_n and status == "ok":
        status = "ok_with_warnings"
    report_path = out_root / "translate_report.json"
    report = {
        "status": status,
        "source_lang": source_lang,
        "source_path": str(config.srt_path),
        "source_encoding": srt_encoding,
        "out_dir": str(out_root),
        "report_path": str(report_path),
        "cue_count": len(src_cues),
        "skipped_targets": skipped,
        "targets": target_results,
        "summary": {
            "ok": ok_n,
            "failed": fail_n,
            "skipped": len(skipped),
            "warnings": warn_n,
        },
    }
    write_json(report_path, report)
    _emit(
        progress_cb,
        percent=100.0,
        stage="translate",
        current=total_all,
        total=total_all,
        message="done",
    )
    return report
