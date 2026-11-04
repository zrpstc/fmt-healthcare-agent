"""Regression coverage for the installed serializer and actual report renderer."""
from __future__ import annotations

import bz2
import json
import pickle
from pathlib import Path
import subprocess
import tempfile
import unittest

from wgs_agent.pipeline.strain_virulence import AnalysisError, summarize_consensus
from wgs_agent.reporting.chapter_four import status_message
from wgs_agent.reporting.document import build_document, render_markdown


class ChapterFourLiveContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chapter4-contract-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.metadata = self.root / "markers_db.pkl"
        with bz2.open(self.metadata, "wb") as handle:
            pickle.dump({"markers": {"m1": {"clade": "t__SGB1"}},
                         "taxonomy": {"k__Bacteria|s__Example_species|t__SGB1": ()}}, handle)

    def consensus(self, marker):
        path = self.root / "synthetic.json.bz2"
        with bz2.open(path, "wt") as handle:
            json.dump({"database_name": "markers_db", "consensus_markers": [marker]}, handle)
        return path

    def test_current_marker_field_is_accepted(self):
        path = self.consensus({"marker": "m1", "sequence": "ACGT" * 30,
                               "breadth": 100.0, "avg_depth": 5.0})
        result = summarize_consensus(path, self.metadata, min_markers=1)
        self.assertEqual(len(result["strains"]), 1)

    def test_legacy_name_field_remains_supported(self):
        path = self.consensus({"name": "m1", "sequence": "ACGT" * 30})
        self.assertEqual(len(summarize_consensus(path, self.metadata, min_markers=1)["strains"]), 1)

    def test_conflicting_marker_identifiers_are_rejected(self):
        path = self.consensus({"marker": "different", "name": "m1", "sequence": "ACGT" * 30})
        with self.assertRaises(AnalysisError):
            summarize_consensus(path, self.metadata, min_markers=1)

    def test_installed_serializer_roundtrip(self):
        project = Path(__file__).resolve()
        while project != project.parent and not (project / "src/wgs_agent").is_dir():
            project = project.parent
        python = project / "var/runtime/envs/fmt-tax/bin/python"
        if not python.is_file():
            self.skipTest("Installed MetaPhlAn environment is unavailable")
        path = self.root / "installed.json.bz2"
        program = ("import sys; from metaphlan.utils.consensus_markers import ConsensusMarker, ConsensusMarkers; "
                   "ConsensusMarkers([ConsensusMarker('m1','ACGT'*30)],'markers_db').to_json(sys.argv[1])")
        result = subprocess.run([str(python), "-c", program, str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=30, check=False)
        self.assertEqual(result.returncode, 0, "Installed scientific serializer failed")
        self.assertEqual(len(summarize_consensus(path, self.metadata, min_markers=1)["strains"]), 1)

    def document(self, strains=None, virulence=None, qc=None):
        modules = {"strains": strains or {"status": "not_run", "strains": []},
                   "virulence": virulence or {"status": "not_run", "markers": []}}
        context = {"health_inputs": modules}
        if qc:
            context["qc_status"] = qc
        return build_document("chapter4_synthetic", {}, {}, {}, {}, {}, {}, {}, {}, context=context)

    def test_actual_markdown_shows_failure_and_completed_zero_hits(self):
        strains = {"status": "failed", "reason_code": "INVALID_CONSENSUS_MARKER", "strains": []}
        virulence = {"status": "completed", "markers": [], "summary": {"processed_reads": 162854}}
        doc = self.document(strains, virulence)
        markdown = render_markdown(doc)
        self.assertIn(status_message(strains, "strains"), markdown)
        self.assertIn(status_message(virulence, "virulence"), markdown)
        self.assertIn("162,854", markdown)
        self.assertIn("达标标记 0 项", markdown)
        self.assertIn("图 4-1 暂无法绘制", markdown)

    def test_actual_markdown_distinguishes_unavailable_states(self):
        for state in ("not_run", "running", "missing_input", "missing_database", "missing_tool",
                      "insufficient_coverage", "failed", "invalid_result"):
            with self.subTest(state=state):
                strains = {"status": state, "strains": []}
                virulence = {"status": state, "markers": []}
                markdown = render_markdown(self.document(strains, virulence))
                self.assertIn(status_message(strains, "strains"), markdown)
                self.assertIn(status_message(virulence, "virulence"), markdown)
                self.assertNotIn("达标标记 0 项", markdown)

    def test_failed_qc_does_not_report_screening_negative(self):
        virulence = {"status": "completed", "markers": [], "summary": {"processed_reads": 12}}
        markdown = render_markdown(self.document(virulence=virulence, qc="failed"))
        self.assertNotIn(status_message(virulence, "virulence"), markdown)
        self.assertNotIn("达标标记 0 项", markdown)

    def test_positive_records_still_render_without_fabricated_host(self):
        virulence = {"status": "completed", "markers": [{"gene": "synthetic_marker",
                      "category": "毒素相关", "reads": 5, "coverage": 90, "identity": 99}]}
        markdown = render_markdown(self.document(virulence=virulence))
        self.assertIn("synthetic_marker", markdown)
        self.assertNotIn("达标标记 0 项", markdown)
        self.assertIn("尚缺少菌种与标记的序列连接证据", markdown)

    def test_unproven_host_label_is_not_linkage_evidence(self):
        from wgs_agent.reporting.chapter_four import figure_note, interpretation

        virulence = {"status": "completed", "markers": [{"gene": "synthetic_marker",
                      "host": "Example organism"}]}
        doc = self.document(virulence=virulence)
        self.assertIsNotNone(figure_note(doc))
        self.assertIn("尚缺少菌种与标记的序列连接证据", interpretation(doc, 3))


if __name__ == "__main__":
    unittest.main()
