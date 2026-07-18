"""xAI Grok unary TTS client (stdlib urllib only)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from srtspeak.core.voices import VoiceOption, normalize_voice_id

API_BASE = "https://api.x.ai/v1"
TTS_URL = f"{API_BASE}/tts"
VOICES_URL = f"{API_BASE}/tts/voices"

CONNECT_TIMEOUT_S = 30.0
READ_TIMEOUT_S = 180.0
MAX_RETRIES = 3
RETRY_BACKOFF_S = (1.0, 2.0, 4.0)
RETRYABLE_STATUS = frozenset({429, 500, 503})


class TtsError(RuntimeError):
    """TTS HTTP or validation failure."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class TtsRequest:
    text: str
    voice_id: str
    language_code: str
    sample_rate: int = 24000
    codec: str = "wav"
    tts_speed: float = 1.0
    text_normalization: bool = True


def build_tts_request_body(
    *,
    text: str,
    voice_id: str,
    language_code: str,
    sample_rate: int = 24000,
    codec: str = "wav",
    tts_speed: float = 1.0,
    text_normalization: bool = True,
) -> dict[str, Any]:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("empty text")
    if len(cleaned) > 15_000:
        raise ValueError("text exceeds 15000 characters")
    if tts_speed != 1.0:
        raise ValueError("tts_speed must be 1.0 (ffmpeg handles tempo)")
    return {
        "text": cleaned,
        "voice_id": normalize_voice_id(voice_id),
        "language": language_code,
        "speed": 1.0,
        "text_normalization": bool(text_normalization),
        "output_format": {
            "codec": codec,
            "sample_rate": int(sample_rate),
        },
    }


def _auth_headers(api_key: str) -> dict[str, str]:
    key = api_key.strip()
    if not key:
        raise TtsError("empty api key", status=None)
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


def _urlopen(req: urllib.request.Request, *, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout)


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        data = exc.read()
        if not data:
            return ""
        text = data.decode("utf-8", errors="replace")
        # never echo secrets; body should not contain key but strip auth-ish tokens
        return text[:500]
    except Exception:
        return ""


def _http_post_bytes(
    url: str,
    *,
    api_key: str,
    body: dict[str, Any],
    timeout: float = READ_TIMEOUT_S,
) -> tuple[bytes, int]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = _auth_headers(api_key)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with _urlopen(req, timeout=timeout) as resp:
                status = int(getattr(resp, "status", None) or resp.getcode())
                data = resp.read()
                if status != 200:
                    raise TtsError(f"TTS unexpected status {status}", status=status)
                if not data:
                    raise TtsError("TTS empty body", status=status)
                return data, status
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            detail = _read_error_body(exc)
            msg = f"TTS HTTP {status}"
            if detail:
                msg = f"{msg}: {detail}"
            if status in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                time.sleep(delay)
                last_err = TtsError(msg, status=status)
                continue
            raise TtsError(msg, status=status) from exc
        except urllib.error.URLError as exc:
            if attempt < MAX_RETRIES:
                delay = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                time.sleep(delay)
                last_err = TtsError(f"TTS network error: {exc.reason}")
                continue
            raise TtsError(f"TTS network error: {exc.reason}") from exc
    if last_err:
        raise last_err
    raise TtsError("TTS failed")


def _http_get_json(
    url: str,
    *,
    api_key: str,
    timeout: float = CONNECT_TIMEOUT_S,
) -> Any:
    headers = _auth_headers(api_key)
    # GET should not force Content-Type application/json body
    headers = {
        "Authorization": headers["Authorization"],
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode())
            raw = resp.read()
            if status != 200:
                raise TtsError(f"voices HTTP {status}", status=status)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _read_error_body(exc)
        raise TtsError(
            f"voices HTTP {exc.code}" + (f": {detail}" if detail else ""),
            status=int(exc.code),
        ) from exc
    except urllib.error.URLError as exc:
        raise TtsError(f"voices network error: {exc.reason}") from exc


def synthesize_to_file(
    *,
    text: str,
    voice_id: str,
    language_code: str,
    api_key: str,
    out_path: Path | str,
    sample_rate: int = 24000,
    codec: str = "wav",
    tts_speed: float = 1.0,
    text_normalization: bool = True,
) -> tuple[Path, dict[str, Any]]:
    """POST /v1/tts and write raw audio bytes to *out_path*."""
    body = build_tts_request_body(
        text=text,
        voice_id=voice_id,
        language_code=language_code,
        sample_rate=sample_rate,
        codec=codec,
        tts_speed=tts_speed,
        text_normalization=text_normalization,
    )
    data, status = _http_post_bytes(TTS_URL, api_key=api_key, body=body)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, {"status": status, "bytes": len(data), "url": TTS_URL}


def fetch_voices(*, api_key: str) -> list[VoiceOption]:
    """GET /v1/tts/voices and return normalized VoiceOption list."""
    data = _http_get_json(VOICES_URL, api_key=api_key)
    items: list[Any]
    if isinstance(data, dict):
        items = data.get("voices") or data.get("data") or []
    elif isinstance(data, list):
        items = data
    else:
        raise TtsError("unexpected voices response shape")
    out: list[VoiceOption] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        vid = item.get("voice_id") or item.get("id") or item.get("name")
        if not vid:
            continue
        name = str(item.get("name") or vid)
        desc = str(item.get("description") or item.get("desc") or "")
        tags_raw = item.get("tags") or item.get("labels") or ()
        if isinstance(tags_raw, dict):
            tags = tuple(str(k) for k in tags_raw.keys())
        elif isinstance(tags_raw, (list, tuple)):
            tags = tuple(str(t) for t in tags_raw)
        else:
            tags = ()
        out.append(
            VoiceOption(
                voice_id=normalize_voice_id(str(vid)),
                name=name,
                description=desc,
                tags=tags,
            )
        )
    if not out:
        raise TtsError("voices list empty")
    return out


def merge_voice_catalog(
    builtin: list[VoiceOption],
    live: list[VoiceOption] | None,
) -> list[VoiceOption]:
    """Prefer live API entries; keep builtin for ids not returned."""
    by_id: dict[str, VoiceOption] = {v.voice_id: v for v in builtin}
    if live:
        for v in live:
            by_id[v.voice_id] = v
    return sorted(by_id.values(), key=lambda v: v.voice_id)
