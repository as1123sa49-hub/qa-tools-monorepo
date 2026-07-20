"""Unit tests for comboburst portal search normalization."""

from core.comboburst_lobby import (
    _expand_search_query_variants,
    _normalize_for_card_match,
    resolve_portal_search_queries,
)


def test_expand_search_apostrophe_variants():
    variants = _expand_search_query_variants("Pop N' Win")
    assert "Pop N' Win" in variants
    assert "Pop N Win" in variants
    assert any("'" in v or v == "Pop N Win" for v in variants)


def test_normalize_for_card_match_ignores_apostrophe_and_underscore():
    assert _normalize_for_card_match("Pop N' Win") == _normalize_for_card_match("PopNWin")
    assert _normalize_for_card_match("Royal_Riches") == _normalize_for_card_match("RoyalRiches")


def test_resolve_portal_search_queries_slot_id_first():
    queries = resolve_portal_search_queries(
        {
            "search_keyword": "Royal Riches",
            "portal_slot_id": "Slot033",
            "search_aliases": ["Royal_Riches"],
        }
    )
    assert queries[0] == "Slot033"
    assert "Royal_Riches" in queries
    assert "RoyalRiches" in queries


def test_resolve_portal_search_queries_includes_slot_id():
    queries = resolve_portal_search_queries(
        {
            "search_keyword": "Pop",
            "portal_slot_id": "Slot009",
            "search_aliases": ["Pop N' Win"],
        }
    )
    assert queries[0] == "Slot009"
    assert "Pop" in queries
