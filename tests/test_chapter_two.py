import copy
import json
import re
import pytest
from wgs_agent.reporting.document import build_document,render_markdown
from wgs_agent.reporting.functional_metrics import category,contributor_summary,read_humann_pathways
from wgs_agent.reporting.chapter_two import (prepare_chapter_two,diversity_rows,filter_diversity_table,
    redundancy_rows,redundancy_table,cooperation_data,chart_payload,draw_chart,draw_cooperation,cooperation_payload)


def path(ident,name,value=1,members=None,complete=False):
    return {"id":ident,"name":name,"abundance":value,"unit":"relative_abundance",
            "contributors":members or [],"contributors_complete":complete}


def member(taxon,value):
    return {"taxon":taxon,"abundance":value,"unit":"relative_abundance"}


def build(paths=(),healthy=False,manual=None):
    inputs={"diversity":{"richness":10,"shannon":2.1,"simpson":.85,"evenness":.8}}
    if healthy:
        inputs["healthy_comparison"]={"audit":{"status":"available","n_subjects":103,"limitations":[]},
            "diversity":[{"metric":metric,"name":label,"value":value,"p5":lo,"p95":hi,"reference_median":median,"percentile":pct,"n_subjects":103,"status":"normal","unit":"种" if metric=="richness" else "无量纲"}
            for metric,label,value,lo,hi,median,pct in [("richness","检出丰富度",10,5,30,15,20),("shannon","Shannon指数",2,1,4,3,25),("simpson","Simpson指数（1−D）",.85,.5,.95,.8,70),("evenness","Pielou均匀度",.8,.4,.9,.7,80)]]}
    if manual:inputs["metabolic_cooperation"]=manual
    return build_document("CH2_TEST",{}, {}, {}, {"pathways":list(paths)}, {}, {}, {}, {}, context={"health_inputs":inputs})


@pytest.mark.parametrize("name,expected",[
    ("acetyl-CoA fermentation to butanoate II","丁酸合成"),
    ("pyruvate fermentation to butanoate","丁酸合成"),
    ("butyrate oxidation",None),("4-aminobutanoate degradation",None),
    ("L-lactate degradation I","乳酸利用"),("lactate fermentation to propionate","乳酸利用"),
    ("pyruvate fermentation to acetate and lactate II",None),
    ("starch degradation III","复杂多糖降解"),("lipopolysaccharide biosynthesis",None),
])
def test_function_matching_respects_consumption_and_generation(name,expected):
    assert category(name)==expected


def test_canonical_file_verifies_all_strata_without_forcing_parent_sum(tmp_path):
    f=tmp_path/'sample_pathabundance_relab.tsv'
    f.write_text("# Pathway\tsample\nUNMAPPED\t.1\nP: starch degradation III\t.9\nP: starch degradation III|g__A.s__A_one\t.2\nP: starch degradation III|unclassified\t.1\n")
    result=read_humann_pathways(f);row=result["pathways"][0]
    assert result["stratification_source"]=="canonical_humann_output_v1"
    assert row["contributors_complete"] and row["abundance"]==.9
    summary=contributor_summary(row)
    assert summary["denominator"]==pytest.approx(.3)
    assert summary["top_named_share"]==pytest.approx(100*2/3)
    assert summary["unknown_share"]==pytest.approx(100/3) and summary["named_count"]==1


@pytest.mark.parametrize("extra",["P: starch degradation III|a\tNaN\n","P: starch degradation III|a\t.2\nP: starch degradation III|a\t.3\n","P: starch degradation III|a\t.2\textra\n"])
def test_invalid_or_duplicate_file_rows_cannot_claim_complete_output(tmp_path,extra):
    f=tmp_path/'bad.tsv';f.write_text("P: starch degradation III\t1\n"+extra)
    result=read_humann_pathways(f)
    assert result["validation_issues"] and not result["is_complete"]
    assert not result["pathways"][0]["contributors_complete"]


def test_unclassified_contribution_is_kept_in_denominator_and_not_counted_as_species():
    row=path("p","starch degradation III",10,[member("a",.6),member("b",.2),member("unclassified",.2)])
    s=contributor_summary(row)
    assert s["named_count"]==2 and s["top_named_share"]==pytest.approx(60)
    assert s["unknown_share"]==pytest.approx(20) and not s["complete"]
    bad={**row,"contributors":[member("a",1),{**member("b",1),"unit":"CPM"}]}
    assert contributor_summary(bad)["status"]=="missing"


def test_diversity_figure_contains_both_profiles_and_true_reference_statistics():
    doc=build(healthy=True);rows=diversity_rows(doc)
    shannon=next(r for r in rows if r["metric"]=="shannon")
    assert shannon["value"]==2 and shannon["primary_value"]==2.1
    assert shannon["reference_median"]==3 and shannon["p95"]==4 and shannon["n_subjects"]==103
    payload=chart_payload(doc,{"id":"2.1.1"})
    assert draw_chart({},payload,1800).height>900
    original=[["观测物种数","10"],["Shannon指数","2.1"],["MHNO 独立谱 · Shannon指数","2"],["丰富度估计","未提供"]]
    assert filter_diversity_table(doc,original)==[["丰富度估计","未提供"]]
    md=render_markdown(doc);block=md.split("### 2.1 ",1)[1].split("### 2.2 ",1)[0]
    assert "| 观测物种数 |" not in block and "| 丰富度估计 |" in block
    assert "MHOmicrobiome MHNO 独立对照" not in block and "意义解读：" not in block


