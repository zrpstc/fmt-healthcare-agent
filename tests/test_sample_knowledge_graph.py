"""Sample-specific graph ranking and API fallbacks use synthetic data only."""

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.sample_graph import build_sample_graph


def claim(identifier=1, **changes):
    row = {"id": identifier, "document_id": 4, "subject_text": "Bifidobacterium longum",
           "subject_type": "MicrobialTaxon", "subject_entity_id": 12,
           "object_text": "butyrate", "object_type": "Metabolite", "object_entity_id": 15,
           "predicate": "CORRELATED_WITH", "evidence_text": "Observed association.",
           "confidence": .9, "negated": True, "speculative": True,
           "qualifiers": {"dose": "study-specific"}}
    return {**row, **changes}


def graph(claims=(), analysis=None, knowledge=None, report=None, limit=40):
    return build_sample_graph(analysis or {"species": {"species_list": [
        {"species": "Bifidobacterium longum", "abundance": 2, "status": "low"}]}},
        knowledge or {}, report or {}, list(claims), sample_id="S1", knowledge_base_id=25, limit=limit)


def test_only_endpoint_matches_create_actual_direct_edges():
    result = graph([claim(), claim(2, subject_text="Unrelated organism", object_text="Unrelated outcome",
        evidence_text="Bifidobacterium longum mentioned in background")])
    assert [edge["claim_id"] for edge in result["edges"]] == ["litkg:claim:1"]
    edge = result["edges"][0]
    assert edge["negated"] and edge["speculative"] and edge["qualifiers"] == {"dose": "study-specific"}
    assert edge["match_reasons"] == ["异常检测实体：Bifidobacterium longum"]
    assert {node["id"] for node in result["nodes"]} == {edge["source"], edge["target"]}
    assert result == graph([claim(), claim(2, subject_text="Unrelated organism", object_text="Unrelated outcome",
        evidence_text="Bifidobacterium longum mentioned in background")])


def test_bound_evidence_survives_outage_deduplicates_and_retains_remote_identity():
    bound = {"claim_id": "litkg:claim:1", "subject": "Bifidobacterium longum", "object": "butyrate",
             "predicate": "CORRELATED_WITH", "evidence_text": "Observed association."}
    result = graph([claim()], knowledge={"matched_docs": [bound, bound]})
    assert len(result["edges"]) == 1 and len(result["nodes"]) == 2
    assert result["edges"][0]["bound_to_sample"]
    assert graph([], knowledge={"matched_docs": [bound]})["edges"]


def test_no_background_title_sample_identifier_or_zero_measurement_match():
    analysis = {"sample_id": "Bifidobacterium longum", "notes": "Bifidobacterium longum",
                "species": {"species_list": [{"species": "Bifidobacterium longum", "abundance": 0}]},
                "knowledge": {"matched_docs": [{"title": "Bifidobacterium longum"}]}}
    assert not graph([claim()], analysis=analysis)["edges"]
    assert not graph([claim(subject_text="unrelated Bifidobacterium longum isolate")])["edges"]


def test_limits_candidates_confidence_and_scope_identity():
    result = graph([claim(i, object_entity_id=i + 100) for i in range(6)], limit=2)
    assert len(result["edges"]) == 2
    assert result["selection"]["candidate_count"] == 6 and result["selection"]["truncated"]
    assert graph([claim(confidence="NaN")])["edges"][0]["confidence"] == 0
    other = claim(1, knowledge_base_id=99)
    assert len(graph([claim(), other])["edges"]) == 2
    assert len(graph([claim(), other])["nodes"]) == 4


def test_abnormal_entity_precedes_healthy_entity_and_cited_bound_comes_first():
    analysis = {"species": {"species_list": [{"species": "Bifidobacterium longum", "abundance": 2, "status": "low"},
                   {"species": "Other organism", "abundance": 2, "status": "normal"}]}}
    result = graph([claim(2, subject_text="Other organism", confidence=1), claim(confidence=.1)], analysis=analysis)
    assert [e["claim_id"] for e in result["edges"]] == ["litkg:claim:1", "litkg:claim:2"]


