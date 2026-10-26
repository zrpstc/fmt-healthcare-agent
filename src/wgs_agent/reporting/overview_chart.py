"""Display sample bars, full-cohort reference intervals and traceable taxon names."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .inputs import finite
from .overview import select_findings
from .taxon_labels import FALLBACK, display_taxon, translate_overview_taxa

VERSION = "overview-reference-distribution-v2"
SAMPLE_COLOR = "#E66B24"
REFERENCE_COLOR = "#2675B8"
MEDIAN_COLOR = "#143F69"


def overview_items(document):
    items = []
    for finding in select_findings(document):
        row = document["evidence"][finding["evidence_id"]]
        is_taxon = row.get("kind") in {"species", "healthy_species", "pathogen"}
        display = display_taxon(document, row) if is_taxon else {"label": row["label"], "original": row["label"]}
        value, median = finite(row.get("value")), finite(row.get("reference_median"))
        p5, p95 = finite(row.get("p5")), finite(row.get("p95"))
        unit = row.get("unit")
        comparable = (row.get("comparison") in {"above", "below", "within"}
                      and value is not None and value >= 0 and median is not None and median >= 0
                      and bool(unit) and unit != "未提供")
        interval = comparable and p5 is not None and p95 is not None and 0 <= p5 <= median <= p95
        if comparable:
            direction = "高于" if value > median else "低于" if value < median else "等于"
            comparison = direction + "对照总体中位数"
            if median > 0:
                comparison += f"（{value / median:.3g} 倍）"
            else:
                comparison += "（总体中位数为 0，不计算倍数）"
        else:
            comparison = "未提供可比中位数，不绘制对照条形"
        n = finite(row.get("n_subjects", row.get("n_reference")))
        detected = finite(row.get("n_detected"))
        counts_valid = (n is not None and detected is not None and n > 0 and n.is_integer()
                        and detected.is_integer() and 0 <= detected <= n)
        positive_median = finite(row.get("reference_detected_median"))
        if positive_median is not None and positive_median <= 0:
            positive_median = None
        items.append({"evidence_id": finding["evidence_id"], "label": display["label"],
                      "original": display["original"], "is_taxon": is_taxon,
                      "value": value, "reference_median": median, "unit": unit,
                      "comparable": comparable, "reference_interval_available": interval,
                      "comparison": comparison, "priority": finding["priority"], "source": finding["source"],
                      "result_text": row["result_text"], "finding": finding["finding"],
                      "reason": finding["reason"], "p5": p5, "p95": p95,
                      "n_reference": int(n) if counts_valid else None,
                      "n_detected": int(detected) if counts_valid else None,
                      "n_zero": int(n-detected) if counts_valid else None,
                      "detection_rate": detected/n if counts_valid else None,
                      "reference_detected_median": positive_median})
    return items


def render_overview_figure(document, output_dir):
    from PIL import Image, ImageDraw
    from .word_figures import _font, _text

    items = overview_items(document)
    if not items:
        document.pop("overview_chart", None)
        return {}
    width, row_height = 1800, 270
    height = 215 + row_height * len(items)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title, font, small = _font(37), _font(28), _font(24)
    heading = ("样式演示（合成数值） · 本次样本与参考分布"
               if document.get("metadata", {}).get("demonstration") is True
               else "重点发现 · 本次样本与参考人群分布")
    _text(draw, (40, 30), heading, title)
    for x, color, label in [(45, SAMPLE_COLOR, "本次样本"), (325, REFERENCE_COLOR, "对照 P5–P95")]:
        draw.rounded_rectangle((x, 86, x+48, 109), radius=4, fill=color)
        _text(draw, (x+65, 97), label, font, anchor="lm")
    draw.ellipse((680, 89, 698, 107), fill=MEDIAN_COLOR)
    _text(draw, (716, 97), "总体中位数（含未检出者）", font, anchor="lm")
    _text(draw, (width-45, 97), "各项目使用独立线性刻度", small, anchor="rm")
    for index, item in enumerate(items):
        y = 145 + index * row_height
        draw.rounded_rectangle((24, y, width-24, y+row_height-12), radius=14, fill="#F2F6FA")
        _text(draw, (45, y+24), f"{index+1}. {item['label']}", font, width=545, max_lines=2)
        if item["is_taxon"]:
            _text(draw, (45, y+110), item["original"].replace("_", " "), small, width=540, max_lines=2)
        _text(draw, (45, y+217), f"{item['priority']} · 第{item['source']}节", small)
        if not item["comparable"]:
            _text(draw, (625, y+45), item["result_text"], font, width=1100, max_lines=2)
            _text(draw, (625, y+125), item["comparison"], small, width=1100)
            continue
        left, span = 625, 820
        maximum = max(item["value"], item["reference_median"], item["p95"] or 0)
        def position(amount):
            return left + (span*amount/maximum if maximum else 0)
        # The sample and the reference band share one linear axis within a panel.
        for bar_y in [y+28, y+83]:
            draw.rounded_rectangle((left, bar_y, left+span, bar_y+30), radius=5, fill="#E0E7EF")
        if item["value"] > 0:
            draw.rectangle((left, y+28, position(item["value"]), y+58), fill=SAMPLE_COLOR)
        _text(draw, (left+span+25, y+43), f"{item['value']:.5g} {item['unit']}", font, anchor="lm")
        if item["reference_interval_available"] and item["p95"] > item["p5"]:
            draw.rectangle((position(item["p5"]), y+83, position(item["p95"]), y+113), fill=REFERENCE_COLOR)
        x = position(item["reference_median"])
        draw.line((x, y+77, x, y+119), fill=MEDIAN_COLOR, width=5)
        draw.ellipse((x-8, y+90, x+8, y+106), fill=MEDIAN_COLOR)
        _text(draw, (left+span+25, y+98), f"中位数 {item['reference_median']:.5g} {item['unit']}", small, anchor="lm")
        if item["reference_interval_available"]:
            direction = "高于参考 P95" if item["value"] > item["p95"] else "低于参考 P5" if item["value"] < item["p5"] else "位于参考区间"
            _text(draw, (625, y+137), f"对照 P5–P95：{item['p5']:.5g}–{item['p95']:.5g} {item['unit']} · {direction}", small, width=1100)
        else:
            _text(draw, (625, y+137), item["comparison"], small, width=1100)
        if item["n_reference"]:
            _text(draw, (625, y+178), f"对照检出 {item['n_detected']}/{item['n_reference']} 人（{100*item['detection_rate']:.1f}%）；未检出 {item['n_zero']} 人", small, width=1100)
        if item["reference_detected_median"] is not None and item["n_detected"]:
            _text(draw, (625, y+219), f"检出者中位数 {item['reference_detected_median']:.5g} {item['unit']}（仅 {item['n_detected']} 人，补充统计）", small, width=1100)
        elif item["reference_median"] == 0:
            _text(draw, (625, y+219), "总体中位数为 0，不计算倍数；参考区间仍按全体对照计算。", small, width=1100)
    _text(draw, (40, height-43), "总体统计保留真实的 0；检出者中位数仅为补充，不替代总体中位数或 P5–P95。", small)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = buffer.getvalue()
    filename = f"{document['sample_id']}_overview_{hashlib.sha256(encoded).hexdigest()[:20]}.png"
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / filename).write_bytes(encoded)
    document["overview_chart"] = {"version": VERSION, "filename": filename, "items": items,
                                  "sample_color": SAMPLE_COLOR, "reference_color": REFERENCE_COLOR,
                                  "reference_representation": "p5_p95_band_with_overall_median_marker",
                                  "width": width, "height": height}
    return {"overview": filename}


def render_overview_content(document):
    items = overview_items(document)
    figure = document.get("overview_chart", {})
    if figure.get("filename"):
        alt = "；".join(f"{item['label']}：{item['finding']} 第{item['source']}节" for item in items)
        alt = alt.replace("[", "［").replace("]", "］").replace("\n", " ").replace("\r", " ")
        return [f"![检测结果总览：{alt}]({figure['filename']})"]
    result = []
    for item in items:
        original = f"（{item['original']}）" if item["is_taxon"] else ""
        detail = (f"本次 {item['value']:.5g} {item['unit']}；对照总体中位数 {item['reference_median']:.5g} {item['unit']}；{item['comparison']}"
                  if item["comparable"] else f"{item['result_text']}；{item['comparison']}")
        result.append(f"- **{item['label']}**{original}：{detail}。{item['reason']}（第{item['source']}节）")
    return result
