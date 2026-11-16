"""Glossary resolution, drafting queue and review behaviour for the consumer report."""

from __future__ import annotations

import json
import secrets
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.consumer_api as consumer_api
from wgs_agent.consumer_web import glossary_candidates
from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.glossary import GlossaryService, taxon_term_id
from wgs_fmt_platform.infrastructure.database import (
    ConsumerGlossaryCandidate,
    ConsumerGlossaryReview,
    SessionLocal,
    create_schema,
)
from test_consumer_api import _user_with_token

FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"


def _service(**kwargs) -> GlossaryService:
    kwargs.setdefault("candidates", [])
    kwargs.setdefault("reviews", [])
    return GlossaryService(**kwargs)


# ------------------------------------------------------------- resolution
def test_species_text_is_resolved_by_latin_name_and_alias():
    service = _service()
    assert service.taxon_term("Faecalibacterium prausnitzii") == "faecalibacterium_prausnitzii"
    assert service.taxon_term("s__Faecalibacterium_prausnitzii") == "faecalibacterium_prausnitzii"
    assert service.taxon_term("Clostridium difficile") == "clostridioides_difficile"
    # A different species of a curated genus must not inherit another species' text.
    assert service.taxon_term("Bifidobacterium longum") is None
    assert service.genus_term("Escherichia albertii") == "genus_escherichia"


def test_curated_drafts_are_pending_until_reviewed():
    service = _service()
    assert service.status("faecalibacterium_prausnitzii") == "pending"
    assert not service.is_publishable("faecalibacterium_prausnitzii")
    reviewed = _service(reviews=[{
        "term_id": "faecalibacterium_prausnitzii", "field": "one_liner", "status": "approved", "text": "审核后的解释。",
    }])
    assert reviewed.is_publishable("faecalibacterium_prausnitzii")
    assert reviewed.one_liner("faecalibacterium_prausnitzii") == "审核后的解释。"
    # Approval of one field does not approve the other.
    assert not reviewed.is_publishable("escherichia_coli", "watch_note")


def test_rejected_rows_do_not_return_to_the_queue():
    reviews = [{"term_id": "escherichia_coli", "field": "watch_note", "status": "rejected", "text": ""}]
    service = _service(reviews=reviews)
    queue = {(row["term_id"], row["field"]) for row in service.review_queue()}
    assert ("escherichia_coli", "watch_note") not in queue
    assert ("escherichia_coli", "one_liner") in queue
    with_rejected = {(row["term_id"], row["field"]) for row in service.review_queue(include_rejected=True)}
    assert ("escherichia_coli", "watch_note") in with_rejected


def test_candidates_merge_without_overriding_curated_text():
    term = taxon_term_id("Bifidobacterium longum")
    service = _service(candidates=[
        {"term_id": term, "field": "one_liner", "kind": "species", "display_name": "长双歧杆菌",
         "latin": "Bifidobacterium longum", "text": "", "evidence": [{"id": "E1", "sentence": "x"}]},
        {"term_id": "faecalibacterium_prausnitzii", "field": "one_liner", "text": "机器草稿"},
    ])
    assert service.taxon_term("Bifidobacterium longum") == term
    row = next(row for row in service.review_queue() if row["term_id"] == term)
    assert row["needs_writing"] is True and row["evidence"]
    assert service.field_text("faecalibacterium_prausnitzii") != "机器草稿"


# -------------------------------------------------------------- builder
def _install(tmp: Path, sample: str, extra_species: list[tuple[str, float]]) -> None:
    document = json.loads((FIXTURES / "sample_report.json").read_text(encoding="utf-8"))
    species = document["template_inputs"]["taxonomy"]["ranks"]["species"]
    for name, value in extra_species:
        species.append({**species[0], "name": name, "abundance": value})
    (tmp / f"{sample}_report.json").write_text(json.dumps(document), encoding="utf-8")
    shutil.copyfile(FIXTURES / "sample_analysis.json", tmp / f"{sample}_analysis.json")


def test_build_records_needs_and_never_borrows_another_species_text(tmp_path):
    _install(tmp_path, "GLOSS_FX", [("Bifidobacterium longum", 2.0), ("Blautia obeum", 3.0)])
    report = build_report("GLOSS_FX", results_dir=tmp_path, refresh=True, allow_pending=True)
    needs = json.loads((tmp_path / "GLOSS_FX_consumer_glossary_needs.json").read_text(encoding="utf-8"))["needs"]
    latins = {row["latin"] for row in needs}
    assert {"Bifidobacterium longum", "Blautia obeum"} <= latins
    texts = {}
    for section in report["sections"]:
        for sub in section["subsections"]:
            for block in sub["blocks"]:
                for card in block.get("cards") or []:
                    if isinstance(card, dict) and block["type"] == "category_cards":
                        for member in card.get("members") or []:
                            texts[member["name"]] = member.get("text")
    assert "长双歧杆菌" in texts
    assert texts["长双歧杆菌"] is None  # never the curated Bifidobacterium adolescentis text


def test_public_build_hides_pending_species_text(tmp_path):
    _install(tmp_path, "GLOSS_PUB", [])
    report = build_report("GLOSS_PUB", results_dir=tmp_path, refresh=True, allow_pending=False)
    payload = json.dumps(report, ensure_ascii=False)
    assert "健康成人肠道中最常见的产丁酸菌之一" not in payload


