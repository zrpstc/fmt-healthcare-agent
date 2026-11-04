import copy
import math

import pytest

from wgs_agent.pipeline.disease_features import analyze_disease_features, merge_disease_features


def taxonomy(rows=None):
    return {"complete": True, "unit": "%", "pipeline": {"profiler": "MetaPhlAn", "database_version": "Jan25"},
            "ranks": {"species": rows or [{"name": "Faecalibacterium prausnitzii", "abundance": 2.0}]}}


def test_annotation_uses_observed_values_and_keeps_missing_unquantified():
    module = analyze_disease_features(taxonomy())
    assert module["status"] == "completed"
    assert module["model_assessment"]["status"] == "not_enabled"
    cd = next(r for r in module["diseases"] if r["id"] == "crohns_disease")
    assert cd["matched_species"] == 1
    found, missing = cd["details"][:2]
    assert found["abundance"] == 2 and found["status"] == "reported"
    assert missing["abundance"] is None and missing["status"] == "not_reported"
    assert "risk_score" not in cd
    assert cd["references"][0]["doi"] == "10.1038/s41586-019-1237-9"


@pytest.mark.parametrize("value", [None, math.nan, math.inf, -1, 101, True, "invalid"])
def test_invalid_profile_values_never_become_disease_features(value):
    result = analyze_disease_features(taxonomy([{"name": "Escherichia coli", "abundance": value}]))
    assert result["status"] == "not_assessed" and not result["diseases"]


def test_incomplete_profiles_units_and_ambiguous_taxa_are_rejected():
    profile = taxonomy()
    for mutation in ({"complete": False}, {"unit": "CPM"}):
        assert analyze_disease_features({**profile, **mutation})["status"] == "not_assessed"
    profile["ranks"]["species"] *= 2
    assert analyze_disease_features(profile)["reason_code"] == "INVALID_OR_AMBIGUOUS_TAXONOMY"


def test_lineage_names_match_exact_species_without_substring_matching():
    module = analyze_disease_features(taxonomy([{"name": "k__Bacteria|s__Escherichia_coli", "abundance": 0.0}]))
    cd = module["diseases"][1]
    assert cd["details"][2]["abundance"] == 0
    module = analyze_disease_features(taxonomy([{"name": "Escherichia coli like", "abundance": 2}]))
    assert module["diseases"][1]["matched_species"] == 0


def test_manual_results_are_preserved_and_generated_results_refresh():
    previous = {"diseases": {"diseases": [{"disease": "manual"}]}, "unrelated": 42}
    before = copy.deepcopy(previous)
    generated = analyze_disease_features(taxonomy())
    assert merge_disease_features(generated, previous)["diseases"] == previous["diseases"]
    assert previous == before
    assert merge_disease_features(generated, {"diseases": generated})["diseases"] == generated


def test_missing_or_malformed_references_return_explicit_status(tmp_path):
    path = tmp_path / "missing.json"
    result = analyze_disease_features(taxonomy(), catalog_path=path)
    assert result["reason_code"] == "DISEASE_REFERENCE_UNAVAILABLE"
    path.write_text("invalid json")
    result = analyze_disease_features(taxonomy(), catalog_path=path)
    assert result["reason_code"] == "DISEASE_REFERENCE_INVALID"


def test_missing_taxonomy_does_not_add_a_placeholder_to_existing_rich_analysis():
    data = {"custom": "preserve exactly"}
    assert merge_disease_features(analyze_disease_features(None), data) == {}
    assert data == {"custom": "preserve exactly"}


def test_malformed_taxonomy_ranks_fail_closed():
    result = analyze_disease_features({"complete": True, "unit": "%", "ranks": None})
    assert result["reason_code"] == "INVALID_TAXONOMY"
