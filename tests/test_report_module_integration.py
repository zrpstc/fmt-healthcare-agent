import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from wgs_agent.pipeline import functional_annotations as fa
from wgs_agent.pipeline import strain_virulence as four, resistome_mge as five
from wgs_agent.reporting import chapter_four, chapter_five
from wgs_agent.reporting.module_refresh import serialize_analysis
from wgs_agent.reporting.report_lock import report_lock


def mappings(root, rows="1.11.1.6\tUniRef90_A\tUniRef90_B\n1.11.1.7\tUniRef90_B\n"):
    root.mkdir(parents=True, exist_ok=True)
    for name, text in {"map_ec_name.txt.gz": "1.11.1.6\tCatalase\n1.11.1.7\tPeroxidase\n",
                       "map_level4ec_uniref90.txt.gz": rows}.items():
        with gzip.open(root / name, "wt") as f:
            f.write(text)
    return root


def gene_file(root, sid="sample", text=None):
    path = root / "profiles/humann" / f"{sid}_genefamilies_relab.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "UniRef90_A\t0.2\nUniRef90_A|s__Example_one\t0.1\nUniRef90_B\t0.3\nUniRef90_B|s__Example_two\t0.2\n")
    return path


def test_ec_annotation_preserves_overlap_units_and_contributors(tmp_path):
    path = gene_file(tmp_path)
    db = mappings(tmp_path / "mapping")
    result = fa.run_sample("sample", tmp_path, db)
    assert result["status"] == "completed"
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id["EC:1.11.1.6"]["abundance"] == pytest.approx(.5)
    assert by_id["EC:1.11.1.7"]["abundance"] == pytest.approx(.3)
    assert result["summary"]["matched_gene_families"] == 2
    assert all(r["unit"] == "relative_abundance" for r in result["results"])
    assert len(by_id["EC:1.11.1.6"]["contributors"]) == 2
    assert path.read_text().startswith("UniRef90_A\t0.2")
    assert not any("percentile" in r for r in result["results"])


def test_annotation_scans_beyond_top_200(tmp_path):
    text = "".join(f"UniRef90_X{i}\t{1000-i}\n" for i in range(250)) + "UniRef90_A\t0.001\n"
    gene_file(tmp_path, text=text)
    result = fa.run_sample("sample", tmp_path, mappings(tmp_path / "mapping"))
    assert result["summary"]["input_gene_families"] == 251
    assert result["results"][0]["detected_genes"] == ["UniRef90_A"]


def test_split_mapping_rows_are_unioned_and_incomplete_ec_is_not_promoted(tmp_path):
    path = gene_file(tmp_path)
    db = mappings(tmp_path / "mapping", "1.11.1.6\tUniRef90_A\n1.11.1.6\tUniRef90_A\tUniRef90_B\n1.11.1.-\tUniRef90_A\n")
    with gzip.open(db / "map_ec_name.txt.gz", "wt") as f:
        f.write("1.11.1.6\tCatalase\n1.11.1.-\tPeroxidase family\n")
    rows, _ = fa.annotate(path, db / "map_ec_name.txt.gz", db / "map_level4ec_uniref90.txt.gz", "relative_abundance")
    assert len(rows) == 1 and rows[0]["abundance"] == pytest.approx(.5)
    assert rows[0]["supporting_gene_family_count"] == 2


@pytest.mark.parametrize("text", ["UniRef90_A\tnan\n", "UniRef90_A\t-1\n", "UniRef90_A\t1\nUniRef90_A\t2\n", "UniRef90_A|s__Orphan\t1\n", "UniRef90_A\t1\nUniRef50_B\t2\n"])
def test_invalid_gene_data_does_not_create_negative_findings(tmp_path, text):
    gene_file(tmp_path, text=text)
    result = fa.run_sample("sample", tmp_path, mappings(tmp_path / "mapping"))
    assert result["status"] == "invalid_input" and result["results"] == []


def test_annotation_cache_invalidates_changed_inputs(tmp_path, monkeypatch):
    path = gene_file(tmp_path)
    db = mappings(tmp_path / "mapping")
    first = fa.run_sample("sample", tmp_path, db)
    real = fa.annotate
    calls = []
    def track(*args):
        calls.append(1)
        return real(*args)
    monkeypatch.setattr(fa, "annotate", track)
    assert fa.run_sample("sample", tmp_path, db)["fingerprint"] == first["fingerprint"]
    assert not calls
    path.write_text(path.read_text().replace("0.2", "0.4"))
    assert fa.run_sample("sample", tmp_path, db)["fingerprint"] != first["fingerprint"]
    assert len(calls) == 1


def test_ec_annotations_reach_chapter_nine_and_gene_evidence(tmp_path):
    from wgs_agent.reporting.document import build_document
    from wgs_agent.reporting.chapter_eight import detected_genes
    gene_file(tmp_path)
    fa.run_sample("sample", tmp_path, mappings(tmp_path / "mapping"))
    inputs = fa.load_functional_inputs("sample", tmp_path)
    doc = build_document("sample", {}, {}, {}, {}, {}, {}, {}, {}, context={"health_inputs": inputs})
    assert len(doc["chapter_nine_results"]["features"]["redox"]["evidence_ids"]) == 2
    rows = [r for r in doc["evidence"].values() if r.get("kind") == "function"]
    assert detected_genes(rows) == ["UniRef90_B", "UniRef90_A"]
    assert all(r["annotation_level"].endswith("not a complete pathway") for r in rows)


