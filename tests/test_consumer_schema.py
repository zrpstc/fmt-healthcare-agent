from __future__ import annotations

from wgs_agent.consumer_web.schema import ConsumerReport, export_schema


def test_contract_version_and_graph_from_alias():
    schema = export_schema()
    assert schema["properties"]["schema_version"]["const"] == "consumer-report/1"
    dump = ConsumerReport(
        sample={
            "sample_id": "ALIAS",
            "alias": "ALIAS",
            "report_date": "2026-11-16",
            "generated_at": "2026-11-16T00:00:00Z",
            "source_report_sha256": "a" * 64,
            "builder_version": "consumer-web-builder-v1",
        },
        summary={"headline": "测试", "headline_source": "rule", "status_cards": [], "key_findings": []},
    ).model_dump(by_alias=True)
    assert dump["schema_version"] == "consumer-report/1"
    assert dump["sample"]["alias"] == "ALIAS"
    assert dump["sections"] == []
    assert dump["references"] == []
