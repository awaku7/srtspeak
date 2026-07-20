"""TDD: SRT translate merge/validate/cache/multi-target/progress."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from srtspeak.core.models import TranslateConfig
from srtspeak.core.progress import ProgressEvent
from srtspeak.core.srt_parser import Cue, format_srt, parse_srt
from srtspeak.core.srt_translate import (
    TranslateError,
    budget_chars,
    merge_translated_cues,
    quality_warnings,
    run_translate,
    validate_structure_lock,
)


def _cues() -> list[Cue]:
    return [
        Cue(1, 0, 1000, "こんにちは"),
        Cue(2, 1000, 2500, "高野山です"),
        Cue(3, 2500, 4000, "今日はいい天気"),
    ]


def test_merge_translated_cues_language_only_delta() -> None:
    src = _cues()
    translated = {
        1: "Hello",
        2: "This is Koyasan",
        3: "Nice weather today",
    }
    out = merge_translated_cues(src, translated)
    validate_structure_lock(src, out)
    assert [c.text for c in out] == [
        "Hello",
        "This is Koyasan",
        "Nice weather today",
    ]
    assert [c.index for c in out] == [1, 2, 3]
    assert [c.start_ms for c in out] == [0, 1000, 2500]


def test_merge_missing_index_raises() -> None:
    src = _cues()
    with pytest.raises(TranslateError, match="index"):
        merge_translated_cues(src, {1: "a", 2: "b"})


def test_merge_empty_text_fail() -> None:
    src = _cues()
    with pytest.raises(TranslateError, match="empty"):
        merge_translated_cues(src, {1: "a", 2: "  ", 3: "c"}, on_empty="fail")


def test_merge_empty_keep_source() -> None:
    src = _cues()
    out = merge_translated_cues(
        src, {1: "a", 2: "", 3: "c"}, on_empty="keep-source"
    )
    assert out[1].text == src[1].text


def test_validate_structure_lock_detects_time_drift() -> None:
    src = _cues()
    bad = [Cue(1, 0, 999, "x"), Cue(2, 1000, 2500, "y"), Cue(3, 2500, 4000, "z")]
    with pytest.raises(TranslateError):
        validate_structure_lock(src, bad)


def test_budget_chars_positive() -> None:
    n = budget_chars(window_ms=2000, language_code="en")
    assert n >= 10


def test_run_translate_multi_target_mock_chat(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    out_dir = tmp_path / "out"
    work = tmp_path / "work"

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        return {
            "cues": [
                {
                    "index": it["index"],
                    "text": f"{target_lang}:{it['text']}",
                }
                for it in items
            ]
        }

    events: list[ProgressEvent] = []

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en", "pt-BR"],
        out_dir=out_dir,
        work_dir=work,
        batch_size=2,
        length_mode="off",
    )
    result = run_translate(
        cfg,
        api_key="dummy",
        progress_cb=events.append,
        chat_fn=fake_chat,
    )
    assert result["summary"]["ok"] == 2
    assert result["summary"]["failed"] == 0
    en_path = Path(result["targets"]["en"]["path"])
    pt_path = Path(result["targets"]["pt-BR"]["path"])
    assert en_path.is_file()
    assert pt_path.is_file()
    en = parse_srt(en_path.read_text(encoding="utf-8"))
    validate_structure_lock(src_cues, en)
    assert en[0].text.startswith("en:")
    assert events, "progress required"
    percents = [e.percent for e in events]
    assert percents == sorted(percents)
    assert percents[-1] == 100.0




def test_run_translate_cache_seeds_from_output_srt(tmp_path: Path) -> None:
    """Existing out SRT with matching structure seeds cache → zero API."""
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    out_dir = tmp_path / "out"
    work = tmp_path / "work"
    # Pre-write translated output as if a previous run finished
    en_dir = out_dir / "en"
    en_dir.mkdir(parents=True)
    out_cues = [
        Cue(1, 0, 1000, "Hello"),
        Cue(2, 1000, 2500, "This is Koyasan"),
        Cue(3, 2500, 4000, "Nice weather today"),
    ]
    (en_dir / "src_en.srt").write_text(format_srt(out_cues), encoding="utf-8")

    calls = {"n": 0}

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        calls["n"] += 1
        return {
            "cues": [
                {"index": it["index"], "text": f"T{it['index']}"} for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=out_dir,
        work_dir=work,
        batch_size=10,
        length_mode="off",
        naming="stem",
    )
    report = run_translate(
        cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat
    )
    assert calls["n"] == 0
    assert report["targets"]["en"]["cache_hits"] == 3
    assert report["targets"]["en"]["api_cues"] == 0


def test_run_translate_cache_by_out_name_file(tmp_path: Path) -> None:
    """Cache file lives under work/translate/by_out/{tgt}__{out_name}.json."""
    src_cues = _cues()
    srt_path = tmp_path / "GRAN_TENKU_ja.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    out_dir = tmp_path / "out"
    work = tmp_path / "work"

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        return {
            "cues": [
                {"index": it["index"], "text": f"EN{it['index']}"} for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=out_dir,
        work_dir=work,
        batch_size=10,
        length_mode="off",
        naming="gran_tenku",
    )
    run_translate(cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat)
    cache_path = work / "translate" / "by_out" / "en__GRAN_TENKU_en.srt.json"
    assert cache_path.is_file()
    import json
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["_out_name"] == "GRAN_TENKU_en.srt"
    assert data["1"]["src"] == "こんにちは"
    assert data["1"]["tgt"] == "EN1"


def test_run_translate_cache_zero_api_second_run(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    out_dir = tmp_path / "out"
    work = tmp_path / "work"
    calls = {"n": 0}

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        calls["n"] += 1
        return {
            "cues": [
                {"index": it["index"], "text": f"T{it['index']}"} for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=out_dir,
        work_dir=work,
        batch_size=10,
        length_mode="off",
    )
    run_translate(cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat)
    n1 = calls["n"]
    assert n1 >= 1
    run_translate(cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat)
    assert calls["n"] == n1


def test_run_translate_no_cache_ignores_existing(tmp_path: Path) -> None:
    """no_cache=True must re-call Chat even when cache files exist."""
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    out_dir = tmp_path / "out"
    work = tmp_path / "work"
    calls = {"n": 0}

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        calls["n"] += 1
        return {
            "cues": [
                {"index": it["index"], "text": f"T{it['index']}-{calls['n']}"}
                for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=out_dir,
        work_dir=work,
        batch_size=10,
        length_mode="off",
    )
    run_translate(cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat)
    n1 = calls["n"]
    assert n1 >= 1

    cfg_nc = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=out_dir,
        work_dir=work,
        batch_size=10,
        length_mode="off",
        no_cache=True,
    )
    run_translate(cfg_nc, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat)
    assert calls["n"] == n1 * 2


def test_translate_config_no_cache_default_false() -> None:
    cfg = TranslateConfig(
        srt_path=Path("a.srt"),
        source_lang="ja",
        targets=["en"],
        out_dir=Path("o"),
    )
    assert cfg.no_cache is False


def test_run_translate_partial_failure_continue(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        if target_lang == "es":
            raise TranslateError("boom")
        return {
            "cues": [
                {"index": it["index"], "text": f"{target_lang}-{it['index']}"}
                for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en", "es", "fr"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        fail_fast=False,
        length_mode="off",
    )
    result = run_translate(
        cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat
    )
    assert result["summary"]["ok"] == 2
    assert result["summary"]["failed"] == 1
    assert result["targets"]["en"]["ok"] is True
    assert result["targets"]["es"]["ok"] is False
    assert Path(result["targets"]["en"]["path"]).is_file()


def test_run_translate_fail_fast(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    seen: list[str] = []

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        seen.append(target_lang)
        if target_lang == "en":
            raise TranslateError("fail-en")
        return {
            "cues": [
                {"index": it["index"], "text": "x"} for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en", "fr"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        fail_fast=True,
        length_mode="off",
    )
    result = run_translate(
        cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat
    )
    assert "fr" not in seen
    assert result["summary"]["failed"] >= 1


def test_translate_config_rejects_empty_targets() -> None:
    with pytest.raises(ValueError):
        TranslateConfig(
            srt_path=Path("a.srt"),
            source_lang="ja",
            targets=[],
            out_dir=Path("o"),
        ).validate()


def test_translate_config_no_api_key_field() -> None:
    from dataclasses import fields

    names = {f.name for f in fields(TranslateConfig)}
    assert "api_key" not in names


def test_write_reparse_structure_lock(tmp_path: Path) -> None:
    src = _cues()
    translated = merge_translated_cues(
        src, {1: "A", 2: "B", 3: "C"}
    )
    path = tmp_path / "out.srt"
    path.write_text(format_srt(translated), encoding="utf-8")
    again = parse_srt(path.read_text(encoding="utf-8"))
    validate_structure_lock(src, again)

def test_pt_br_and_pt_pt_write_distinct_paths(tmp_path: Path) -> None:
    """BCP-47 variants must not collapse to the same out dir (pt)."""
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        return {
            "cues": [
                {"index": it["index"], "text": f"{target_lang}-{it['index']}"}
                for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["pt-BR", "pt-PT"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        length_mode="off",
    )
    result = run_translate(
        cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat
    )
    p_br = Path(result["targets"]["pt-BR"]["path"])
    p_pt = Path(result["targets"]["pt-PT"]["path"])
    assert p_br != p_pt
    assert p_br.is_file() and p_pt.is_file()
    assert "pt-BR" in str(p_br) or p_br.parent.name == "pt-BR"
    assert "pt-PT" in str(p_pt) or p_pt.parent.name == "pt-PT"
    assert result.get("report_path")


def test_run_translate_accepts_none_progress(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        return {
            "cues": [
                {"index": it["index"], "text": f"x{it['index']}"} for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        length_mode="off",
    )
    result = run_translate(cfg, api_key="k", progress_cb=None, chat_fn=fake_chat)
    assert result["summary"]["ok"] == 1

def test_quality_warnings_identical_and_empty() -> None:
    src = _cues()
    out = [
        Cue(1, 0, 1000, "こんにちは"),
        Cue(2, 1000, 2500, "高野山です"),
        Cue(3, 2500, 4000, "今日はいい天気"),
    ]
    warns = quality_warnings(src, out, identical_ratio_warn=0.5)
    assert any("identical" in w for w in warns)

    out_empty = [
        Cue(1, 0, 1000, "Hello"),
        Cue(2, 1000, 2500, "   "),
        Cue(3, 2500, 4000, "x"),
    ]
    warns2 = quality_warnings(src, out_empty)
    assert any("empty" in w for w in warns2)


def test_run_translate_reports_identical_warning(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        # return source text unchanged -> identical warnings
        return {
            "cues": [
                {"index": it["index"], "text": it["text"]} for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        length_mode="off",
    )
    result = run_translate(
        cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat
    )
    assert result["targets"]["en"]["ok"] is True
    assert result["targets"]["en"]["warnings"]
    assert result["summary"]["warnings"] >= 1
    assert result["status"] == "ok_with_warnings"


def test_run_translate_batch_error_detail(tmp_path: Path) -> None:
    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        return {"cues": [{"index": items[0]["index"], "text": "only-one"}]}

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        batch_size=3,
        length_mode="off",
    )
    result = run_translate(
        cfg, api_key="k", progress_cb=lambda _e: None, chat_fn=fake_chat
    )
    assert result["targets"]["en"]["ok"] is False
    err = result["targets"]["en"]["errors"][0]
    assert "batch" in err
    assert "expected_indexes" in err
    assert result["targets"]["en"]["error_detail"]["kind"] == "batch_failure"


def test_run_translate_batch_chat_heartbeat(tmp_path: Path) -> None:
    """Chat wait must emit waiting heartbeats (not freeze progress)."""
    import time

    src_cues = _cues()
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    events: list[ProgressEvent] = []

    def slow_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        time.sleep(0.35)
        return {
            "cues": [
                {"index": it["index"], "text": f"{target_lang}:{it['text']}"}
                for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        batch_size=2,
        length_mode="off",
        heartbeat_s=0.1,
    )
    result = run_translate(
        cfg,
        api_key="k",
        progress_cb=events.append,
        chat_fn=slow_chat,
    )
    assert result["summary"]["ok"] == 1
    messages = [e.message for e in events]
    waiting = [m for m in messages if "waiting chat" in m]
    assert waiting, messages
    # batch phase: current/total are batch counters, not raw cue totals only
    batch_evs = [
        e
        for e in events
        if e.message and "batch" in e.message and "done" not in e.message
    ]
    assert batch_evs, messages
    assert any(e.total >= 1 and e.current >= 1 for e in batch_evs)
    # percents stay non-decreasing overall (allow equal)
    percents = [e.percent for e in events]
    assert percents == sorted(percents)
    assert percents[-1] == 100.0


def test_run_translate_batch_progress_uses_batch_counters(tmp_path: Path) -> None:
    """During batch work, ProgressEvent.current/total reflect batch index."""
    src_cues = _cues()  # 3 cues
    srt_path = tmp_path / "src.srt"
    srt_path.write_text(format_srt(src_cues), encoding="utf-8")
    events: list[ProgressEvent] = []

    def fake_chat(items: list[dict], *, target_lang: str, **_kw: object) -> dict:
        return {
            "cues": [
                {"index": it["index"], "text": f"{target_lang}:{it['text']}"}
                for it in items
            ]
        }

    cfg = TranslateConfig(
        srt_path=srt_path,
        source_lang="ja",
        targets=["en"],
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        batch_size=2,  # 2 batches for 3 cues
        length_mode="off",
        heartbeat_s=0.0,  # disable wait thread noise
    )
    run_translate(cfg, api_key="k", progress_cb=events.append, chat_fn=fake_chat)
    start_batch = [
        e
        for e in events
        if e.message == "en batch 1/2" or e.message == "en batch 2/2"
    ]
    assert start_batch, [e.message for e in events]
    for e in start_batch:
        assert e.total == 2
        assert e.current in (1, 2)
        assert e.lang == "en"
