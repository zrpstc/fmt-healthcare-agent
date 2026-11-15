"""Consumer presentation of chapter two, retaining all original evidence IDs."""
from __future__ import annotations

import hashlib
import io
import re
import copy
from pathlib import Path

from PIL import Image, ImageDraw

from .consumer_format import count, percentile_phrase, tier
from .consumer_copy import FUNCTION_BACKUP
from .consumer_state import consumer, omit, NameRegistry
from .functional_metrics import aggregate_category, record_function_consistency, taxon_name
from .inputs import finite

STANDARD_TIERS = ("明显偏低", "略低", "常见", "略高", "明显偏高")
LABELS = {"richness": ("偏少", "略少", "常见", "较丰富", "很丰富"),
          "shannon": ("偏少", "略少", "常见", "较丰富", "很丰富"),
          "evenness": ("较集中", "略集中", "常见", "较均衡", "很均衡"),
          "typicality": ("典型", "较典型", "略少见", "少见", "很少见")}
METRIC_LABELS = {"richness": "菌种数（丰富度）", "shannon": "综合多样性", "evenness": "分布均衡度"}
STAGES = (("复杂多糖降解", "拆解膳食纤维和淀粉", "fiber_stage"),
          ("乳酸利用", "转化中间产物", "lactate_stage"),
          ("丁酸合成", "生成丁酸", "butyrate_stage"))


def metric_tier(metric, percentile, borderline=False):
    return LABELS[metric][STANDARD_TIERS.index(tier(percentile, borderline))]


def typicality_phrase(percentile):
    phrase = percentile_phrase(percentile)
    direction = "更大" if phrase.startswith("高于") else "更小"
    return phrase.replace("高于", "比", 1).replace("低于", "比", 1).replace("参考人群", "健康人与人群差异" + direction)


def _concept(glossary, key):
    entry = glossary.get(key, kind="concept", chapter=2)
    return (entry["one_liner"] + entry.get("detail", "")) if entry else ""


def prepare(document):
    """Resolve shared G2/G4 data and record every hidden item through G6."""
    from .chapter_two import diversity_rows, qc_failed
    from .glossary import Glossary
    state = consumer(document)
    state.setdefault("raw_derived_observations", {key: copy.deepcopy(row) for key, row in document.get("evidence", {}).items()
                                               if key.startswith("word-observation-")})
    if "enzyme_markers" not in state and not qc_failed(document):
        from .consumer_markers import existing_enzyme_markers
        state["enzyme_markers"] = existing_enzyme_markers(document.get("sample_id", ""))
    glossary = Glossary(document)
    definitions = {key: _concept(glossary, key) for key in (
        "diversity", "richness", "shannon", "evenness", "functional_potential", "functional_backup", "typicality")}
    rows = []
    if not qc_failed(document):
        for row in diversity_rows(document):
            metric = row["metric"]
            if metric not in METRIC_LABELS:
                continue
            if metric == "richness" and not float(row["value"]).is_integer():
                omit(document, 2, "richness", "invalid_count", "菌种数记录不是有效整数")
                continue
            p = finite(row.get("percentile"))
            valid_p = p is not None and 0 <= p <= 100
            label = metric_tier(metric, p, row.get("borderline", False)) if valid_p else None
            value = count(row["value"]) + "种" if metric == "richness" else f"{row['value']:.2f}"
            color = "#66737C" if metric == "evenness" else "#B47A24" if label in {"偏少", "略少"} else "#267D79"
            rows.append({**row, "display_label": METRIC_LABELS[metric], "formatted_value": value,
                         "tier_label": label, "color": color})
            if not valid_p:
                omit(document, 2, "diversity_reference:" + metric, "reference_unavailable", "该指标缺少同口径参考比较")
    comparison = document.get("template_inputs", {}).get("healthy_comparison") or {}
    typicality = dict(comparison.get("typicality") or {})
    if typicality.get("status") == "available" and finite(typicality.get("percentile")) is not None and not qc_failed(document):
        typicality["tier"] = metric_tier("typicality", typicality["percentile"], typicality.get("borderline", False))
        typicality["phrase"] = typicality_phrase(typicality["percentile"])
        state["typicality"] = typicality
    else:
        state.pop("typicality", None)
        typicality = None
        omit(document, 2, "typicality", "derived_reference_unavailable", "组成典型度参考资产不可用，保留可用的组成示意图")
    categories = {}
    stages = []
    glossary_entries = list(glossary.curated.values())
    for category_name, title, meaning_key in STAGES:
        aggregate = aggregate_category(document, category_name) if not qc_failed(document) else {
            "category": category_name, "status": "missing", "pathways": [], "per_pathway": [], "contributors": [], "named_count": 0,
            "top_named_share": None, "unknown_share": None, "denominator": None, "unit_consistent": True, "complete": False}
        categories[category_name] = aggregate
        record_function_consistency(document, category_name, aggregate, glossary_entries)
        if aggregate["status"] != "available" or not aggregate["unit_consistent"]:
            omit(document, 2, "stage:" + category_name,
                 "incompatible_units" if not aggregate["unit_consistent"] else "no_named_gene_contributors",
                 "各项计量单位不同，细节分开列于附录" if not aggregate["unit_consistent"] else "现有基因注释没有可核对的参与菌记录")
            continue
        named = [r for r in aggregate["contributors"] if r["name"] != "未分类贡献"]
        top = aggregate["top_named_share"]
        thresholds = FUNCTION_BACKUP
        backup = ("多种菌分担" if len(named) >= thresholds["minimum_named_contributors"] and top is not None and top < thresholds["top_share_percent"]
                  else "主要依赖少数菌" if len(named) < thresholds["minimum_named_contributors"] or top is not None and top >= thresholds["top_share_percent"] else None)
        stages.append({"category": category_name, "title": title, "members": named,
                       "backup": backup, "meaning": _concept(glossary, meaning_key), "complete": aggregate["complete"]})
    omit(document, 2, "functional_population_percentile", "functional_reference_not_implemented", "尚未建立可比较的功能人群分布")
    payload = {"diversity": rows, "definitions": definitions, "typicality": typicality,
               "categories": categories, "stages": stages,
               "topic_mapping": {"word.2.3": ["word.2.3", "word.2.4"]},
               "sequencing_depth_warning": bool(comparison.get("audit", {}).get("sequencing_depth", {}).get("warnings"))}
    state["chapter_two"] = payload
    return payload


