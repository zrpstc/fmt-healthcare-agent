import copy
import json
import re
import pytest
from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.chapter_one import prepare_chapter_one, reference_rows
from wgs_agent.reporting.word_figures import chart_data, draw_chart, render_word_figures
from wgs_agent.reporting.word_template import contract


def build(core=None, healthy=False):
    species=[{"species":f"Species test{i}","abundance":10-i,"unit":"%"} for i in range(8)]
    species[0]["species"]="Ruminococcus bicirculans ex Wegman et al 2014"
    inputs={"taxonomy":{"unit":"%","ranks":{"phylum":[{"name":"Firmicutes","abundance":62.5},{"name":"Bacteroidota","abundance":37.5}],"genus":[{"name":"Bacteroides","abundance":13.14}]}}}
    if core is not None:inputs["core_microbiome"]=core
    if healthy:
        inputs["healthy_comparison"]={"species":[{**row,"abundance":row["abundance"]+1,"p5":0,"p95":2,"reference_median":0,"percentile":98.05825,"n_reference":103,"status":"high"} for row in species]}
    return build_document("CHAPTER_TEST",{"species_list":species},{},{},{},{},{},{},{},context={"health_inputs":inputs})


def subsection(md,number):
    return re.split(r"\n#{2,3} ",md.split(f"### {number} ",1)[1],maxsplit=1)[0]


def test_chapter_label_translation_is_names_only_and_preserves_other_labels(monkeypatch):
    doc=build(healthy=True)
    before=copy.deepcopy(doc["evidence"])
    doc["overview_taxon_labels"]={"saved":{"label":"保留的总览名称"}}
    calls=[]
    def request(config,messages,schema,post):
        items=json.loads(messages[1]["content"])["items"]
        assert all(set(item)=={"id","name"} for item in items)
        assert all("ex Wegman" not in item["name"] for item in items)
        calls.extend(items)
        return json.dumps({"items":[{"id":item["id"],"label":"测试菌名称"} for item in items]})
    monkeypatch.setattr("wgs_agent.reporting.narrative._request",request)
    prepare_chapter_one(doc,{"model":"test"},post=object())
    assert calls and doc["evidence"]==before
    assert doc["overview_taxon_labels"]=={"saved":{"label":"保留的总览名称"}}
    assert doc["audit"]["chapter_one_taxon_translation"]["untranslated"]==0


@pytest.mark.parametrize("ident,expected",[("1.1.1",62.5),("1.1.2",13.14),("1.1.3",10),("1.2.1",10)])
def test_percent_values_are_bound_without_renormalizing(ident,expected):
    doc=build();prepare_chapter_one(doc,None)
    payload=chart_data(doc,{"id":ident,"kind":"barChart"})
    assert payload["series"][0]["values"][0]==expected
    assert payload["chapter_one_mode"] in {"bars","phylum"}
    spec={"id":ident,"series":[{"color":"246a73"}]}
    assert draw_chart(spec,payload,900 if ident!="1.1.1" else 1800).width in {900,1800}
    assert payload["rows"][0]["display_label"]


def test_missing_core_hides_placeholder_ring_and_uses_full_width(tmp_path):
    doc=build();prepare_chapter_one(doc,None);render_word_figures(doc,tmp_path)
    panel=doc["word_figures"]["1.2.1+1.2.2"]
    assert [item["id"] for item in panel["items"]]==["1.2.1"]
    assert panel["width"]==1800 and not doc["chapter_one_presentation"]["core_chart_visible"]
    md=render_markdown(doc)
    assert "未绘制核心检出圆环" in subsection(md,"1.2")


def test_defined_core_keeps_useful_member_count_ring(tmp_path):
    core={"definition":"cohort-v1","members":[{"species":"a","abundance":1},{"species":"b","abundance":0}]}
    doc=build(core=core);prepare_chapter_one(doc,None);render_word_figures(doc,tmp_path)
    panel=doc["word_figures"]["1.2.1+1.2.2"]
    assert [item["id"] for item in panel["items"]]==["1.2.1","1.2.2"]
    ring=panel["items"][1]["data"]
    assert ring["center"]=="1/2" and ring["series"][0]["values"]==[1,1]
    assert doc["chapter_one_presentation"]["core_chart_visible"]


def test_all_eight_reference_table_entries_move_to_chart_without_primary_mixing():
    doc=build(healthy=True);prepare_chapter_one(doc,None)
    payload=chart_data(doc,{"id":"1.4.1","kind":"barChart"})
    assert len(payload["rows"])==8
    assert payload["series"][0]["values"][0]==11
    assert doc["evidence"]["S1"]["value"]==10
    for row in payload["rows"]:
        assert row["reference_median"]==0 and row["p95"]==2
        assert row["percentile"]==98.05825 and row["n_reference"]==103
    assert draw_chart({},payload,1800).height>1500


def test_only_requested_tables_removed_other_chapters_and_13_unchanged():
    doc=build();before=render_markdown(doc)
    prepare_chapter_one(doc,None);after=render_markdown(doc)
    assert "分类层级 |" not in subsection(after,"1.1")
    assert "核心成员明细" not in subsection(after,"1.2")
    assert "| 参考核心成员 |" not in subsection(after,"1.2")
    assert "| 组成指标 |" in subsection(after,"1.2")
    assert "| 重点物种 |" not in subsection(after,"1.4")
    assert before.split("## 2 ",1)[1]==after.split("## 2 ",1)[1]
    assert subsection(before,"1.3")==subsection(after,"1.3")


def test_failed_qc_never_displays_abundance_or_core_counts():
    doc=build();doc["metadata"]["qc_status"]="failed"
    prepare_chapter_one(doc,None)
    assert reference_rows(doc)==[]
    payload=chart_data(doc,{"id":"1.1.1","kind":"barChart"})
    assert payload["status"]=="missing"


def test_core_matching_normalizes_names_and_preserves_observed_zero():
    inputs={"core_microbiome":{"definition":"defined-reference","unit":"%","members":[{"species":"Core_A"},{"species":"Core_B"}]}}
    doc=build_document("CORE_TEST",{"species_list":[{"species":"Core A","abundance":5,"unit":"%"},{"species":"Core B","abundance":0,"unit":"%"}]},{},{},{},{},{},{},{},context={"health_inputs":inputs})
    prepare_chapter_one(doc,None)
    ring=chart_data(doc,{"id":"1.2.2","kind":"doughnutChart"})
    assert ring["status"]=="available" and ring["center"]=="1/2"
    assert "| 核心成员检出数 / 参考成员数 | 1 / 2 |" in render_markdown(doc)