def test_ec_annotations_bind_chapter_eight_gene_column_without_claiming_full_pathway(tmp_path):
    from wgs_agent.reporting.document import build_document
    from wgs_agent.reporting.chapter_eight import table_rows
    gene_file(tmp_path)
    db = mappings(tmp_path / "mapping", "9.9.9.9\tUniRef90_A\n")
    with gzip.open(db / "map_ec_name.txt.gz", "wt") as f:
        f.write("9.9.9.9\tSynthetic butyrate enzyme\n")
    fa.run_sample("sample", tmp_path, db)
    doc = build_document("sample", {}, {}, {}, {}, {}, {}, {}, {},
                         context={"health_inputs": fa.load_functional_inputs("sample", tmp_path)})
    rows = table_rows(doc, 1)
    matched = [row for row in rows if "UniRef90_A" in row[3]]
    assert matched and "非完整通路" in matched[0][1]


def test_cross_sample_annotation_rejected_and_legacy_preserved(tmp_path):
    four.atomic_json(fa.artifact_path(tmp_path, "sample"), fa.envelope("other", "completed"))
    assert fa.load_functional_inputs("sample", tmp_path)["functional_modules"]["status"] == "invalid_input"
    legacy = {"functional_modules": {"observations": [{"name": "explicit assay"}]}}
    assert fa.merge_functional_inputs({}, legacy) == legacy


def test_all_analysis_refreshers_share_report_lock(tmp_path):
    analysis = tmp_path / "sample_analysis.json"
    analysis.write_text('{"sample_id":"sample","custom":1}')
    bio = tmp_path / "bio"
    four.atomic_json(four.artifact_path(bio, "virulence", "sample"), four.envelope("virulence", "sample", "completed"))
    five.atomic_json(five.artifact_path(bio, "resistance", "sample"), five.envelope("resistance", "sample", "completed"))
    with report_lock(tmp_path, "sample"):
        for refresh in (chapter_four.refresh_analysis_modules, chapter_five.refresh_analysis_modules):
            with pytest.raises(BlockingIOError):
                refresh(analysis, "sample", bio)
    chapter_four.refresh_analysis_modules(analysis, "sample", bio)
    chapter_five.refresh_analysis_modules(analysis, "sample", bio)
    saved = json.loads(analysis.read_text())
    assert saved["custom"] == 1 and "virulence" in saved and "resistance" in saved


def test_new_modules_persist_without_reference_changes_and_unchanged_bytes_preserved():
    original = b'{"sample_id": "sample", "custom": 1}\n'
    updated = json.loads(original)
    updated["virulence"] = {"status": "completed"}
    updated["dna_viruses"] = {"complete": True}
    assert json.loads(serialize_analysis(original, updated)) == updated
    assert serialize_analysis(original, json.loads(original)) == original


def test_cache_recovery_runs_all_supplements_without_base_pipeline(tmp_path):
    source = Path(__file__).resolve().parents[1] / "runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh"
    app = tmp_path / "app"
    target = app / "runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh"
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text())
    output = tmp_path / "bio"
    for rel in ("status/done/sample.done", "profiles/metaphlan/sample_profile.tsv",
                "profiles/humann/sample_pathabundance_relab.tsv", "profiles/humann/sample_genefamilies_relab.tsv",
                "clean_merged/sample.dehosted.fastq.gz"):
        p = output / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("" if rel.endswith(".done") else "synthetic")
    group = tmp_path / "sample.json"
    group.write_text('{"sample_id":"sample"}')
    fake = tmp_path / "module-python"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PROBE_EVENTS"\n')
    fake.chmod(0o755)
    events = tmp_path / "events"
    env = {**os.environ, "PYTHON": sys.executable, "PROBE_EVENTS": str(events),
           "WGS_HEALTHY_REFERENCE_PROVIDER": "", "WGS_CHAPTER4_PYTHON": str(fake),
           "WGS_CHAPTER5_PYTHON": str(fake), "WGS_CHAPTER6_PYTHON": str(fake),
           "WGS_FUNCTIONAL_PYTHON": str(fake), "WGS_CHAPTER4_ENABLED": "1",
           "WGS_CHAPTER5_ENABLED": "1", "WGS_CHAPTER6_ENABLED": "1", "WGS_FUNCTIONAL_ANNOTATIONS_ENABLED": "1"}
    p = subprocess.run(["bash", str(target), "--group-json", str(group), "--output-root", str(output)],
                       env=env, capture_output=True, text=True, timeout=10)
    assert p.returncode == 0, p.stderr
    calls = events.read_text()
    for name in ("strain_virulence", "resistome_mge", "non_bacterial", "functional_annotations"):
        assert "wgs_agent.pipeline." + name in calls
    assert (output / "status/done/sample.done").stat().st_size > 0
    assert not list((output / "work/sample/fastp").glob("*.fastq"))


def test_empty_done_marker_is_not_complete(tmp_path, monkeypatch):
    from wgs_agent.pipeline import upload_workflow, mho_workflow
    monkeypatch.setattr(mho_workflow, "get_mho_status", lambda sid: {"ready": False})
    settings = SimpleNamespace(job_root=tmp_path / "jobs", output_root=tmp_path / "bio")
    done = settings.output_root / "status/done/sample.done"
    done.parent.mkdir(parents=True)
    done.touch()
    result = upload_workflow.get_workflow_status("sample", settings=settings, include_log=False)
    assert result["state"] != "complete"
