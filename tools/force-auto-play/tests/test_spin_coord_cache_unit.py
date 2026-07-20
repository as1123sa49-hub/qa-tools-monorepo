"""Unit tests for persistent spin coordinate cache."""

import json

import pytest

from core import spin_coord_cache


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "spin_coords.json"
    monkeypatch.setattr(spin_coord_cache, "DEFAULT_CACHE_PATH", cache_file)
    return cache_file


def test_save_and_load_spin_coord(isolated_cache):
    spin_coord_cache.save_spin_coord("CMB_COMBO_WildBuffalo", 1707.7, 750.4)
    loaded = spin_coord_cache.get_spin_coord("CMB_COMBO_WildBuffalo")
    assert loaded == (1707.7, 750.4)

    data = json.loads(isolated_cache.read_text(encoding="utf-8"))
    assert data["CMB_COMBO_WildBuffalo"] == {"x": 1707.7, "y": 750.4}


def test_get_spin_coord_missing_returns_none(isolated_cache):
    assert spin_coord_cache.get_spin_coord("unknown_game") is None