def test_existing_functions_are_populated_without_turning_lactate_production_into_use():
    doc=build([path("PWY-5676","acetyl-CoA fermentation to butanoate II",1,[member("a",.1)],True),path("PWY-6731","starch degradation III",2,[member("a",.8),member("unclassified",.2)],True),path("P41-PWY","pyruvate fermentation to lactate",1,[member("b",1)],True)])
    rows=redundancy_rows(doc)
    assert rows[0]["pathway"]["id"]=="PWY-5676" and rows[0]["summary"]["top_named_share"]==100
    assert rows[1]["pathway"] is None
    assert rows[2]["summary"]["named_count"]==1
    assert all("未建立功能参考分布"==r[3] for r in redundancy_table(doc))
    assert draw_chart({},chart_payload(doc,{"id":"2.3.1"}),1800).height>700


def test_stages_use_annotations_without_inventing_crossfeeding_links():
    paths=[path("PWY-6731","starch degradation III",1,[member("g__A.s__A_one",1)]),path("GLYCOLYSIS","glycolysis I",1,[member("g__B.s__B_two",1)]),path("PWY-5676","acetyl-CoA fermentation to butanoate II",1,[member("g__C.s__C_three",1)])]
    doc=build(paths);evidence=copy.deepcopy(doc["evidence"])
    stages=cooperation_data(doc)
    assert len(stages["stages"])==3 and all(s["pathway"] for s in stages["stages"])
    assert stages["connections"]==[] and stages["source"]=="independent_pathway_stage_annotations"
    assert "未提供菌间交换" in stages["stages"][0]["link_evidence"]
    assert draw_cooperation(cooperation_payload(doc),1800).width==1800
    assert doc["evidence"]==evidence


def test_provided_stage_records_are_preserved():
    doc=build(manual={"stages":[{"stage":"底物初级降解","contributors":"已报告菌A","function":"已报告功能","link_evidence":"已报告证据"}]})
    data=cooperation_data(doc)
    assert data["source"]=="provided_stage_records" and data["stages"][0]["contributors"]=="已报告菌A"


def test_translation_request_contains_only_taxon_names(monkeypatch):
    doc=build([path("PWY-6731","starch degradation III",1,[member("g__Escherichia.s__Escherichia_coli",.8),member("unclassified",.2)])])
    received=[]
    def request(config,messages,schema,post):
        items=json.loads(messages[1]["content"])["items"];received.extend(items)
        assert all(set(item)=={"id","name"} for item in items)
        return json.dumps({"items":[{"id":item["id"],"label":"大肠埃希菌"} for item in items]})
    monkeypatch.setattr("wgs_agent.reporting.narrative._request",request)
    prepare_chapter_two(doc,{"model":"test"},post=object())
    assert received and {item["name"] for item in received}=={"Escherichia coli"}
    assert doc["audit"]["chapter_two_taxon_translation"]["untranslated"]==0


def test_failed_qc_never_fills_plots_with_existing_numbers():
    doc=build([path("p","starch degradation III",1,[member("a",1)])],healthy=True)
    doc["metadata"]["qc_status"]="failed"
    assert diversity_rows(doc)==[] and cooperation_data(doc)["stages"]==[]
    assert all(r["summary"]["status"]=="missing" for r in redundancy_rows(doc))


@pytest.mark.asyncio
async def test_generator_prefers_verified_canonical_strata_over_legacy_complete_module(tmp_path,monkeypatch):
    from wgs_agent.reporting import inputs,reference,knowledge_graph
    from wgs_agent.tools import detailed_report
    from wgs_agent.tools.domain_tools import ReportGeneratorTool
    fresh={"is_complete":True,"stratification_source":"canonical_humann_output_v1",
           "pathways":[path("VERIFIED","acetyl-CoA fermentation to butanoate II",1,[member("g__A.s__A_one",.2)],True)]}
    monkeypatch.setenv("WGS_WORKSPACE",str(tmp_path))
    monkeypatch.setattr(inputs,"load_existing_report_inputs",lambda _: {"pathways":fresh})
    monkeypatch.setattr(reference,"refresh_reference_comparisons",lambda data,other:data)
    monkeypatch.setattr(detailed_report,"resolve_report_model",lambda:None)
    monkeypatch.setattr(detailed_report,"load_gene_family_evidence",lambda _: {})
    async def none(_):return None
    monkeypatch.setattr(knowledge_graph,"enrich_document",none)
    source=tmp_path/'CANONICAL_TEST_analysis.json'
    source.write_text(json.dumps({"sample_id":"CANONICAL_TEST","pathways":{"is_complete":True,"pathways":[path("STALE","old pathway")]}}))
    result=await ReportGeneratorTool().invoke({"sample_id":"CANONICAL_TEST","analysis_json_path":str(source)})
    assert not result.is_error,result.content
    doc=json.loads((tmp_path/'CANONICAL_TEST_report.json').read_text())
    assert doc["chapter_two_results"]["redundancy"][0]["pathway"]["id"]=="VERIFIED"
    assert doc["chapter_two_results"]["redundancy"][0]["summary"]["complete"]
