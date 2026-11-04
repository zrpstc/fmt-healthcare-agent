import copy
import gzip
import json
import math

import pytest

from wgs_agent.pipeline import specialized_metabolism as sm
from wgs_agent.reporting.document import build_document, render_markdown


@pytest.fixture
def inputs(tmp_path):
    profile = tmp_path / "sample.tsv"
    profile.write_text("# Gene Family\tS_Abundance\nUniRef90_A\t2\nUniRef90_A|g__B.s__B_a\t1.5\nUniRef90_B\t3\nUniRef90_C8WLM1\t1\n")
    mappings = tmp_path / "mapping"
    mappings.mkdir()
    with gzip.open(mappings / "map_level4ec_uniref90.txt.gz", "wt") as handle:
        handle.write("3.1.1.20\tUniRef90_A\n3.1.1.73\tUniRef90_A\tUniRef90_B\n3.2.1.31\tUniRef90_B\n1.7.1.6\tUniRef90_B\n1.7.1.17\tUniRef90_B\n")
    return profile, mappings


def panel(module, ident):
    return next(row for group in ["dietary", "drugs"] for row in module[group] if row["id"] == ident)


def test_real_family_values_and_contributors_are_not_reinterpreted_as_activity(inputs):
    profile, mappings = inputs
    module = sm.analyze_profile("S", profile, mappings, "relative_abundance")
    row = panel(module, "tannase")
    assert module["status"] == "completed"
    assert row["abundance"] == 2
    assert row["unit"] == "relative_abundance"
    assert row["stratified_contributions"][0]["abundance"] == 1.5
    assert row["pathway_completeness"] == "not_assessed"
    assert row["substrate_specific_activity"] == "not_tested"
    assert row["matched_gene_families"] == ["UniRef90_A"]


def test_overlapping_ec_groups_take_gene_union_once(inputs):
    profile, mappings = inputs
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    row = panel(module, "azoreductase")
    assert row["abundance"] == 3 and row["matched_gene_family_count"] == 1
    assert panel(module, "feruloyl_esterase")["abundance"] == 5


def test_unsupported_rows_are_quarantined_without_releasing_their_content(inputs):
    profile, mappings = inputs
    with profile.open("a") as f:
        f.write("NON_UNIREF_FEATURE\t9\n")
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    assert module["status"] == "partial"
    assert module["input_audit"]["quarantined_rows"] == 1
    assert "NON_UNIREF_FEATURE" not in json.dumps(module)
    assert panel(module, "tannase")["abundance"] == 2
    assert panel(module, "diltiazem_bt4096")["status"] == "not_assessed_incomplete_input"
    assert panel(module, "diltiazem_bt4096")["abundance"] is None


def test_missing_reference_is_not_a_negative_call(inputs):
    profile, mappings = inputs
    module = sm.analyze_profile("S", profile, mappings, "CPM")
    row = panel(module, "gallate_decarboxylase")
    assert row["status"] == "reference_unavailable"
    assert row["abundance"] is None
    module = sm.analyze_profile("S", profile, mappings / "missing", "CPM")
    assert module["status"] == "partial" and module["reference_audit"]["status"] == "missing"


def test_specific_drug_cluster_is_not_replaced_by_bacterium_or_generic_ec(inputs):
    profile, mappings = inputs
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    assert panel(module, "digoxin_cgr2")["matched_gene_families"] == ["UniRef90_C8WLM1"]
    assert panel(module, "diltiazem_bt4096")["status"] == "no_annotated_support"
    assert panel(module, "diltiazem_bt4096")["abundance"] is None


def test_uniref50_is_insufficient_for_curated_specific_markers(inputs):
    profile, mappings = inputs
    profile.write_text("UniRef50_C8WLM1\t1\n")
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    assert panel(module, "digoxin_cgr2")["status"] == "reference_unavailable"
    assert panel(module, "digoxin_cgr2")["abundance"] is None


def test_partial_equol_marker_group_does_not_become_complete_pathway(inputs):
    profile, mappings = inputs
    profile.write_text("UniRef90_E1CIA4\t2\nUniRef90_E7FL40\t1\n")
    row = panel(sm.analyze_profile("S", profile, mappings, "RPK"), "equol_marker_panel")
    assert row["marker_panel_coverage"] == "2/3"
    assert row["pathway_completeness"] == "not_assessed"
    assert row["substrate_specific_activity"] == "not_tested"


