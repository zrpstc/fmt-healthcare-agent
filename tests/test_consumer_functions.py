from __future__ import annotations

from wgs_agent.consumer_web.functions import (
    aggregate_category,
    fiber_union,
    taxonomy_fallback_contributors,
)


def _pathway(ident, name, contributors):
    return {
        "id": ident,
        "name": name,
        "kind": "pathway",
        "value": 0.1,
        "unit": "relative_abundance",
        "contributors": contributors,
    }


def test_butyrate_aggregates_all_pathways_not_one_representative():
    document = {
        "evidence": {
            "P1": _pathway("PWY-5676", "acetyl-CoA fermentation to butanoate II", [
                {"taxon": "g__Faecalibacterium.s__Faecalibacterium_prausnitzii", "abundance": 0.04, "unit": "relative_abundance"},
                {"taxon": "g__Escherichia.s__Escherichia_coli", "abundance": 0.06, "unit": "relative_abundance"},
            ]),
            "P2": _pathway("P163-PWY", "L-lysine fermentation to acetate and butanoate", [
                {"taxon": "g__Fusobacterium.s__Fusobacterium_nucleatum", "abundance": 0.1, "unit": "relative_abundance"},
            ]),
        }
    }
    result = aggregate_category(document, "丁酸合成")
    assert result["status"] == "available"
    assert result["pathway_ids"] == ["P163-PWY", "PWY-5676"]
    assert len(result["pathways"]) == 2
    names = {row["name"] for row in result["contributors"]}
    assert "Faecalibacterium prausnitzii" in names
    assert "Fusobacterium nucleatum" in names
    assert result["top_named_share"] < 100


def test_lactate_without_strata_can_use_taxonomy_fallback():
    document = {
        "template_inputs": {"taxonomy": {"ranks": {"species": [
            {"name": "Veillonella rogosae", "abundance": 24.8},
        ]}}},
        "evidence": {
            "P1": _pathway("PWY-8086", "(S)-lactate fermentation to propanoate, acetate and hydrogen", []),
        },
    }
    result = aggregate_category(document, "乳酸利用")
    assert result["pathway_ids"] == ["PWY-8086"]
    assert result["named_count"] == 0
    fallback = taxonomy_fallback_contributors(document, {"veillonella"})
    assert fallback[0]["name"] == "Veillonella rogosae"


def test_fiber_union_is_shared_by_diversity_and_nutrition():
    document = {
        "evidence": {
            "P1": _pathway("PWY-6731", "starch degradation III", [
                {"taxon": "g__Escherichia.s__Escherichia_coli", "abundance": 0.05, "unit": "relative_abundance"},
                {"taxon": "g__Faecalibacterium.s__Faecalibacterium_prausnitzii", "abundance": 0.05, "unit": "relative_abundance"},
            ]),
        }
    }
    union = fiber_union(document)
    assert union["named"]
    assert {row["name"] for row in union["named"]} == {"Escherichia coli", "Faecalibacterium prausnitzii"}
    assert union["backup"] in {"多种菌分担", "主要依赖少数菌"}