def fallback(document, subsection):
    data = prepare(document)
    if subsection == 1:
        rows = {r["metric"]: r for r in data["diversity"]}
        richness, evenness = rows.get("richness"), rows.get("evenness")
        if not richness:
            return ""
        text = f"您的菌群检出{count(richness['value'])}种菌"
        if richness["tier_label"]:
            text += "，种类" + richness["tier_label"]
        if evenness and evenness["tier_label"]:
            text += "；各种菌之间分布" + evenness["tier_label"]
        return text + "。"
    if subsection == 2:
        row = data["typicality"]
        return f"从整体组成看，您的菌群在健康人群中属于{row['tier']}，{row['phrase']}。" if row else ""
    parts = []
    for stage in data["stages"]:
        if stage["backup"] == "多种菌分担":
            parts.append(stage["title"] + "具备由多种菌分担的潜力")
        elif stage["backup"]:
            parts.append(stage["title"] + "的潜力主要见于少数菌")
    return "；".join(parts) + "。" if parts else ""


def displayed_values(document, subsection):
    data = prepare(document)
    if subsection == 1:
        return [r["formatted_value"].removesuffix("种") for r in data["diversity"]]
    if subsection == 2 and data["typicality"]:
        return re.findall(r"\d+%", data["typicality"]["phrase"])
    return []


def text_error(text, subsection):
    if re.search(r"PCoA|Bray.Curtis|Lingoes|PWY-|P163|CENTFERM|通路丰度|分层|已注释分类单元|未建立功能参考分布|Simpson|Pielou|Shannon|\de-\d|肠道生态失衡|菌群紊乱|仅由|只由|功能[强弱]|产生了", text, re.I):
        return "consumer_ch2_unsupported_language"
    if subsection == 1 and len(re.findall(r"\d+(?:\.\d+)?%?", text)) > 1:
        return "consumer_ch2_too_many_numbers"
    return None


def interpretation(document, subsection):
    from .narrative import consumer_text_error
    topic = next((t for s in document.get("word_sections", []) for t in s["topics"]
                  if t["id"] == f"word.2.{subsection}"), {})
    value = topic.get("interpretation", "")
    if value and consumer_text_error(value, displayed_values(document, subsection)) is None and text_error(value, subsection) is None:
        return value
    return fallback(document, subsection)


def _name(document, member, registry):
    from .chapter_two import display_name
    latin = taxon_name(member["taxon"])
    return registry.name({"species": latin, "name": latin, "display_label": display_name(document, member["taxon"])})


