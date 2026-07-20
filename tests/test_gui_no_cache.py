"""GUI no_cache wiring (source contract; no Qt display required)."""

from __future__ import annotations

from pathlib import Path

import pytest

APP_PY = Path(__file__).resolve().parents[1] / "src" / "srtspeak" / "gui" / "app.py"


@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_PY.read_text(encoding="utf-8")


def test_build_tab_has_no_cache_checkbox(app_src: str) -> None:
    assert "self.no_cache_cb" in app_src
    assert "no_cache_cb = QCheckBox" in app_src


def test_translate_tab_has_no_cache_checkbox(app_src: str) -> None:
    assert "self.tr_no_cache_cb" in app_src
    assert "tr_no_cache_cb = QCheckBox" in app_src


def test_settings_load_no_cache(app_src: str) -> None:
    assert 's["no_cache"]' in app_src or "s.get(\"no_cache\"" in app_src
    assert 's["tr_no_cache"]' in app_src or "s.get(\"tr_no_cache\"" in app_src


def test_settings_save_no_cache(app_src: str) -> None:
    assert '"no_cache": self.no_cache_cb.isChecked()' in app_src
    assert '"tr_no_cache": self.tr_no_cache_cb.isChecked()' in app_src


def test_build_config_passes_no_cache(app_src: str) -> None:
    assert "no_cache=self.no_cache_cb.isChecked()" in app_src


def test_translate_config_passes_no_cache(app_src: str) -> None:
    assert "no_cache=self.tr_no_cache_cb.isChecked()" in app_src
