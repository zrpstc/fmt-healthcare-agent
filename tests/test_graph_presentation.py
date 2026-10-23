"""Chinese display transformation, styling and module bibliography contracts."""

import copy
import json
import re

from wgs_agent.reporting.bibliography import citation, module_bibliographies
from wgs_agent.reporting.document import render_markdown
from wgs_agent.reporting.graph_labels import resolve_graph_model, translate_graph_labels
from wgs_agent.reporting.graph_visual import render_graph_figures
from wgs_agent.reporting.knowledge_graph import attach_subgraphs, relation_label
from test_report_knowledge_graph import claim, document, topic


class Response:
    status_code = 200
    text = ""

    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(self.data, ensure_ascii=False)},
                }
            ]
        }


def fake_post(url, **kwargs):
    items = json.loads(kwargs["json"]["messages"][1]["content"])["items"]
    labels = {
        "entity": "中文实体",
        "type": "实体类型",
        "relation": "相关",
        "attribute": "丰度升高，观察性研究",
    }
    return Response(
        {
            "items": [
                {
                    "id": item["id"],
                    "label": labels[item["kind"]],
                    "detail": "保留原始含义的中文说明",
                }
                for item in items
            ]
        }
    )


def test_environment_model_overrides_workspace_and_never_exposes_credentials(monkeypatch):
    monkeypatch.delenv("WGS_REPORT_GRAPH_LLM_DISABLED", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://env-model/v1")
    monkeypatch.setenv("WGS_LLM_DEFAULT_MODEL", "env-model")
    monkeypatch.delenv("WGS_REPORT_GRAPH_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("WGS_REPORT_LLM_BASE_URL", raising=False)
    config = resolve_graph_model()
    assert config["base_url"] == "http://env-model/v1"
    assert config["model"] == "env-model"
    doc = document([claim()])
    translate_graph_labels(doc, config, post=fake_post)
    assert "secret-value" not in json.dumps(doc)
    assert doc["audit"]["graph_translation"]["status"] == "generated"


def test_translation_keeps_raw_graph_identity_qualifiers_and_negation():
    doc = document([claim(negated=True, speculative=True)])
    row = topic(doc)
    row["knowledge_subgraph"]["edges"][0]["qualifiers"] = {"evidence_type": "observational"}
    original = copy.deepcopy(row["knowledge_subgraph"])
    translate_graph_labels(doc, {"base_url": "http://test/v1", "model": "test"}, post=fake_post)
    graph = row["knowledge_subgraph"]
    for before, after in zip(original["nodes"], graph["nodes"]):
        assert (before["id"], before["label"], before["type"]) == (
            after["id"],
            after["label"],
            after["type"],
        )
        assert not re.search(r"[A-Za-z]", after["display_label"] + after["display_type"])
    edge = graph["edges"][0]
    assert edge["predicate"] == "CORRELATED_WITH" and edge["negated"] and edge["speculative"]
    assert edge["display_attributes"] == "丰度升高，观察性研究"
    assert "否定" in relation_label(edge) and "推测" in relation_label(edge)


def test_unknown_english_fallback_is_hidden_instead_of_leaking_to_image(tmp_path):
    doc = document([claim(object="unknown complex experimental outcome")])
    translate_graph_labels(doc, None)
    assert topic(doc)["knowledge_subgraph"]["display_status"] == "unavailable"
    assert not render_graph_figures(doc, tmp_path)
    assert "unknown complex" not in render_markdown(doc)
    assert "中文图谱暂不可用" in render_markdown(doc)


def test_invalid_english_and_unknown_ids_are_rejected_and_repaired_once():
    doc = document([claim(object="Unknown outcome")])
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        items = json.loads(kwargs["json"]["messages"][1]["content"])["items"]
        if len(calls) == 1:
            return Response(
                {
                    "items": [
                        {"id": item["id"], "label": "English label", "detail": "English detail"}
                        for item in items
                    ]
                    + [{"id": "invented", "label": "杜撰", "detail": "杜撰"}]
                }
            )
        return fake_post(url, **kwargs)

    translate_graph_labels(doc, {"base_url": "http://test/v1", "model": "test"}, post=post)
    assert len(calls) == 2
    assert "invented" not in doc["graph_label_translations"]
    assert topic(doc)["knowledge_subgraph"]["display_status"] == "ready"


def test_styling_uses_shared_nodes_variable_sizes_and_type_colors(tmp_path):
    doc = document([claim(1), claim(2, object="acetate", predicate="PRODUCES")])
    translate_graph_labels(doc, None)
    figures = render_graph_figures(doc, tmp_path)
    graph = topic(doc)["knowledge_subgraph"]
    assert len(graph["nodes"]) == 3
    style = graph["visual_style"]
    assert len(set(style["node_colors"].values())) == 2
    assert len(set(style["edge_colors"].values())) == 2
    assert len(set(tuple(size) for size in style["node_sizes"].values())) > 1
    assert (tmp_path / figures[topic(doc)["id"]]).read_bytes().startswith(b"\x89PNG")
    saved = copy.deepcopy(graph)
    attach_subgraphs(doc)
    assert graph == topic(doc)["knowledge_subgraph"] == saved
    markdown = render_markdown(doc)
    assert graph["figure"] in markdown
    assert "证据原句" not in markdown and "参考依据：" not in markdown
    assert "CORRELATED_WITH" not in markdown and "document:" not in markdown


def test_module_references_deduplicate_claims_and_include_only_used_papers():
    doc = document([claim(1), claim(2), claim(3, "Unrelated species", "unrelated outcome")])
    for key in ("K1", "K2"):
        doc["evidence"][key].update(
            title="Original paper title",
            authors=["First Author", "Second Author"],
            journal="Journal",
            year=2021,
            doi="10.1234/test",
        )
    doc["evidence"]["K3"].update(title="Unused paper")
    modules = module_bibliographies(doc)
    module = next(m for m in modules if m["id"] == "key_taxa")
    citations = [p["citation"] for p in module["references"]]
    assert sum("Original paper title" in p for p in citations) == 1
    assert not any("Unused paper" in p for p in citations)
    assert (
        "First Author, Second Author. Original paper title. Journal, 2021. DOI: 10.1234/test."
        in citations
    )
    markdown = render_markdown(doc)
    body, references = markdown.split("### 分模块参考文献", 1)
    assert "Original paper title" not in body and "Original paper title" in references
    assert "#### 重点菌群" in references
    assert "[1]" in references


def test_missing_bibliographic_fields_are_omitted_without_guessing():
    value = citation({"title": "A study"})
    assert value == "A study."
    assert "未提供" not in value and "202" not in value
    assert (
        citation({"title": "A <i>microbial</i> study &amp; its results"})
        == "A microbial study & its results."
    )


def test_multiline_entity_and_property_labels_render_without_anchor_errors(tmp_path):
    doc = document([claim()])
    translate_graph_labels(doc, None)
    row = topic(doc)
    graph = row["knowledge_subgraph"]
    graph["nodes"][0]["display_label"] = "表达复杂免疫标记的特异性研究细胞群"
    graph["edges"][0]["display_attributes"] = "观察性研究，菌群相对丰度升高，研究对象为实验小鼠"
    assert render_graph_figures(doc, tmp_path)


def test_translation_cache_reuses_results_and_isolates_models(tmp_path, monkeypatch):
    from wgs_agent.reporting import graph_labels

    monkeypatch.setenv("WGS_WORKSPACE", str(tmp_path))
    calls = []

    def request(config, messages, schema, post):
        calls.append(config["model"])
        items = json.loads(messages[1]["content"])["items"]
        return json.dumps(
            {"items": [{"id": i["id"], "label": "中文", "detail": "中文说明"} for i in items]},
            ensure_ascii=False,
        )

    monkeypatch.setattr(graph_labels, "_request", request)
    config = {"base_url": "http://test/v1", "model": "first"}
    translate_graph_labels(document([claim()]), config)
    second = document([claim()])
    translate_graph_labels(second, config)
    assert calls == ["first"]
    assert second["audit"]["graph_translation"]["cached_labels"] > 0
    translate_graph_labels(document([claim()]), {**config, "model": "second"})
    assert calls == ["first", "second"]
    assert all(
        p.stat().st_mode & 0o777 == 0o600 for p in (tmp_path / "report-graph-labels").glob("*.json")
    )


def test_self_relation_keeps_renderable_loop(tmp_path):
    doc = document([claim(object="Bifidobacterium longum", object_type="MicrobialTaxon")])
    translate_graph_labels(doc, None)
    graph = topic(doc)["knowledge_subgraph"]
    assert len(graph["nodes"]) == 1
    assert graph["edges"][0]["source"] == graph["edges"][0]["target"]
    assert render_graph_figures(doc, tmp_path)


def test_property_caption_keeps_declared_direction_and_full_conditions():
    from wgs_agent.reporting.graph_visual import property_caption

    edge = {
        "qualifiers": {
            "metric": "concentration",
            "direction": "increased",
            "reference_group": "肥胖对照",
            "evidence_type": "observational",
        },
        "display_attributes": "无菌组浓度高于肥胖对照，来自观察性研究",
    }
    before = copy.deepcopy(edge)
    assert property_caption(edge) == "浓度升高 · 观察研究"
    assert edge == before
    edge["qualifiers"]["direction"] = "decreased"
    assert "降低" in property_caption(edge)
