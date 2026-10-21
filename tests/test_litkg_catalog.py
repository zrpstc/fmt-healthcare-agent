import pytest

from wgs_fmt_platform.knowledge.litkg_catalog import (
    normalize_knowledge_bases,
    parse_knowledge_base_ids,
    select_knowledge_bases,
)


def test_parse_knowledge_base_ids_supports_auto_and_csv() -> None:
    assert parse_knowledge_base_ids("auto") == []
    assert parse_knowledge_base_ids("25, 7,25,invalid,0") == [25, 7]


def test_normalize_knowledge_base_catalog() -> None:
    rows = normalize_knowledge_bases({
        "knowledge_bases": [
            {"id": 25, "name": "FMT evidence", "document_count": 17},
            {"id": "26", "slug": "metabolic"},
            {"name": "invalid"},
        ]
    })
    assert [row["id"] for row in rows] == [25, 26]
    assert rows[1]["name"] == "metabolic"


def test_auto_selects_all_and_stale_config_falls_back_to_all() -> None:
    available = [{"id": 25, "name": "FMT"}, {"id": 26, "name": "IBD"}]
    assert select_knowledge_bases(available, configured_ids="auto") == available
    assert select_knowledge_bases(available, configured_ids="7") == available


def test_requested_selection_is_strict() -> None:
    available = [{"id": 25, "name": "FMT"}, {"id": 26, "name": "IBD"}]
    assert select_knowledge_bases(available, requested_ids="26") == [available[1]]
    assert select_knowledge_bases(available, requested_ids="7") == []


def test_catalog_requires_expected_shape() -> None:
    with pytest.raises(ValueError, match="knowledge_bases"):
        normalize_knowledge_bases({"items": []})
