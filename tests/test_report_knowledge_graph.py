"""Report-topic relevance, source fidelity, retrieval and publication regression tests."""

import json
from pathlib import Path

import httpx
import pytest

from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.knowledge_graph import (
    MAX_EDGES,
    MAX_NODES,
    attach_subgraphs,
    build_topic_graph,
    enrich_document,
    relation_label,
)
from wgs_agent.tools.knowledge_tools import claim_record_to_reference


def claim(identifier=1, subject="Bifidobacterium longum", object="butyrate", **changes):
    row = {
        "id": identifier,
        "document_id": 4,
        "filename": "evidence.pdf",
        "subject_text": subject,
        "subject_type": "MicrobialTaxon",
        "subject_entity_id": 12,
        "object_text": object,
        "object_type": "Compound",
        "object_entity_id": 100 + identifier,
        "predicate": "CORRELATED_WITH",
        "evidence_text": f"{subject} was correlated with {object} in the study.",
        "confidence": 0.9,
    }
    row.update(changes)
    return row


def reference(row):
    return claim_record_to_reference(row, base_url="http://litkg.test", knowledge_base_id=25)


def document(claims=(), *, qc=None):
    return build_document(
        "TEST__001",
        {"species_list": [{"species": "Bifidobacterium longum", "abundance": 2, "unit": "%"}]},
        {},
        {},
        {},
        {},
        {},
        {},
        {"matched_docs": [reference(r) for r in claims]},
        context={"qc_status": qc},
    )


def topic(doc, id="key_taxa.bifidobacteria"):
    return next(t for s in doc["sections"] for t in s["topics"] if t["id"] == id)


def test_graph_contains_only_relevant_actual_claims_and_valid_endpoints():
    unrelated = claim(
        2,
        "Unrelated species",
        "unrelated condition",
        evidence_text="Bifidobacterium longum appears only in background prose.",
    )
    doc = document([claim(), unrelated])
    graph = topic(doc)["knowledge_subgraph"]
    assert [e["claim_id"] for e in graph["edges"]] == ["litkg:claim:1"]
    node_ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in graph["edges"])
    markdown = render_markdown(doc)
    assert "相关知识子图" in markdown
    assert "CORRELATED_WITH" not in markdown
    assert "证据原句与出处" not in markdown
    assert "分模块参考文献" in markdown


def test_graph_caps_and_deduplicates_claims_deterministically():
    doc = document([claim(i, object=f"metabolite {i}") for i in range(20)])
    row = topic(doc)
    row["allowed_narrative_ids"] = [f"K{i}" for i in range(1, 21)] + ["K1"]
    graph = build_topic_graph(doc, row)
    assert len(graph["edges"]) == MAX_EDGES
    assert len(graph["nodes"]) <= MAX_NODES
    assert len({e["claim_id"] for e in graph["edges"]}) == MAX_EDGES
    assert graph["truncated"]
    assert build_topic_graph(doc, row) == graph


def test_cited_claims_take_precedence_over_related_background():
    doc = document([claim(1), claim(2)])
    row = topic(doc)
    row["narrative_evidence_ids"] = ["S1", "K2"]
    attach_subgraphs(doc)
    assert [e["evidence_id"] for e in row["knowledge_subgraph"]["edges"]] == ["K2"]
    assert row["knowledge_subgraph"]["selection"] == "cited_claims"
    assert row["knowledge_subgraph"]["edges"][0]["cited_in_analysis"]


def test_missing_results_and_title_only_references_do_not_create_edges():
    doc = document([claim()])
    assert topic(doc, "nutrition.minerals")["knowledge_subgraph"]["status"] == "not_assessed"
    failed = document([claim()], qc="failed")
    assert all(
        not t["knowledge_subgraph"]["edges"] for s in failed["sections"] for t in s["topics"]
    )
    no_claim = document()
    row = topic(no_claim)
    no_claim["evidence"]["B1"] = {
        "kind": "literature",
        "title": "Bifidobacterium longum and butyrate",
    }
    row["allowed_narrative_ids"].append("B1")
    assert not build_topic_graph(no_claim, row)["edges"]
    assert "未匹配到可展示的知识图谱关系" in render_markdown(no_claim)