def graph_seeds(document, subsection):
    if subsection == 1:
        return ["多样性", "丰富度", "均衡度", "diversity", "richness", "evenness", "Shannon index"]
    if subsection == 2:
        return ["组成典型度", "菌群组成", "健康人群", "多样性", "microbiota", "diversity"]
    from .chapter_two import display_name
    data = prepare(document)
    seeds = []
    products = {"丁酸合成": ["丁酸", "butyrate"], "乳酸利用": ["乳酸", "lactate"],
                "复杂多糖降解": ["膳食纤维", "淀粉", "dietary fiber", "starch"]}
    for stage in data["stages"]:
        seeds.extend(products.get(stage["category"], []))
        for member in stage["members"][:3]:
            seeds.extend([taxon_name(member["taxon"]), display_name(document, member["taxon"])])
    return sorted(set(seeds))


def render(document):
    from .consumer_copy import CHAPTERS, EMPTY_SECTION
    from .consumer_basis import comparison_basis_note
    from .knowledge_graph import subsection_graph_markdown
    data = prepare(document)
    copy = CHAPTERS[2]
    output = ["## 2 " + copy["title"], copy["intro"], "### 2.1 " + copy["subsections"][1]]
    definitions = data["definitions"]
    for key, title in [("diversity", "多样性"), ("richness", "丰富度（菌种数）"),
                       ("shannon", "综合多样性（Shannon 指数）"), ("evenness", "均衡度")]:
        if definitions[key]:
            output.append("> " + title + "：" + definitions[key])
    figure = document.get("word_figures", {}).get("2.1.1")
    if figure:
        output.append("![菌的种类和分布](" + figure["filename"] + ")")
    for row in data["diversity"]:
        if row.get("percentile") is None or not figure:
            output.append(row["display_label"] + "：" + row["formatted_value"] + ("，" + row["tier_label"] if row["tier_label"] else "") + "。")
    if data["sequencing_depth_warning"] and any(r["metric"] == "richness" for r in data["diversity"]):
        output.append("> 菌种数会受测序量影响，仅供参考。")
    note = comparison_basis_note(document, 2)
    if note:
        output.append("> " + note)
    summary = interpretation(document, 1)
    if summary:
        output.append(summary)
    output.extend(subsection_graph_markdown(document, 2, 1, graph_seeds(document, 1)))
    output.append("### 2.2 " + copy["subsections"][2])
    if definitions["typicality"]:
        output.append("> 组成典型度：" + definitions["typicality"])
    if data["typicality"]:
        output.append("**" + data["typicality"]["tier"] + "**  " + data["typicality"]["phrase"] + "。")
    figure = document.get("word_figures", {}).get("2.2.1")
    if figure:
        output.extend(["![您的菌群组成示意图](" + figure["filename"] + ")",
                       "> 每个点代表一位健康成人，◆代表您；点越接近，菌群组成越相似。平面图只是近似示意。"])
    summary = interpretation(document, 2)
    if summary:
        output.append(summary)
    output.extend(subsection_graph_markdown(document, 2, 2, graph_seeds(document, 2)))
    output.append("### 2.3 " + copy["subsections"][3])
    if not data["stages"]:
        output.append(EMPTY_SECTION)
        output.extend(subsection_graph_markdown(document, 2, 3, []))
        return output
    for key, title in [("functional_potential", "功能潜力"), ("functional_backup", "功能备份")]:
        if definitions[key]:
            output.append("> " + title + "：" + definitions[key])
    figure = document.get("word_figures", {}).get("2.3.1")
    if figure:
        output.extend(["图 2-3  食物在肠道里的接力", "![食物在肠道里的接力](" + figure["filename"] + ")"])
    else:
        registry = NameRegistry(document)
        registry.seen.update(consumer(document).get("names_seen", []))
        for stage in data["stages"]:
            names = "、".join(_name(document, member, registry) for member in stage["members"][:3])
            if len(stage["members"]) > 3:
                names += f"等{len(stage['members'])}种"
            output.append(stage["title"] + "：本样本中参与的菌有" + names +
                          ("，" + stage["backup"] if stage["backup"] else "") + "。" + stage["meaning"])
    output.extend(["> 以上为基因层面的功能潜力，不代表实际产量；箭头表示一般的代谢顺序。", interpretation(document, 3)])
    output.extend(subsection_graph_markdown(document, 2, 3, graph_seeds(document, 3)))
    return [line for line in output if line]


