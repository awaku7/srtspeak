"""TDD: glossary load/save/suggest."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from srtspeak.core.srt_parser import Cue
from srtspeak.core.translate_glossary import (
    GlossaryError,
    extract_term_candidates,
    load_glossary,
    merge_glossary,
    save_glossary,
    suggest_glossary,
)


def test_load_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    data = {
        "tone": "documentary",
        "do_not_translate": ["GRAN_TENKU"],
        "terms": [{"source": "結界", "en": "barrier"}],
    }
    save_glossary(path, data)
    loaded = load_glossary(path)
    assert loaded["tone"] == "documentary"
    assert loaded["terms"][0]["en"] == "barrier"


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load_glossary(tmp_path / "nope.json") == {}


def test_load_invalid_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[1,2]", encoding="utf-8")
    with pytest.raises(GlossaryError):
        load_glossary(path)


def test_extract_term_candidates_katakana_and_repeat() -> None:
    cues = [
        Cue(1, 0, 1000, "グラン天空に行く"),
        Cue(2, 1000, 2000, "グラン天空の結界"),
        Cue(3, 2000, 3000, "結界が光る"),
        Cue(4, 3000, 4000, "普通の文です"),
    ]
    cands = extract_term_candidates(cues, min_count=2)
    sources = {c["source"] for c in cands}
    assert "グラン天空" in sources or "結界" in sources
    # single-occurrence plain words should not dominate
    assert "普通の文です" not in sources


def test_merge_glossary_keeps_existing_prefers_base() -> None:
    base = {
        "tone": "old",
        "terms": [{"source": "結界", "en": "ward"}],
    }
    incoming = {
        "tone": "new",
        "terms": [
            {"source": "結界", "en": "barrier", "pt-BR": "barreira"},
            {"source": "高野山", "keep": "Koyasan"},
        ],
    }
    merged = merge_glossary(base, incoming, prefer="base")
    assert merged["tone"] == "old"
    by_src = {t["source"]: t for t in merged["terms"]}
    assert by_src["結界"]["en"] == "ward"
    assert "pt-BR" not in by_src["結界"] or by_src["結界"].get("en") == "ward"
    assert by_src["高野山"]["keep"] == "Koyasan"


def test_suggest_glossary_mock_chat(tmp_path: Path) -> None:
    cues = [
        Cue(1, 0, 1000, "グラン天空の結界"),
        Cue(2, 1000, 2000, "グラン天空へ"),
    ]
    mock = {
        "tone": "documentary narration",
        "do_not_translate": ["GRAN_TENKU"],
        "terms": [
            {"source": "グラン天空", "keep": "GRAN TENKU"},
            {"source": "結界", "en": "barrier", "pt-BR": "barreira"},
        ],
    }
    with patch(
        "srtspeak.core.translate_glossary._call_glossary_chat",
        return_value=mock,
    ):
        out = suggest_glossary(
            cues,
            source_lang="ja",
            targets=["en", "pt-BR"],
            api_key="dummy",
        )
    assert out["tone"]
    assert any(t.get("source") == "グラン天空" for t in out["terms"])
    path = tmp_path / "glossary.json"
    save_glossary(path, out)
    assert path.is_file()
    assert "barrier" in path.read_text(encoding="utf-8")


def test_suggest_glossary_requires_api_key() -> None:
    with pytest.raises(GlossaryError, match="api_key"):
        suggest_glossary(
            [Cue(1, 0, 1000, "a")],
            source_lang="ja",
            targets=["en"],
            api_key="",
        )

def test_save_glossary_strips_meta_and_count(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    save_glossary(
        path,
        {
            "tone": "doc",
            "terms": [{"source": "結界", "en": "barrier", "count": 9}],
            "meta": {"model": "x"},
        },
    )
    raw = path.read_text(encoding="utf-8")
    assert "meta" not in raw
    assert "count" not in raw
    loaded = load_glossary(path)
    assert loaded["terms"][0]["en"] == "barrier"
    assert "count" not in loaded["terms"][0]


def test_save_glossary_dedupes_source(tmp_path: Path) -> None:
    path = tmp_path / "g.json"
    save_glossary(
        path,
        {
            "terms": [
                {"source": "A", "en": "1"},
                {"source": "A", "en": "2"},
            ]
        },
    )
    loaded = load_glossary(path)
    assert len(loaded["terms"]) == 1
    assert loaded["terms"][0]["en"] == "1"

def test_suggest_drops_terms_not_in_source() -> None:
    cues = [
        Cue(1, 0, 1000, "グラン天空の結界"),
        Cue(2, 1000, 2000, "グラン天空へ"),
    ]
    mock = {
        "terms": [
            {"source": "グラン天空", "keep": "GRAN TENKU"},
            {"source": "存在しない語", "en": "nope"},
        ]
    }
    with patch(
        "srtspeak.core.translate_glossary._call_glossary_chat",
        return_value=mock,
    ):
        out = suggest_glossary(
            cues,
            source_lang="ja",
            targets=["en"],
            api_key="dummy",
        )
    sources = {t["source"] for t in out["terms"]}
    assert "グラン天空" in sources
    assert "存在しない語" not in sources
    assert out["meta"]["dropped_not_in_source_count"] == 1


def test_suggest_glossary_emits_progress_stages() -> None:
    cues = [
        Cue(1, 0, 1000, "グラン天空の結界"),
        Cue(2, 1000, 2000, "グラン天空へ"),
    ]
    mock = {
        "terms": [
            {"source": "グラン天空", "keep": "GRAN TENKU"},
        ]
    }
    events: list = []

    def slow_chat(**_kwargs):  # type: ignore[no-untyped-def]
        import time

        time.sleep(0.35)
        return mock

    out = suggest_glossary(
        cues,
        source_lang="ja",
        targets=["en"],
        api_key="dummy",
        progress_cb=events.append,
        chat_fn=slow_chat,
        heartbeat_s=0.1,
    )
    assert out["terms"]
    assert events, "expected progress events"
    percents = [e.percent for e in events]
    messages = [e.message for e in events]
    stages = [e.stage for e in events]
    assert all(s == "glossary" for s in stages)
    assert percents[0] < percents[-1]
    assert percents[-1] == 100.0
    joined = " ".join(messages)
    assert "extract" in joined or "candidate" in joined.lower()
    assert "chat" in joined.lower() or "waiting" in joined.lower()
    assert "done" in messages[-1].lower() or percents[-1] == 100.0
    chat_related = [
        e
        for e in events
        if "chat" in (e.message or "").lower() or "wait" in (e.message or "").lower()
    ]
    assert len(chat_related) >= 2, messages
