import copy
import json

import numpy as np
import pytest

from wgs_agent.reporting import cmd
from wgs_agent.reporting.cmd_derived import (prepare_derived_reference, load_derived,
    typicality_comparison, target_distance_vector, DISTANCES)
from wgs_agent.reporting.functional_metrics import aggregate_category, pathway_category, record_function_consistency
from test_cmd_reference import bundle


def path(ident, name, members=(), unit="relative_abundance"):
    return {"kind": "pathway", "id": ident, "name": name, "value": 1,
            "unit": unit, "contributors": [{"taxon": taxon, "abundance": value, "unit": unit} for taxon,value in members],
            "contributors_complete": True}


def document(*rows):
    return {"evidence": {f"P{i}":r for i,r in enumerate(rows)}, "template_inputs": {}}


def test_all_pathways_are_pooled_and_unknown_kept_without_mutating_raw_evidence():
    doc = document(path("P163-PWY", "L-lysine fermentation to acetate and butanoate", [("A one", 2), ("unclassified", 1)]),
                   path("PWY-5676", "acetyl-CoA fermentation to butanoate II", [("A one", 1), ("B two", 2)]))
    before = copy.deepcopy(doc)
    result = aggregate_category(doc, "丁酸合成")
    assert len(result["pathways"]) == 2 and result["named_count"] == 2
    assert result["denominator"] == 6 and result["top_named_share"] == 50
    assert result["unknown_share"] == pytest.approx(100/6)
    assert doc == before


def test_mixed_units_keep_separate_pathway_summaries_and_no_pooled_shares():
    result = aggregate_category(document(path("P163-PWY", "x", [("A one",2)]),
                                        path("PWY-5676", "x", [("B two",5)], "CPM")), "丁酸合成")
    assert result["denominator"] is None and result["top_named_share"] is None
    assert not result["unit_consistent"] and len(result["per_pathway"]) == 2
    assert all(r["share"] is None for r in result["contributors"])
    assert [p["summary"]["top_named_share"] for p in result["per_pathway"]] == [100,100]


def test_enzyme_evidence_adds_taxa_without_adding_enzyme_abundance_to_pathway_denominator():
    doc = document(path("P163-PWY", "x", [("A one",2)]))
    doc["template_inputs"]["functional_modules"] = {"status":"completed","results":[
        {"id":"EC:2.8.3.8","abundance":1000,"unit":"CPM","contributors":[
            {"taxon":"A one","abundance":500,"unit":"CPM"},
            {"taxon":"B two","abundance":500,"unit":"CPM"}]}]}
    result = aggregate_category(doc,"丁酸合成")
    assert result["denominator"] == 2 and result["named_count"] == 2
    assert result["contributors"][0]["share"] == 100
    assert result["contributors"][1]["share"] is None
    assert any(e["type"] == "enzyme_marker" for e in result["contributors"][1]["evidence"])
    doc["template_inputs"]["functional_modules"]["status"]="invalid_input"
    assert aggregate_category(doc,"丁酸合成")["named_count"]==1


def test_curated_butyrate_route_does_not_treat_all_gaba_degradation_as_butyrate():
    assert pathway_category({"id":"PWY-5022","name":"4-aminobutanoate degradation V"})=="丁酸合成"
    assert pathway_category({"name":"4-aminobutanoate degradation I"}) is None
    assert pathway_category({"id":"PWY-8086","name":"(S)-lactate fermentation to propanoate, acetate and hydrogen"})=="乳酸利用"
    assert pathway_category({"name":"pyruvate fermentation to lactate"}) is None


def test_coverage_gap_is_idempotent_and_retained_in_consumer_audit():
    doc=document(path("P163-PWY","x",[("A one",2)]))
    doc["template_inputs"]["taxonomy"]={"ranks":{"species":[{"name":"Faecalibacterium prausnitzii","abundance":13.3}]}}
    glossary=[{"name":"Faecalibacterium prausnitzii","tags":["butyrate_producer"]}]
    aggregate=aggregate_category(doc,"丁酸合成")
    first=record_function_consistency(doc,"丁酸合成",aggregate,glossary)
    assert first[0]["type"]=="coverage_gap"
    record_function_consistency(doc,"丁酸合成",aggregate,glossary)
    assert doc["consumer"]["function_consistency"]==first