# ---------------------------------------------------------------- drafting
def _fake_post(text: str, scope: str = "species", ids: list[str] | None = None):
    class Response:
        status_code = 200
        text_body = ""

        def raise_for_status(self):
            return None

        def json(self):
            content = json.dumps({"text": text, "evidence_scope": scope, "source_ids": ids or ["E1"]}, ensure_ascii=False)
            return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}

    def post(url, headers=None, json=None, timeout=None):
        return Response()

    return post


EVIDENCE = [{"id": "E1", "scope": "species", "sentence": "B. longum ferments plant oligosaccharides.", "source": "litkg"}]
NEED = {"latin": "Bifidobacterium longum", "display_name": "长双歧杆菌"}
CONFIG = {"model": "fake", "base_url": "http://model.invalid", "api_key": "x", "response_format": "none"}


def test_draft_text_accepts_a_valid_cited_sentence():
    text, scope, cited, status = glossary_candidates.draft_text(
        NEED, "one_liner", EVIDENCE, CONFIG, _fake_post("常见的双歧杆菌，能分解植物来源的寡糖。"))
    assert status == "drafted" and text and cited == ["E1"] and scope == "species"


@pytest.mark.parametrize("text,scope,expected", [
    ("一种有益菌，能治疗腹泻。", "species", "rejected_forbidden_wording"),
    ("能分解植物来源的寡糖。", "genus", "rejected_genus_scope_unmarked"),
    ("能分解植物来源的寡糖，这一句子故意写得非常非常非常非常非常非常非常长以超过四十个汉字的限制。", "species", "rejected_too_long"),
])
def test_draft_text_rejects_unsafe_or_unscoped_output(text, scope, expected):
    result = glossary_candidates.draft_text(NEED, "one_liner", EVIDENCE, CONFIG, _fake_post(text, scope))
    assert result[3] == expected and result[0] == ""


def test_draft_text_without_model_or_evidence_queues_for_manual_writing():
    assert glossary_candidates.draft_text(NEED, "one_liner", EVIDENCE, None)[3] == "no_model"
    assert glossary_candidates.draft_text(NEED, "one_liner", [], CONFIG)[3] == "no_evidence"


# ------------------------------------------------------------------- API
@pytest.fixture
def client():
    create_schema()
    with TestClient(app) as test_client:
        yield test_client


def _cleanup(term_ids: list[str]) -> None:
    with SessionLocal() as session:
        session.query(ConsumerGlossaryCandidate).filter(ConsumerGlossaryCandidate.term_id.in_(term_ids)).delete()
        session.query(ConsumerGlossaryReview).filter(ConsumerGlossaryReview.term_id.in_(term_ids)).delete()
        session.commit()


def test_generate_endpoint_queues_pending_candidates_and_review_flow(client, tmp_path, monkeypatch):
    sample = "GLOSS_API_" + secrets.token_hex(3)
    _install(tmp_path, sample, [("Bifidobacterium longum", 2.0)])
    monkeypatch.setattr(consumer_api, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(consumer_api, "_alias", lambda sid: "样本 TEST")
    monkeypatch.setattr(consumer_api, "_report_for",
                        lambda sid, refresh=False, allow_pending=None: build_report(sid, results_dir=tmp_path, refresh=refresh))
    real_generate = glossary_candidates.generate_for_sample
    monkeypatch.setattr(consumer_api, "generate_for_sample",
                        lambda sid, **kw: real_generate(sid, **{**kw, "config": None, "use_llm": False}))
    term = taxon_term_id("Bifidobacterium longum")
    _cleanup([term])
    try:
        viewer, _ = _user_with_token("viewer")
        denied = client.post("/api/consumer/glossary/generate", json={"sample_id": sample},
                             headers={"Authorization": f"Bearer {viewer}"})
        assert denied.status_code == 403

        researcher, _ = _user_with_token("researcher")
        headers = {"Authorization": f"Bearer {researcher}"}
        generated = client.post("/api/consumer/glossary/generate", json={"sample_id": sample, "use_llm": False},
                                headers=headers)
        assert generated.status_code == 200, generated.text
        assert generated.json()["processed"] >= 1

        queue = client.get("/api/consumer/glossary/review", headers=headers).json()["entries"]
        row = next(item for item in queue if item["term_id"] == term)
        assert row["needs_writing"] is True
        assert sample in row["samples_used"]

        empty = client.post(f"/api/consumer/glossary/review/{term}",
                            json={"field": "one_liner", "status": "approved", "text": "  "}, headers=headers)
        assert empty.status_code == 422

        rejected = client.post(f"/api/consumer/glossary/review/{term}",
                               json={"field": "one_liner", "status": "rejected", "text": ""}, headers=headers)
        assert rejected.status_code == 200
        queue = client.get("/api/consumer/glossary/review", headers=headers).json()["entries"]
        assert all(item["term_id"] != term for item in queue)

        approved = client.post(f"/api/consumer/glossary/review/{term}",
                               json={"field": "one_liner", "status": "approved", "text": "成人肠道常见的双歧杆菌。"},
                               headers=headers)
        assert approved.status_code == 200
        report = build_report(sample, results_dir=tmp_path, allow_pending=False)
        assert "成人肠道常见的双歧杆菌。" in json.dumps(report, ensure_ascii=False)
    finally:
        _cleanup([term])
