from wgs_agent.tools.knowledge_tools import (
    _format_claim_results,
    claim_record_to_reference,
)
from wgs_agent.tools.report_maker import build_full_report
from wgs_agent.pipeline.pdf_builder import build_context


def _reference() -> dict[str, object]:
    return claim_record_to_reference(
        {
            "id": 343,
            "document_id": 4,
            "filename": "agora.pdf",
            "title": "A reconstruction of gut microbial metabolism",
            "authors": ["Author A", "Author B"],
            "journal": "Example Journal",
            "year": 2020,
            "doi": "10.0000/example",
            "subject_text": "AGORA",
            "subject_type": "Resource",
            "predicate": "HAS_ASSAY_CONDITION",
            "object_text": "773 gut microbes",
            "object_type": "Cohort",
            "evidence_text": "We generated AGORA for 773 gut microbes.",
            "confidence": 1.0,
        },
        base_url="http://10.181.8.92:8080",
        knowledge_base_id=7,
        query="AGORA gut microbes",
        retrieval_score=3,
    )


def test_claim_search_output_contains_machine_readable_reference() -> None:
    reference = _reference()
    output = _format_claim_results("AGORA", [reference])
    assert "---JSON---" in output
    assert "litkg:claim:343" in output
    assert "http://10.181.8.92:8080/documents/4/claims" in output


def test_legacy_report_renders_claim_provenance_and_evidence() -> None:
    report = build_full_report(
        sample_id="S001",
        species_data={"species_list": [{"species": "AGORA", "abundance": 1}]},
        compare_data={},
        enterotype_data={},
        pathway_data={},
        metabolite_data={},
        drug_data={},
        disease_data={},
        knowledge_data={"matched_docs": [_reference()], "pubmed_results": []},
        fmt_matching_data=None,
    )
    assert "litkg:claim:343" not in report
    assert "证据原句:" not in report
    assert "document:4" not in report
    assert "REST 来源" not in report
    assert "A reconstruction of gut microbial metabolism" in report
    assert "Author A, Author B" in report
    assert "Example Journal, 2020" in report
    assert "DOI: 10.0000/example" in report


def test_pdf_context_contains_litkg_claim_reference() -> None:
    context = build_context(
        "S001",
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {"matched_docs": [_reference()], "pubmed_results": []},
    )
    assert any("litkg:claim:343" in item for item in context["references"])
    assert any("document:4" in item for item in context["references"])
