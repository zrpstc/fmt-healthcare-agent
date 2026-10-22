from wgs_agent.tools.report_layers import build_report_layers


def test_three_report_layers_keep_user_and_audit_content_separate():
    evidence = {
        "S1": {"species": "Akkermansia muciniphila", "abundance": 1.2, "status": "normal"},
        "P1": {"name": "PWY-TEST", "abundance": 2.5, "unit": "relative_abundance"},
        "D1": {"disease": "示例关联", "risk_score": 33, "risk_level": "medium"},
        "F1": {"donor_id": "DONOR-1", "score": 0.8, "distance": 0.2},
    }
    layers = build_report_layers(
        sample_id="TEST",
        full_report="# 完整报告\n\n## 详细证据\n\n保留完整表格。\n",
        evidence=evidence,
        species_data={"species_list": [evidence["S1"]]},
        enterotype_data={"enterotype": "Bacteroides"},
        pathway_data={"pathways": [evidence["P1"]]},
        disease_data={"diseases": [evidence["D1"]]},
        matching_data={"status": "ok", "top_k_matches": [evidence["F1"]]},
        context={"analysis_sha256": "abc", "knowledge_sha256": "def", "report_version": "v2"},
    )
    assert "肠道宏基因组分析主报告" in layers["main_markdown"]
    assert "保留完整表格" not in layers["main_markdown"]
    assert "技术附录与审计记录" in layers["technical_markdown"]
    assert "保留完整表格" in layers["technical_markdown"]
    payload = layers["interactive"]
    assert payload["available_modules"] == ["species", "pathways", "diseases", "matching"]
    assert payload["charts"][0]["items"][0]["evidence_id"] == "S1"


def test_interactive_payload_omits_non_finite_values():
    layers = build_report_layers(
        sample_id="TEST",
        full_report="# 完整报告\n",
        evidence={"S1": {"species": "A", "abundance": float("nan")}},
        species_data={}, enterotype_data={}, pathway_data={}, disease_data={}, matching_data={}, context={},
    )
    assert layers["interactive"]["available_modules"] == []
    assert layers["interactive"]["charts"][0]["items"] == []
