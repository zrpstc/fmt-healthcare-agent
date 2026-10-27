"""Chapter-one charts with explicit percentages, translated labels and reference details."""
from __future__ import annotations
import re
import math
from PIL import Image, ImageDraw
from .inputs import finite
from .reference import species_key
from .taxon_labels import display_taxon, translate_overview_taxa

VERSION = "chapter-one-labeled-charts-v1"
TARGETS = {"1.1.1", "1.1.2", "1.1.3", "1.2.1", "1.4.1"}
LABEL_FIELD = "chapter_one_taxon_labels"


def _rows(document, kind, limit):
    from .word_template import Data
    data = Data(document)
    if data.qc_failed:
        return []
    return sorted([r for r in data.group(kind) if r.get("unit") == "%"
                   and finite(r.get("value")) is not None and r["value"] >= 0],
                  key=lambda r: -r["value"])[:limit]


def reference_rows(document):
    from .word_template import Data
    data = Data(document)
    if data.qc_failed:
        return []
    # Same eight entries formerly shown in table 1.4.t1, including unavailable comparisons.
    kind = "healthy_species" if data.inputs.get("healthy_comparison") else "species"
    return sorted(data.group(kind), key=lambda r: -(finite(r.get("value")) or 0))[:8]


def prepare_chapter_one(document, config, *, post=None, fallback_config=None):
    from .word_figures import chart_data
    rows = _rows(document, "tax_phylum", 5) + _rows(document, "tax_genus", 5)
    rows += _rows(document, "species", 6) + reference_rows(document)
    translate_overview_taxa(document, config, post=post, fallback_config=fallback_config,
                            rows=rows, label_field=LABEL_FIELD, audit_field="chapter_one_taxon_translation")
    core = chart_data(document, {"id":"1.2.2", "kind":"doughnutChart"})
    document["chapter_one_presentation"] = {
        "version": VERSION, "core_chart_visible": core["status"] == "available",
        "core_chart_reason": core.get("reason", ""),
        "removed_tables": ["1.1.t1", "1.2.t2", "1.4.t1"],
    }


def name(document, row):
    return display_taxon(document, row, label_field=LABEL_FIELD)["label"]


def scientific(row):
    original = str(row.get("species") or row.get("name") or row.get("label", ""))
    return re.sub(r"\s+ex\s+.*$", "", original, flags=re.I).replace("_", " ")


def translate_text(document, text):
    value = str(text)
    labels = document.get(LABEL_FIELD, {})
    for item in sorted(labels.values(), key=lambda d: -len(d["original"])):
        original = item["original"]
        value = re.sub(r"(?<![A-Za-z])" + re.escape(original) + r"(?![A-Za-z])",
                       lambda m: item["label"], value, flags=re.I)
    return value


def chart_payload(document, spec):
    from .word_figures import _dataset, _series
    ident = spec["id"]
    if ident == "1.4.1":
        rows = reference_rows(document)
        payload = _dataset([name(document,r) for r in rows], [
            _series("MHNO 独立谱" if any(r.get("kind")=="healthy_species" for r in rows) else "本次样本", [finite(r.get("value")) for r in rows]),
            _series("参考人群中位数", [finite(r.get("reference_median")) for r in rows])], "%")
        payload.update(chapter_one_mode="reference", rows=[{**r,"display_label":name(document,r),"scientific_label":scientific(r)} for r in rows])
        return payload
    kind = {"1.1.1":"tax_phylum", "1.1.2":"tax_genus", "1.1.3":"species", "1.2.1":"species"}[ident]
    rows = _rows(document, kind, 100000 if ident=="1.1.1" else 6 if ident=="1.2.1" else 5)
    if ident == "1.1.1":
        shown = [{**r,"display_label":name(document,r),"scientific_label":scientific(r)} for r in rows[:5]]
        remaining = math.fsum(r["value"] for r in rows[5:])
        if remaining > 0:
            shown.append({"display_label":"其余已记录类群","scientific_label":"","value":remaining})
        payload = _dataset(["本样本"], [_series(r["display_label"],[r["value"]]) for r in shown], "相对丰度（%）")
        payload.update(chapter_one_mode="phylum", rows=shown, recorded_total=math.fsum(r["value"] for r in rows))
        return payload
    payload = _dataset([name(document,r) for r in rows], [_series("相对丰度",[r["value"] for r in rows])], "%")
    payload.update(chapter_one_mode="bars", rows=[{**r,"display_label":name(document,r),"scientific_label":scientific(r)} for r in rows])
    return payload


def _label(draw, xy, text, size=28, **kwargs):
    from .word_figures import _font, _text
    _text(draw, xy, str(text), _font(size), **kwargs)


def _pct(value):
    return f"{value:.5g}%" if value is not None else "未提供"


def draw_chart(spec, payload, width):
    mode = payload["chapter_one_mode"]
    rows = payload["rows"]
    if mode == "reference":
        return _reference(payload, width)
    if mode == "phylum":
        return _phylum(payload, width)
    height = max(240, 100 + len(rows)*125)
    image = Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(image)
    color = "#" + spec["series"][0]["color"]
    if not rows:
        _label(draw,(35,70),"未提供可用的相对丰度结果",26)
        return image
    left, right = width*.46, width-145
    maximum = max(r["value"] for r in rows) or 1
    for index,row in enumerate(rows):
        y = 35+index*125
        _label(draw,(20,y),row["display_label"],28,width=left-40,max_lines=2)
        _label(draw,(20,y+76),row["scientific_label"],20,width=left-40,max_lines=1)
        end = left+(right-left)*row["value"]/maximum
        draw.rounded_rectangle((left,y+25,right,y+55),radius=4,fill="#EDF2F6")
        if row["value"]>0:draw.rectangle((left,y+25,end,y+55),fill=color)
        _label(draw,(end+12,y+40),_pct(row["value"]),26,anchor="lm")
    _label(draw,(width/2,height-35),"相对丰度（%）",24,anchor="mm")
    return image