@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "invalid"])
def test_invalid_known_abundances_fail_the_analysis(inputs, bad):
    profile, mappings = inputs
    profile.write_text("UniRef90_A\t" + bad + "\n")
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    assert module["status"] == "invalid_input" and not module["dietary"]


@pytest.mark.parametrize("text", [
    "UniRef90_A\t1\nUniRef90_A\t2\n",
    "UniRef90_A\t1\nUniRef50_B\t2\n",
    "UniRef90_A\t1\nUniRef90_B|unclassified\t1\n",
    "UniRef90_A\t1\nUniRef90_A|unclassified\t2\n",
    "UniRef90_A\t1\t2\n",
])
def test_ambiguous_or_inconsistent_profiles_are_rejected(inputs, text):
    profile, mappings = inputs
    profile.write_text(text)
    assert sm.analyze_profile("S", profile, mappings, "RPK")["status"] == "invalid_input"


def test_artifact_sample_id_and_nonfinite_values_are_checked(tmp_path):
    target = sm.artifact_path(tmp_path, "S")
    target.parent.mkdir(parents=True)
    value = sm.envelope("OTHER", "completed", "COMPLETED")
    target.write_text(json.dumps(value))
    assert sm.load_specialized_inputs("S", tmp_path)["specialized_metabolism"]["status"] == "invalid_input"
    value = sm.envelope("S", "completed", "COMPLETED", dietary=[{"abundance": math.nan}])
    target.write_text(json.dumps(value))
    assert sm.load_specialized_inputs("S", tmp_path)["specialized_metabolism"]["status"] == "invalid_input"


def test_manual_specialized_results_and_unrelated_fields_are_preserved(inputs):
    profile, mappings = inputs
    old = {"specialized_metabolism": {"dietary": [{"name": "manual"}]}, "custom": 42}
    snapshot = copy.deepcopy(old)
    fresh = sm.analyze_profile("S", profile, mappings, "RPK")
    assert sm.merge_specialized_inputs({"specialized_metabolism": fresh}, old)["specialized_metabolism"] == old["specialized_metabolism"]
    assert old == snapshot
    assert sm.merge_specialized_inputs({}, {}) == {}


def document(module, qc=None):
    return build_document("S", {}, {}, {}, {}, {}, {}, {}, {},
        context={"qc_status": qc, "health_inputs": {"specialized_metabolism": module}})


def test_public_chapter_twelve_renders_generated_specialist_results_and_sources(inputs):
    profile, mappings = inputs
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    markdown = render_markdown(document(module))
    content = markdown.split("## 12 专项代谢转化功能", 1)[1].split("## 13 ", 1)[0]
    assert "单宁酶" in content and "家族丰度 2 RPK" in content
    assert "Cgr2" in content and "BT_4096" in content
    assert "完整通路" in content and "底物" in content
    assert "12.1" in content and "12.2" in content and "12.3" in content
    assert "3.1.1.20" in content


def test_qc_failure_does_not_display_specialized_abundances(inputs):
    profile, mappings = inputs
    module = sm.analyze_profile("S", profile, mappings, "RPK")
    content = render_markdown(document(module, "failed")).split("## 12 专项代谢转化功能", 1)[1].split("## 13 ", 1)[0]
    assert "家族丰度 2 RPK" not in content



def test_cached_results_are_invalidated_by_input_changes(inputs, tmp_path):
    profile, mapping = inputs
    output = tmp_path / "bio"
    target = output / "profiles/humann/S_genefamilies_relab.tsv"
    target.parent.mkdir(parents=True)
    target.write_bytes(profile.read_bytes())
    first = sm.run_sample("S", output, mapping)
    second = sm.run_sample("S", output, mapping)
    assert second == first
    target.write_text(target.read_text().replace("UniRef90_A\t2", "UniRef90_A\t4"))
    third = sm.run_sample("S", output, mapping)
    assert third["fingerprint"] != first["fingerprint"]
    assert panel(third, "tannase")["abundance"] == 4


def test_equol_steps_have_no_additive_pathway_abundance(inputs):
    profile, mapping = inputs
    profile.write_text("UniRef90_E1CIA4\t2\nUniRef90_E7FL40\t1\n")
    row = panel(sm.analyze_profile("S", profile, mapping, "RPK"), "equol_marker_panel")
    assert row["abundance"] is None
    assert row["marker_panel_coverage"] == "2/3"
    assert "DZNR 2 RPK" in row["result"] and "THDR 1 RPK" in row["result"]