def draw_scatter(payload, width=1800):
    from .word_figures import _font, _text
    points = payload.get("points", [])
    image = Image.new("RGB", (width, 530), "white")
    draw = ImageDraw.Draw(image, "RGBA")
    if not points:
        return image
    low_x, high_x = min(p["x"] for p in points), max(p["x"] for p in points)
    low_y, high_y = min(p["y"] for p in points), max(p["y"] for p in points)
    for point in sorted(points, key=lambda p: bool(p.get("is_sample"))):
        x = 70 + (width-150) * (point["x"]-low_x) / max(high_x-low_x, 1e-12)
        y = 460 - 380 * (point["y"]-low_y) / max(high_y-low_y, 1e-12)
        if point.get("is_sample"):
            draw.polygon([(x,y-17),(x+17,y),(x,y+17),(x-17,y)],fill="#174E56")
            _text(draw,(min(x+28,width-85),y-17),"您",_font(32),fill="#174E56")
        else:
            draw.ellipse((x-5,y-5,x+5,y+5), fill=(121,169,165,100))
    return image


def draw_stages(document, stages, width=1800):
    from .word_figures import _font, _text
    image = Image.new("RGB", (width, 440), "white")
    draw = ImageDraw.Draw(image)
    registry = NameRegistry(document)
    registry.seen.update(consumer(document).get("names_seen", []))
    first = consumer(document).get("chapters", {}).get("1", {})
    registry.mark([r for key in ("phyla", "genera", "species", "reference_rows") for r in first.get(key, [])])
    n = len(stages)
    if not n:
        return image
    box_width = (width-60-50*(n-1))/n
    for index, stage in enumerate(stages):
        x = 30 + index*(box_width+50)
        draw.rounded_rectangle((x,15,x+box_width,420),radius=18,fill="#F0F7F5",outline="#CCE0DA",width=2)
        _text(draw,(x+22,38),stage["title"],_font(31),fill="#205D63",width=box_width-44,max_lines=2)
        members = stage["members"]
        displayed = [_name(document,r,registry) for r in members[:3]]
        names = "、".join(value.split("（*")[0] for value in displayed)
        if len(members)>3:
            names += f"等{len(members)}种"
        _text(draw,(x+22,119),"本样本中参与的菌："+names,_font(27),width=box_width-44,max_lines=3)
        latins = [re.search(r"（\*(.*?)\*）", value).group(1) for value in displayed if "（*" in value]
        if latins:
            from .consumer_chapter import _latin
            _latin(draw,(x+22,216)," / ".join(latins),20,box_width-44)
        if stage["backup"]:
            _text(draw,(x+22,270),stage["backup"],_font(29),fill="#276F6A",width=box_width-44,max_lines=1)
        _text(draw,(x+22,324),stage["meaning"],_font(25),width=box_width-44,max_lines=3)
        if index<n-1:
            center=x+box_width+25
            draw.line((center-15,215,center+13,215),fill="#CFDFDD",width=6)
            draw.polygon([(center+17,215),(center+4,205),(center+4,225)],fill="#CFDFDD")
    return image


def render_figures(document, output, manifest):
    from .word_figures import draw_tier_scale
    data=prepare(document)
    images=[]
    rows=[r for r in data["diversity"] if finite(r.get("percentile")) is not None]
    if rows:
        images.append(("2.1.1",draw_tier_scale(rows),{"rows":rows,"mode":"consumer_diversity"}))
    ordination=(document.get("template_inputs",{}).get("healthy_comparison") or {}).get("ordination") or {}
    if ordination.get("status")=="available":
        images.append(("2.2.1",draw_scatter(ordination),{"mode":"consumer_composition","technical":ordination}))
    else:
        omit(document,2,"composition_scatter","ordination_unavailable","组成示意图所需数据不可用")
    if data["stages"]:
        images.append(("2.3.1",draw_stages(document,data["stages"]),{"mode":"consumer_function_stages","categories":data["categories"],"origin_ids":["2.3.1","2.4.flow"]}))
    figures={}
    for key,image,payload in images:
        buffer=io.BytesIO();image.save(buffer,format="PNG",optimize=True);encoded=buffer.getvalue()
        filename=f"{document['sample_id']}_consumer_{key.replace('.','_')}_{hashlib.sha256(encoded).hexdigest()[:20]}.png"
        (Path(output)/filename).write_bytes(encoded)
        manifest[key]={"filename":filename,"items":[{"id":key,"data":payload}],"width":image.width,"height":image.height}
        figures[key]=filename
    return figures


