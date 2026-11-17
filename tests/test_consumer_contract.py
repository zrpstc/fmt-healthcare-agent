from __future__ import annotations

import json
from pathlib import Path

from wgs_agent.consumer_web.schema import export_schema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs" / "consumer-web" / "consumer-report.schema.json"
TS = ROOT / "apps" / "workspace-web" / "lib" / "consumer-report.ts"


def test_python_schema_and_exported_schema_agree():
    assert SCHEMA.is_file()
    exported = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert exported == export_schema()


def test_typescript_contract_names_match_python_schema():
    text = TS.read_text(encoding="utf-8")
    schema = export_schema()
    for key in ("schema_version", "sample", "summary", "sections", "actions", "retest",
                "red_flags", "glossary", "references", "omissions", "methods", "downloads"):
        assert key in text
        assert key in schema["properties"]
    assert "from: string" in text
    assert "from" in schema["$defs"]["GraphEdge"]["properties"]
    assert "very_low" in text
    assert "very_low" in schema["$defs"]["Tier"]["properties"]["key"]["enum"]