def test_entity_name_fragments_do_not_match_different_compounds_or_proteins():
    doc = build_document(
        "TEST",
        {},
        {},
        {},
        {},
        {"metabolites": [{"name": "丁酸 / butyrate（演示）", "value": 1}]},
        {},
        {},
        {
            "matched_docs": [
                reference(claim(1, "Imidazole propionate", "quantification")),
                reference(claim(2, "butyrate", "gut barrier")),
            ]
        },
    )
    row = topic(doc, "metabolites.scfa")
    row["allowed_narrative_ids"].extend(["K1", "K2"])
    assert [e["claim_id"] for e in build_topic_graph(doc, row)["edges"]] == ["litkg:claim:2"]
    protein = reference(claim(3, "programmed cell death protein 1", "cancer"))
    doc["evidence"]["K3"] = {**protein, "kind": "literature"}
    row = {
        "id": "nutrition.macro",
        "status": "available",
        "evidence_ids": [],
        "allowed_narrative_ids": ["K3"],
    }
    assert not build_topic_graph(doc, row)["edges"]


def test_negation_speculation_and_no_effect_are_visible():
    doc = document([claim(negated=True, speculative=True)])
    doc["evidence"]["K1"]["result_status"] = "not_significant"
    edge = build_topic_graph(doc, topic(doc))["edges"][0]
    assert edge["negated"] and edge["speculative"]
    assert all(word in relation_label(edge) for word in ("否定", "推测", "不显著"))
    assert "证据原句与出处" not in render_markdown(doc)


@pytest.fixture
def retrieval(monkeypatch):
    monkeypatch.setenv("WGS_CLAIM_API_URL", "http://litkg.test")
    monkeypatch.setenv("WGS_CLAIM_API_KNOWLEDGE_BASE_ID", "25")
    monkeypatch.setenv("WGS_REPORT_GRAPH_SCAN_LIMIT", "501")
    monkeypatch.setenv("WGS_CLAIM_API_TOKEN", "test-secret")
    monkeypatch.setenv("WGS_REPORT_GRAPH_RETRIEVAL_DISABLED", "0")


@pytest.mark.asyncio
async def test_retrieval_paginates_once_per_report_and_keeps_only_matching_claims(retrieval):
    doc = document()
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.path == "/knowledge-bases/25/claims"
        assert set(request.url.params) == {"limit", "offset"}
        assert request.headers["authorization"] == "Bearer test-secret"
        offset = int(request.url.params["offset"])
        return httpx.Response(
            200,
            json={
                "claims": [claim(i, "Unrelated species", "unrelated outcome") for i in range(500)]
                if offset == 0
                else [claim(501)],
                "total": 501,
            },
        )

    await enrich_document(doc, transport=httpx.MockTransport(handle))
    assert len(requests) == 2
    assert doc["audit"]["knowledge_graph_retrieval"]["scanned_claims"] == 501
    assert doc["audit"]["knowledge_graph_retrieval"]["added_claims"] == 1
    attach_subgraphs(doc)
    edge = topic(doc)["knowledge_subgraph"]["edges"][0]
    assert edge["claim_id"] == "litkg:claim:501"
    assert edge["source"] != edge["target"]
    assert len(doc["references"]["matched_docs"]) == 1
    assert "test-secret" not in json.dumps(doc)


@pytest.mark.asyncio
async def test_outage_preserves_bound_evidence(retrieval):
    doc = document([claim()])

    def handle(request):
        return httpx.Response(503)

    await enrich_document(doc, transport=httpx.MockTransport(handle))
    assert doc["audit"]["knowledge_graph_retrieval"]["status"] == "unavailable"
    assert topic(doc)["knowledge_subgraph"]["edges"]
    assert "HTTPStatusError" not in render_markdown(doc)


@pytest.mark.asyncio
async def test_scan_limit_is_audited_and_existing_claim_is_not_duplicated(retrieval, monkeypatch):
    monkeypatch.setenv("WGS_REPORT_GRAPH_SCAN_LIMIT", "1")
    doc = document([claim()])
    await enrich_document(
        doc,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"claims": [claim()], "total": 2})
        ),
    )
    audit = doc["audit"]["knowledge_graph_retrieval"]
    assert audit["scan_truncated"]
    assert audit["added_claims"] == 0
    assert len(doc["references"]["matched_docs"]) == 1