def appendix(document):
    from .document import table
    from .chapter_two import diversity_rows
    data=prepare(document)
    output=["#### 多样性明细",table(["指标","独立比较谱","主分析","P5–P95","经验百分位","参考人数"],
        [[r["label"],str(r["value"]),str(r.get("primary_value")),f"{r.get('p5')}–{r.get('p95')}",str(r.get("percentile")),str(r.get("n_subjects",r.get("n_reference")))] for r in diversity_rows(document)])]
    comparison=document.get("template_inputs",{}).get("healthy_comparison") or {}
    output.extend(["#### 组成比较明细",table(["项目","原始记录"],[[k,str(v)] for k,v in (data["typicality"] or comparison.get("typicality") or {}).items() if k!="_distribution"])])
    ordination=comparison.get("ordination") or {}
    output.append(table(["图示方法","原始记录"],[[k,str(ordination.get(k))] for k in ["method","correction","reference_sampling","n_reference","n_reference_total","distance_summary","explained_variance"]]))
    if ordination.get("n_reference_total",0)>ordination.get("n_reference",0):
        output.append(f"散点图使用固定的{ordination['n_reference']}人绘图子集；图示距离摘要属于这一子集，组成典型度使用全部{ordination['n_reference_total']}名合格参考。")
    output.append("#### 功能明细")
    output.append("各类别纳入全部命中通路；仅在单位一致时合计物种贡献，以已记录分层贡献总和（含未分类）为分母。通路贡献和酶标记数量不混加。")
    rows=[]
    for category_name,result in data["categories"].items():
        for item in result["per_pathway"]:
            pathway,summary=item["pathway"],item["summary"]
            members=summary["members"]
            description="群落通路总量（不作贡献分母）"
            if not members:
                description += "；" + summary.get("reason", "无物种分层记录")
            rows.append([category_name,pathway.get("id"),pathway.get("name",pathway.get("label")),str(pathway.get("value",pathway.get("abundance"))),pathway.get("unit"),description,"—"])
            for member in members:
                rows.append([category_name,pathway.get("id"),pathway.get("name",pathway.get("label")),str(member["value"]),pathway.get("unit"),member["name"],str(member["share"])])
            if not members:
                for member in pathway.get("contributors", []):
                    if not isinstance(member, dict):
                        continue
                    value=finite(member.get("abundance", member.get("value")))
                    rows.append([category_name,pathway.get("id"),pathway.get("name",pathway.get("label")),str(value) if value is not None else "数值不可用",
                                 member.get("unit",pathway.get("unit")),taxon_name(member.get("taxon") or member.get("species") or member.get("name")),"未合并计算"])
    output.append(table(["功能类别","通路ID","通路名称","原始丰度","单位","贡献者","通路内占比%"],rows))
    output.append("#### 类别合并结果")
    output.append(table(["类别","贡献者","类别内占比%","未分类贡献%","记录覆盖"],
        [[category_name, member["name"], str(member["share"]) if member["share"] is not None else
          "仅酶标记，无通路占比" if member.get("enzyme_markers") else "单位不同，未合并",
          str(result["unknown_share"]), "完整记录" if result["complete"] else "部分记录"]
         for category_name,result in data["categories"].items() for member in result["contributors"]]))
    markers=consumer(document).get("enzyme_markers") or {}
    if markers.get("status")=="available":
        output.append("#### 关键酶补充证据")
        output.append("酶标记补充者的通路级占比未知，列在已有通路占比的贡献者之后；酶标记丰度不混入通路分母，也不证明完整通路或实际酶活。")
        output.append(table(["EC编号","贡献者","标记原始丰度","单位","证据类型"],
            [[r["ec_number"],taxon_name(m["taxon"]),str(m["abundance"]),m["unit"],"enzyme_marker"]
             for r in markers.get("results",[]) for m in r.get("contributors",[])]))
        output.append("现有UniRef输入SHA256："+markers.get("source_sha256","")+"；EC映射SHA256："+markers.get("mapping_audit",{}).get("sha256","")+"。")
        output.append("已隔离非标准输入行："+str(markers.get("input_audit",{}).get("quarantined_rows",0))+"；这些行未参与任何功能计量，标记缺失不作阴性结论。")
    if consumer(document).get("function_consistency"):
        output.append("基因注释可能遗漏部分菌。")
        output.append(table(["记录类型","类别","物种","样本丰度%"],[[r["type"],r["category"],r["species"],str(r["abundance"])] for r in consumer(document)["function_consistency"]]))
    return output
