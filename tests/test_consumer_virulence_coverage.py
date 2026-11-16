from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.sections.panel import watch_species
from wgs_agent.consumer_web.sections.context import Context
from wgs_agent.consumer_web.glossary import GlossaryService
from wgs_agent.consumer_web.names import NameRegistry
from wgs_agent.consumer_web.graph import GraphBuilder, ReferenceIndex


FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"


def test_every_watch_taxon_has_a_virulence_source_conclusion(monkeypatch):
    monkeypatch.setattr(
        "wgs_agent.consumer_web.sections.virulence.load_vfdb_index",
        lambda: {
            "VFG002287": {"symbol": "toxA", "vf_name": "TcdA", "vf_category": "Exotoxin", "host": "Clostridium difficile 630"},
        },
    )
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        shutil.copyfile(FIXTURES / "sample_report.json", tmp / "CONSUMER_TEST_report.json")
        shutil.copyfile(FIXTURES / "sample_analysis.json", tmp / "CONSUMER_TEST_analysis.json")
        report = build_report("CONSUMER_TEST", results_dir=tmp, refresh=True)
        document = json.loads((tmp / "CONSUMER_TEST_report.json").read_text(encoding="utf-8"))
        ctx = Context(document, {}, GlossaryService(), NameRegistry(document), ReferenceIndex(document), GraphBuilder(document, ReferenceIndex(document)))
        watch = watch_species(ctx)
        source_rows = []
        for section in report["sections"]:
            if section["id"] != "virulence":
                continue
            for subsection in section["subsections"]:
                if subsection["id"] != "virulence-source":
                    continue
                for block in subsection["blocks"]:
                    if block["type"] == "table":
                        source_rows.extend(str(cell) for row in block["rows"] for cell in row)
        for row in watch:
            name = ctx.names.plain(row["name"])
            assert any(name in cell for cell in source_rows), name