@pytest.mark.asyncio
async def test_malformed_service_payload_does_not_break_report(retrieval):
    doc = document([claim()])
    await enrich_document(
        doc,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"claims": ["invalid"]})),
    )
    assert doc["audit"]["knowledge_graph_retrieval"]["status"] == "unavailable"
    assert "相关知识子图" in render_markdown(doc)


@pytest.mark.asyncio
async def test_unconfigured_retrieval_makes_no_network_request(monkeypatch):
    monkeypatch.setenv("WGS_CLAIM_API_URL", "")
    doc = document([claim()])

    def unexpected(_):
        pytest.fail("network request without configuration")

    await enrich_document(doc, transport=httpx.MockTransport(unexpected))
    assert doc["audit"]["knowledge_graph_retrieval"]["status"] == "not_configured"


@pytest.fixture
def generator(monkeypatch):
    from wgs_agent.reporting import inputs
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool

    monkeypatch.setenv("WGS_REPORT_GRAPH_RETRIEVAL_DISABLED", "1")
    monkeypatch.setenv("WGS_REPORT_GRAPH_LLM_DISABLED", "1")
    monkeypatch.setattr(detailed_report, "resolve_report_model", lambda: None)
    monkeypatch.setattr(detailed_report, "load_gene_family_evidence", lambda _: {})
    monkeypatch.setattr(inputs, "load_existing_report_inputs", lambda _: {})
    return ReportGeneratorTool()


def analysis_file(tmp_path):
    target = tmp_path / "TEST__001_analysis.json"
    target.write_text(
        json.dumps(
            {
                "sample_id": "TEST__001",
                "species": {
                    "species_list": [
                        {"species": "Bifidobacterium longum", "abundance": 2, "unit": "%"}
                    ]
                },
                "knowledge": {"matched_docs": [reference(claim())]},
            }
        )
    )
    return target


@pytest.mark.asyncio
async def test_published_graph_is_shared_by_markdown_json_api_and_pdf(
    generator, tmp_path, monkeypatch
):
    result = await generator.invoke(
        {"sample_id": "TEST__001", "analysis_json_path": str(analysis_file(tmp_path))}
    )
    assert not result.is_error, result.content
    doc = json.loads((tmp_path / "TEST__001_report.json").read_text())
    graph = topic(doc)["knowledge_subgraph"]
    filename = graph["figure"]
    image = tmp_path / filename
    assert image.read_bytes().startswith(b"\x89PNG")
    assert image.stat().st_mode & 0o777 == 0o600
    markdown = (tmp_path / "TEST__001_health_report.md").read_text()
    assert f"]({filename})" in markdown
    assert render_markdown(doc) == markdown
    pdf = (tmp_path / "TEST__001_health_report.pdf").read_bytes()
    assert b"/Subtype /Image" in pdf  # Embeds a figure, not an unavailable-image caption.
    evidence = json.loads((tmp_path / "TEST__001_report_evidence.json").read_text())
    assert evidence["knowledge_subgraphs"][topic(doc)["id"]] == graph
    from app import main

    monkeypatch.setattr(main, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(main, "is_deleted", lambda _: False)
    assert Path(main.report_figure("TEST__001", filename).path) == image


@pytest.mark.asyncio
async def test_pdf_failure_does_not_publish_new_graphs(generator, tmp_path, monkeypatch):
    from wgs_agent.tools import report_maker

    old_report = tmp_path / "TEST__001_health_report.md"
    old_report.write_text("previous report")

    def fail(*_):
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(report_maker, "_generate_fpdf_report", fail)
    result = await generator.invoke(
        {"sample_id": "TEST__001", "analysis_json_path": str(analysis_file(tmp_path))}
    )
    assert result.is_error
    assert old_report.read_text() == "previous report"
    assert not list(tmp_path.glob("*.png"))
    assert not list(tmp_path.glob(".TEST__001-report-*"))
