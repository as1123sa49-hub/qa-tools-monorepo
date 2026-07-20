"""Unit tests for JC search provider-chip matching (second row)."""

from core.game_utils import (
    ocr_text_matches_provider_chip,
    provider_chip_aliases,
)


def test_provider_chip_aliases_fc_includes_fa_chai():
    aliases = provider_chip_aliases("FC")
    assert "fa chai" in aliases
    assert "fc" in aliases


def test_provider_chip_aliases_jdb():
    assert "jdb" in provider_chip_aliases("JDB")


def test_ocr_matches_fa_chai_variants():
    aliases = provider_chip_aliases("FC")
    assert ocr_text_matches_provider_chip("FA CHAI", aliases)
    assert ocr_text_matches_provider_chip("fC", aliases)
    assert ocr_text_matches_provider_chip("Fa Chai", aliases)


def test_ocr_rejects_type_tabs_and_other_providers():
    aliases = provider_chip_aliases("FC")
    assert not ocr_text_matches_provider_chip("Feature", aliases)
    assert not ocr_text_matches_provider_chip("Slot", aliases)
    assert not ocr_text_matches_provider_chip("JDB", aliases)
    assert not ocr_text_matches_provider_chip("JILI", aliases)


def test_ocr_matches_jdb_not_fc():
    aliases = provider_chip_aliases("JDB")
    assert ocr_text_matches_provider_chip("jDB", aliases)
    assert not ocr_text_matches_provider_chip("FA CHAI", aliases)