def test_offline_reference_leave_one_out_and_runtime_vector_include_target_only_species(tmp_path):
    from scipy.spatial.distance import pdist, squareform, cdist
    base=bundle(tmp_path);output=tmp_path/'derived'
    result=prepare_derived_reference(base,output,block_size=4)
    manifest,labels,features,matrix,hashes=cmd.load_bundle(output)
    derived=load_derived(output,manifest,hashes)
    manual=squareform(pdist(matrix.values_array,metric='braycurtis'))
    medians=[float(np.median(np.delete(row,i))) for i,row in enumerate(manual)]
    assert next(iter(derived[0]['strata'].values()))['typicality']==pytest.approx(medians,abs=1e-7)
    target={matrix.features[0]:30,'target_only_species':70}
    selected=list(matrix.ids)
    vector=target_distance_vector(target,matrix,selected)
    complete=np.column_stack((matrix.values_array,np.zeros(len(selected))))
    target_values=np.array([target.get(f,0) for f in matrix.features]+[70])
    assert vector==pytest.approx(cdist([target_values],complete,'braycurtis')[0])
    comparison,shared_vector=typicality_comparison(target,matrix,selected,derived,reference_version='test')
    assert comparison['n_reference']==35 and comparison['status']=='available'
    assert comparison['percentile']==100 and not comparison['borderline']
    assert comparison['derived_sha256']==manifest['files']['consumer_derived.json']
    assert shared_vector==pytest.approx(vector)
    assert result['files'][DISTANCES]==manifest['files'][DISTANCES]


def test_derived_sha_failure_and_self_exclusion_do_not_silently_use_other_cohort(tmp_path):
    base=bundle(tmp_path);output=tmp_path/'derived';prepare_derived_reference(base,output)
    manifest,_,_,matrix,hashes=cmd.load_bundle(output)
    derived=load_derived(output,manifest,hashes)
    row,vector=typicality_comparison(matrix[matrix.ids[0]],matrix,list(matrix.ids)[1:],derived)
    assert row['n_reference']==34 and len(vector)==34
    with pytest.raises(ValueError,match='insufficient'):
        typicality_comparison(matrix[matrix.ids[0]],matrix,list(matrix.ids)[:29],derived)
    path=output/DISTANCES;path.chmod(0o640)
    with path.open('ab') as f:f.write(b'x')
    with pytest.raises(ValueError,match='sha_mismatch'):
        load_derived(output,manifest,hashes)


def test_typicality_boundary_reuses_existing_bootstrap_rule(tmp_path,monkeypatch):
    from wgs_agent.reporting import cmd_derived
    base=bundle(tmp_path);output=tmp_path/'derived';prepare_derived_reference(base,output)
    manifest,_,_,matrix,hashes=cmd.load_bundle(output)
    derived=load_derived(output,manifest,hashes)
    reference=next(iter(derived[0]['strata'].values()))['typicality']
    boundary=float(np.quantile(reference,.95))
    monkeypatch.setattr(cmd_derived,'target_distance_vector',lambda *args:np.full(len(matrix),boundary))
    row,_=typicality_comparison(matrix[matrix.ids[0]],matrix,list(matrix.ids),derived)
    assert row['borderline'] and row['comparison_status']=='borderline'
    assert 'percentile_ci95' in row and row['bootstrap_iterations']==1000


def test_existing_marker_lookup_reuses_strict_parser_and_quarantines_invalid_rows(tmp_path):
    import gzip
    from wgs_agent.reporting.consumer_markers import existing_enzyme_markers
    folder=tmp_path/'profiles/humann';folder.mkdir(parents=True)
    (folder/'TEST_genefamilies_relab.tsv').write_text(
        'UniRef90_A123\t.5\nUniRef90_A123|g__Faecalibacterium.s__Faecalibacterium_prausnitzii\t.5\n'
        'UniRef90_invalid!\t100\n')
    mapping=tmp_path/'maps';mapping.mkdir()
    with gzip.open(mapping/'map_level4ec_uniref90.txt.gz','wt') as f:
        f.write('2.8.3.8\tUniRef90_A123\n')
    result=existing_enzyme_markers('TEST',root=tmp_path,mapping_dir=mapping)
    assert result['status']=='available' and result['input_audit']['quarantined_rows']==1
    assert len(result['results'])==1 and result['results'][0]['abundance']==.5
    doc=document(path('P163-PWY','x',[('Fusobacterium nucleatum',1)]))
    doc['consumer']={'enzyme_markers':result}
    aggregate=aggregate_category(doc,'丁酸合成')
    assert aggregate['named_count']==2 and aggregate['denominator']==1
    assert aggregate['contributors'][1]['name']=='Faecalibacterium prausnitzii'
