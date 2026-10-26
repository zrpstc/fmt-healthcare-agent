import math

import numpy as np
import pytest

from wgs_agent.reporting.ordination import community_ordination, composition_summary, community_paragraph


def test_distances_use_union_and_normalize_each_profile():
    result = community_ordination({"target_only": 7}, {"b": {"b": 20}, "a": {"a": 100}}, ["b", "a"])
    assert result["status"] == "available"
    assert result["n_features"] == 3
    assert result["distance_summary"] == {"median": 1.0, "minimum": 1.0, "maximum": 1.0}
    assert len(result["points"]) == 3
    assert sum(p["is_sample"] for p in result["points"]) == 1
    points = np.array([[p["x"], p["y"]] for p in result["points"]])
    assert np.linalg.norm(points[0] - points[1]) == pytest.approx(1.0)
    assert sum(result["explained_variance"]) == pytest.approx(1.0)


def test_reference_order_and_abundance_scale_do_not_change_coordinates():
    matrix = {"a": {"x": 4, "y": 6}, "b": {"x": 8, "y": 2}, "c": {"z": 10}}
    first = community_ordination({"x": 3, "y": 7}, matrix, ["c", "b", "a"])
    second = community_ordination({"x": 30, "y": 70}, matrix, ["a", "b", "c"])
    assert first["points"] == second["points"]
    assert first["distance_summary"]["minimum"] == pytest.approx(0.1)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "bad"])
def test_invalid_abundance_fails_closed(bad):
    result = community_ordination({"a": bad}, {"a": {"a": 1}, "b": {"b": 1}}, ["a", "b"])
    assert result["status"] == "unavailable"
    assert result["points"] == []


def test_identical_communities_do_not_create_artificial_separation():
    result = community_ordination({"a": 1}, {"a": {"a": 2}, "b": {"a": 3}}, ["a", "b"])
    assert result["reason"] == "no_community_variation"
    assert result["points"] == []


def test_missing_or_duplicate_reference_is_rejected():
    for selected in [["a", "a"], ["a", "missing"], ["a"]]:
        assert community_ordination({"a": 1}, {"a": {"a": 1}}, selected)["status"] == "unavailable"


def test_lingoes_correction_matches_euclidean_reconstruction():
    rng = np.random.default_rng(190)
    values = rng.dirichlet(np.full(6, 0.3), 9)
    matrix = {str(i): dict(enumerate(row)) for i, row in enumerate(values[1:])}
    result = community_ordination(dict(enumerate(values[0])), matrix, list(matrix))
    assert result["status"] == "available"
    assert result["correction"] == "Lingoes"
    assert result["correction_constant"] > 0
    assert 0 < sum(result["explained_variance"]) <= 1 + 1e-12
    assert all(math.isfinite(p[axis]) for p in result["points"] for axis in ["x", "y"])


def test_descriptive_summary_does_not_assign_an_enterotype():
    doc = {"template_inputs": {"taxonomy": {"complete": True, "ranks": {"genus": [{"name": "Bacteroides", "abundance": 60}, {"name": "Prevotella", "abundance": 20}]}}}}
    summary = composition_summary(doc)
    assert "Bacteroides、Prevotella" in summary
    assert "未完成可靠肠型分类" in summary
    assert "2.2" in summary
    assert "暂不判断" in composition_summary({})
    doc["metadata"] = {"qc_status": "failed"}
    assert "Bacteroides" not in composition_summary(doc)


def test_unmatched_reference_is_reported_explicitly():
    payload = community_ordination({"x": 1}, {"a": {"y": 1}, "b": {"z": 1}}, ["a", "b"])
    doc = {"template_inputs": {"healthy_comparison": {"ordination": payload}}}
    assert "未按年龄、性别或国家" in community_paragraph(doc, interpretation=True)
    assert "2 个独立参考样本" in community_paragraph(doc)


def test_contract_keeps_one_community_location_plot():
    from wgs_agent.reporting.word_template import contract
    charts = [(ch["number"], b["sub"], spec) for ch in contract()["chapters"] for b in ch["blocks"] if b["type"] == "visuals" for spec in b["items"] if spec.get("kind") == "scatterChart"]
    assert [(ch, sub) for ch, sub, _ in charts] == [(2, 2)]
    assert not any(b["type"] in {"visuals", "table"} for b in contract()["chapters"][0]["blocks"] if b["sub"] == 3)