@pytest.mark.parametrize("field", ["status", "comparison"])
@pytest.mark.parametrize("container_type", [list, dict], ids=["list", "dict"])
def test_nested_comparison_containers_preserve_abnormal_features(field, container_type):
    row = {"species": "Bifidobacterium longum", "abundance": 2, "comparison": "below"}
    container = [row] if container_type is list else {"rows": [row]}
    analysis = {
        "compare": {field: container},
        "species": {"species_list": [
            {"species": "Other organism", "abundance": 2, "status": "normal"},
        ]},
    }
    result = graph(
        [claim(2, subject_text="Other organism", confidence=1), claim(confidence=.1)],
        analysis=analysis,
    )
    assert [edge["claim_id"] for edge in result["edges"]] == [
        "litkg:claim:1", "litkg:claim:2",
    ]
    assert result["edges"][0]["match_reasons"] == [
        "异常检测实体：Bifidobacterium longum",
    ]
    assert result["edges"][1]["match_reasons"] == ["检测实体：Other organism"]


def test_detected_entity_precedes_generic_saved_evidence_and_parenthetical_prose():
    saved = {"claim_id": "litkg:claim:9", "subject": "unrelated organism", "object": "unrelated pathway",
             "predicate": "ASSOCIATED_WITH", "evidence_text": "Saved background."}
    result = graph([claim()], knowledge={"matched_docs": [saved]})
    assert [e["claim_id"] for e in result["edges"]] == ["litkg:claim:1", "litkg:claim:9"]
    assert not graph([claim(subject_text="anaerobic process")], analysis={
        "pathways": {"pathways": [{"name": "unrelated pathway (anaerobic)", "abundance": 1}]}})["edges"]


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(main, "is_deleted", lambda _: False)
    (tmp_path / "S1_analysis.json").write_text(json.dumps({"species": {"species_list": [
        {"species": "Bifidobacterium longum", "abundance": 1}]}}))
    return tmp_path


def test_api_paginates_past_first_page_and_reports_scan_status(runtime, monkeypatch):
    calls = []
    async def upstream(path, params):
        calls.append(params)
        if params["offset"] == 0:
            return {"claims": [claim(i, subject_text="irrelevant", object_text="other") for i in range(500)], "total": 501}
        return {"claims": [claim(900)], "total": 501}
    monkeypatch.setattr(main, "_litkg_get", upstream)
    with TestClient(main.app) as client:
        response = client.get("/api/knowledge/samples/S1/graph?limit=20")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["edges"][0]["claim_id"] == "litkg:claim:900"
        assert result["retrieval"]["scanned_claims"] == 501
        assert not result["retrieval"]["scan_truncated"]
        assert calls[1]["offset"] == 500
        assert client.get("/api/knowledge/samples/S1/graph?limit=151").status_code == 422
        assert client.get("/api/knowledge/samples/MISSING/graph").status_code == 404


def test_api_extracts_graph_from_nested_comparison_rows(runtime, monkeypatch):
    analysis = {"compare": {"comparison": [
        {"species": "Bifidobacterium longum", "abundance": 1, "comparison": "above"},
    ]}}
    (runtime / "S1_analysis.json").write_text(json.dumps(analysis))

    async def upstream(path, params):
        return {"claims": [claim()], "total": 1}

    monkeypatch.setattr(main, "_litkg_get", upstream)
    with TestClient(main.app) as client:
        response = client.get("/api/knowledge/samples/S1/graph?limit=20")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["summary"]["relation_count"] == 1
    assert result["edges"][0]["match_reasons"] == [
        "异常检测实体：Bifidobacterium longum",
    ]
    assert result["retrieval"]["status"] == "complete"


def test_api_outage_uses_saved_claims_and_deleted_sample_rejected(runtime, monkeypatch):
    saved = {"claim_id": "litkg:claim:1", "subject": "Bifidobacterium longum", "object": "butyrate",
             "predicate": "CORRELATED_WITH", "evidence_text": "Saved evidence."}
    (runtime / "S1_knowledge.json").write_text(json.dumps({"matched_docs": [saved]}))
    async def unavailable(*args):
        raise HTTPException(502, "Unavailable")
    monkeypatch.setattr(main, "_litkg_get", unavailable)
    with TestClient(main.app) as client:
        result = client.get("/api/knowledge/samples/S1/graph").json()
        assert result["edges"] and result["retrieval"]["status"] == "unavailable"
        assert result["retrieval"]["message"]
        monkeypatch.setattr(main, "is_deleted", lambda _: True)
        assert client.get("/api/knowledge/samples/S1/graph").status_code == 410