def _phylum(payload,width):
    from .word_figures import PALETTE
    rows=payload["rows"];height=200+math.ceil(len(rows)/2)*74
    image=Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(image)
    if not rows:
        _label(draw,(35,60),"未提供门水平分类结果",28);return image
    left,right=45,width-45
    total=payload["recorded_total"]
    if total>100.001:
        _label(draw,(45,50),"门水平百分数合计超过100%，请核对输入口径",28);return image
    draw.rectangle((left,35,right,95),fill="#EDF2F6")
    position=left
    colors=["#246A73","#4A86A4","#8AB8C2","#B5D2CD","#C6B694","#E7E9EC"]
    for i,row in enumerate(rows):
        span=(right-left)*row["value"]/100
        color=colors[i%len(colors)]
        draw.rectangle((position,35,position+span,95),fill=color)
        if span>160:
            _label(draw,(position+span/2,65),_pct(row["value"]),27,fill="white" if i<2 else "#25333E",anchor="mm")
        position+=span
        x=45+(i%2)*(width/2);y=160+(i//2)*74
        draw.rectangle((x,y+8,x+26,y+34),fill=color)
        _label(draw,(x+42,y),row["display_label"]+"  "+_pct(row["value"]),28,width=width/2-80,max_lines=1)
        if row["scientific_label"]:_label(draw,(x+42,y+38),row["scientific_label"],20)
    for tick in [0,25,50,75,100]:
        x=left+(right-left)*tick/100
        draw.line((x,98,x,108),fill="#8795A2",width=2)
        _label(draw,(x,123),f"{tick}%",22,anchor="mm")
    _label(draw,(width-45,height-14),f"已记录门合计 {_pct(total)}",21,anchor="rm")
    return image


def _reference(payload,width):
    rows=payload["rows"];rowheight=215;height=100+rowheight*len(rows)
    image=Image.new("RGB",(width,max(height,240)),"white");draw=ImageDraw.Draw(image)
    if not rows:
        _label(draw,(35,70),"未提供可用于参考比较的物种结果",28);return image
    for x,color,text in [(35,"#E66B24",payload["series"][0]["name"]),(380,"#2675B8","参考 P5–P95")]:
        draw.rectangle((x,20,x+35,42),fill=color);_label(draw,(x+49,31),text,26,anchor="lm")
    _label(draw,(760,31),"深蓝标记：总体中位数；各行使用独立刻度",25,anchor="lm")
    for i,row in enumerate(rows):
        y=70+i*rowheight
        draw.rounded_rectangle((20,y,width-20,y+rowheight-10),radius=12,fill="#F2F6FA")
        _label(draw,(40,y+18),f"{i+1}. {row['display_label']}",30,width=505,max_lines=2)
        _label(draw,(40,y+108),row["scientific_label"],21,width=505,max_lines=2)
        if row.get("unit") != "%":
            _label(draw,(585,y+45),"本次："+str(row.get("result_text","未提供")),27)
            _label(draw,(585,y+110),"参考比较单位不足，未转换成百分比或发布高低判断。",25,width=width-630)
            continue
        value=finite(row.get("value"));median=finite(row.get("reference_median"));p5=finite(row.get("p5"));p95=finite(row.get("p95"))
        valid=all(v is not None and v>=0 for v in [value,median,p5,p95]) and p5<=median<=p95
        left,right=585,width-330;span=right-left
        maximum=max([v for v in [value,median,p95] if v is not None]+[1e-30])
        pos=lambda v:left+span*v/maximum
        draw.rounded_rectangle((left,y+25,right,y+53),radius=4,fill="#E0E7EF")
        if value is not None and value>=0:
            if value>0:draw.rectangle((left,y+25,pos(value),y+53),fill="#E66B24")
        _label(draw,(right+20,y+39),"本次 "+_pct(value),27,anchor="lm")
        if valid:
            draw.rounded_rectangle((left,y+82,right,y+110),radius=4,fill="#E0E7EF")
            if p95>p5:draw.rectangle((pos(p5),y+82,pos(p95),y+110),fill="#2675B8")
            mx=pos(median);draw.line((mx,y+76,mx,y+116),fill="#143F69",width=5)
            draw.ellipse((mx-7,y+89,mx+7,y+103),fill="#143F69")
            _label(draw,(right+20,y+96),"中位数 "+_pct(median),26,anchor="lm")
            _label(draw,(585,y+130),f"参考 P5–P95：{p5:.5g}%–{p95:.5g}%",26)
            percentile=finite(row.get("percentile"));n=finite(row.get("n_subjects",row.get("n_reference")))
            detail=(f"经验百分位：{percentile:.1f}" if percentile is not None else "经验百分位：未提供")
            detail+=(f"；参考 n={int(n)}" if n is not None else "；参考人数未提供")
            direction={"above":"高于参考区间","below":"低于参考区间","within":"位于参考区间"}.get(row.get("comparison"),"暂不判定高低")
            _label(draw,(585,y+171),detail+"；"+direction,25,width=width-630,max_lines=1)
        else:
            _label(draw,(585,y+99),"参考中位数 "+_pct(median),26)
            _label(draw,(585,y+151),row.get("comparison_reason_cn") or "参考分布或比较条件不足，暂不判定高低",25,width=width-630,max_lines=1)
    _label(draw,(35,height-15),"丰度及区间均为百分比；经验百分位描述参考队列中的位置。",22,anchor="lm")
    return image
