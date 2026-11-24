"""Tests for Japanese kanji to hiragana (ja_yomi) via xAI Responses API (structured JSON)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from srtspeak.core.ja_yomi import (
    JaYomiError,
    _call_chat_json,
    apply_ja_yomi,
    convert_cues_batch,
    should_apply_ja_yomi,
)
from srtspeak.core.models import BuildConfig
from srtspeak.core.srt_parser import Cue


def test_should_apply_only_for_ja() -> None:
    assert should_apply_ja_yomi(enabled=True, lang="ja") is True
    assert should_apply_ja_yomi(enabled=True, lang="en") is False
    assert should_apply_ja_yomi(enabled=False, lang="ja") is False


def test_ja_yomi_uses_responses_structured_output() -> None:
    with patch(
        "srtspeak.core.ja_yomi.request_responses_text",
        return_value='{"cues":[{"index":1,"text":"こうやさん"}]}',
    ) as request:
        result = _call_chat_json([{"index": 1, "text": "高野山"}], "test-key")

    assert result["cues"][0]["text"] == "こうやさん"
    assert request.call_args.kwargs["model"] == "grok-4.7"
    assert request.call_args.kwargs["schema_name"] == "hiragana_cues"
    assert request.call_args.kwargs["strict"] is True
    assert request.call_args.kwargs["max_output_tokens"] == 8000


def test_ja_yomi_rejects_non_object_json_response() -> None:
    with (
        patch(
            "srtspeak.core.ja_yomi.request_responses_text",
            return_value="[]",
        ),
        pytest.raises(JaYomiError, match="expected a JSON object"),
    ):
        _call_chat_json([{"index": 1, "text": "高野山"}], "test-key")


def test_apply_ja_yomi_noop_when_disabled() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    out = apply_ja_yomi(cues, enabled=False, lang="ja")
    assert out[0].text == "高野山"


def test_apply_ja_yomi_noop_for_en() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    out = apply_ja_yomi(cues, enabled=True, lang="en")
    assert out[0].text == "高野山"


def test_apply_ja_yomi_noop_without_api_key() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    out = apply_ja_yomi(cues, enabled=True, lang="ja", api_key=None)
    assert out[0].text == "高野山"


def test_convert_cues_batch_success() -> None:
    cues = [
        Cue(1, 0, 1000, "高野山来ました。"),
        Cue(2, 1000, 2000, "今日はいい天気です。"),
    ]
    mock_response = {
        "cues": [
            {"index": 1, "text": "こうやさんきました。"},
            {"index": 2, "text": "きょうはいいてんきです。"},
        ]
    }
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response):
        out = convert_cues_batch(cues, "dummy-key")

    assert out[0].text == "こうやさんきました。"
    assert out[1].text == "きょうはいいてんきです。"
    assert out[0].index == 1
    assert out[1].index == 2


def test_convert_cues_batch_preserves_inline_speech_tags() -> None:
    cues = [Cue(1, 0, 1000, "<whisper>高野山</whisper>[pause][laugh]")]

    def fake_chat(items: list[dict], _api_key: str) -> dict:
        sent = items[0]["text"]
        assert "<whisper>" not in sent
        assert "</whisper>" not in sent
        assert "[pause]" not in sent
        assert "[laugh]" not in sent
        assert "SRTSPEECHTAG" in sent
        return {
            "cues": [
                {"index": items[0]["index"], "text": sent.replace("高野山", "こうやさん")}
            ]
        }

    with patch("srtspeak.core.ja_yomi._call_chat_json", side_effect=fake_chat):
        out = convert_cues_batch(cues, "dummy-key")

    assert out[0].text == "<whisper>こうやさん</whisper>[pause][laugh]"


def test_convert_cues_batch_falls_back_if_tag_placeholder_is_lost() -> None:
    cues = [Cue(1, 0, 1000, "<whisper>高野山</whisper>")]
    with patch(
        "srtspeak.core.ja_yomi._call_chat_json",
        return_value={"cues": [{"index": 1, "text": "こうやさん"}]},
    ):
        out = convert_cues_batch(cues, "dummy-key")
    assert out[0].text == cues[0].text


def test_convert_cues_batch_mismatch() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    mock_response = {"cues": [{"index": 1, "text": "こうやさん"}, {"index": 2, "text": "余分"}]}
    with (
        patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response),
        pytest.raises(JaYomiError, match="returned 2 cues for 1 expected"),
    ):
        convert_cues_batch(cues, "dummy-key")


def test_convert_cues_batch_api_error() -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    with (
        patch(
            "srtspeak.core.ja_yomi._call_chat_json",
            side_effect=JaYomiError("Grok Responses API error: 401"),
        ),
        pytest.raises(JaYomiError, match="Grok Responses API error: 401"),
    ):
        convert_cues_batch(cues, "bad-key")


def test_build_config_ja_yomi_default_true() -> None:
    cfg = BuildConfig(
        srt_path=Path("a.srt"),
        lang="ja",
        language_code="ja",
        out_dir=Path("out"),
    )
    assert cfg.ja_yomi is True


def test_apply_ja_yomi_integration_via_chat() -> None:
    cues = [
        Cue(1, 0, 1000, "高野山来ました。"),
        Cue(2, 1000, 2000, "こんにちは"),
    ]
    mock_response = {
        "cues": [
            {"index": 1, "text": "こうやさんきました。"},
        ]
    }
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response):
        out = apply_ja_yomi(cues, enabled=True, lang="ja", api_key="test")

    assert "高" not in out[0].text
    assert out[1].text == "こんにちは"


def test_apply_ja_yomi_no_cache_ignores_file(tmp_path: Path) -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    work = tmp_path / "work"
    work.mkdir()
    # seed cache with wrong conversion to prove bypass
    cache_path = work / "ja_yomi_cache.json"
    import hashlib
    import json

    h = hashlib.sha256("|".join(c.text for c in cues).encode("utf-8")).hexdigest()[:16]
    cache_path.write_text(
        json.dumps({"_srt_hash": h, "1": "cached-wrong"}, ensure_ascii=False),
        encoding="utf-8",
    )
    mock_response = {"cues": [{"index": 1, "text": "こうやさん"}]}
    with patch("srtspeak.core.ja_yomi._call_chat_json", return_value=mock_response) as m:
        out = apply_ja_yomi(
            cues,
            enabled=True,
            lang="ja",
            api_key="k",
            work_dir=work,
            no_cache=True,
        )
    assert m.called
    assert out[0].text == "こうやさん"


def test_apply_ja_yomi_invalidates_cache_from_another_model(tmp_path: Path) -> None:
    cues = [Cue(1, 0, 1000, "高野山")]
    work = tmp_path / "work"
    work.mkdir()
    cache_path = work / "ja_yomi_cache.json"
    import hashlib
    import json

    input_hash = hashlib.sha256("高野山".encode()).hexdigest()[:16]
    cache_path.write_text(
        json.dumps(
            {"_srt_hash": input_hash, "_model": "grok-4.5", "1": "old reading"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    response = {"cues": [{"index": 1, "text": "こうやさん"}]}

    with patch(
        "srtspeak.core.ja_yomi._call_chat_json", return_value=response
    ) as call:
        out = apply_ja_yomi(
            cues,
            enabled=True,
            lang="ja",
            api_key="test-key",
            work_dir=work,
        )

    assert call.called
    assert out[0].text == "こうやさん"
    updated = json.loads(cache_path.read_text(encoding="utf-8"))
    assert updated["_model"] == "grok-4.7"
    assert updated["_cache_version"] == 2


def test_apply_ja_yomi_invalidates_legacy_cache_with_inline_tag(tmp_path: Path) -> None:
    cues = [Cue(1, 0, 1000, "<whisper>高野山</whisper>[pause]")]
    work = tmp_path / "work"
    work.mkdir()
    cache_path = work / "ja_yomi_cache.json"
    import hashlib
    import json

    input_hash = hashlib.sha256(cues[0].text.encode()).hexdigest()[:16]
    cache_path.write_text(
        json.dumps(
            {"_srt_hash": input_hash, "_model": "grok-4.7", "1": "stale reading"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_chat(items: list[dict], _api_key: str) -> dict:
        sent = items[0]["text"]
        return {
            "cues": [
                {"index": 1, "text": sent.replace("高野山", "こうやさん")}
            ]
        }

    with patch("srtspeak.core.ja_yomi._call_chat_json", side_effect=fake_chat) as call:
        out = apply_ja_yomi(
            cues,
            enabled=True,
            lang="ja",
            api_key="test-key",
            work_dir=work,
        )

    assert call.called
    assert out[0].text == "<whisper>こうやさん</whisper>[pause]"


def test_apply_ja_yomi_parallel_requests_converts_batches_concurrently(
    tmp_path: Path,
) -> None:
    import threading

    cues = [Cue(i, i * 1000, (i + 1) * 1000, f"漢字{i}") for i in range(1, 12)]
    lock = threading.Lock()
    two_active = threading.Event()
    active = 0
    max_active = 0

    def fake_chat(items: list[dict], _api_key: str) -> dict:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active >= 2:
                two_active.set()
        try:
            assert two_active.wait(timeout=3)
            return {
                "cues": [
                    {"index": item["index"], "text": "かんじ"}
                    for item in items
                ]
            }
        finally:
            with lock:
                active -= 1

    with patch("srtspeak.core.ja_yomi._call_chat_json", side_effect=fake_chat):
        out = apply_ja_yomi(
            cues,
            enabled=True,
            lang="ja",
            api_key="test-key",
            work_dir=tmp_path,
            no_cache=True,
            parallel_requests=2,
        )

    assert max_active == 2
    assert [cue.index for cue in out] == list(range(1, 12))
    assert all(cue.text == "かんじ" for cue in out)

