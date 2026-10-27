"""Consistent metabolite targets, measured gene support and relative capacity charts."""
from __future__ import annotations

import math
import re

from .inputs import finite

HEADERS = ["目标产物", "主要代谢（合成或分解）路径", "主要贡献菌", "作为支持证据的检出基因"]
SCORE_NOTE = (
    "代谢能力相对评分采用已提供的功能通路参考百分位（0–100）；同一产物、同一方向对应多条通路时取均值。"
    "合成与分解分别展示，综合或方向未注明的通路单独列示；缺少有效参考评分时标记为未评分，不以零代替。"
    "该评分表示基因组功能潜力，不代表产物实测浓度或净生成量。表中仅列实际检出的基因证据，最多5种；不足3种时按实际数量列出。"
)


def _unique(values):
    result, seen = [], set()
    for value in values:
        value = str(value).strip()
        if value and value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
    return result


def target_groups(data, sub):
    from .word_template import _function_rows, contract, matching

    functions = [] if data.qc_failed else _function_rows(data, 8, sub)
    blocks = contract()["chapters"][7]["blocks"]
    labels = _unique(seed[0] for block in blocks if block["type"] == "table" and block["sub"] == sub for seed in block["rows"][1:])
    groups = []
    for label in labels:
        if "其他" in label:
            rows = [row for row in functions if not any(matching([row], other) for other in labels if "其他" not in other)]
            # Name additional targets from their actual observations, rather than
            # plotting an undifferentiated catch-all metabolite.
            for row in rows:
                name = row.get("target_product") or row.get("target") or row.get("label") or row.get("name")
                if name:
                    groups.append((str(name), [row]))
        else:
            groups.append((label, matching(functions, label)))
    combined = {}
    for label, rows in groups:
        combined.setdefault(label, []).extend(row for row in rows if not any(row is old for old in combined[label]))
    return list(combined.items())


def _direction(row):
    from .word_template import _direction as direction
    value = direction(row)
    if value == "generation":
        return "合成"
    if value in {"use", "utilization", "consumption", "degradation"}:
        return "分解"
    return "综合/方向未注明"


def _paths(rows):
    result = []
    for row in rows:
        paths = row.get("main_pathways") or row.get("pathways") or row.get("pathway")
        if not isinstance(paths, list):
            paths = [paths] if paths else [row]
        for path in paths:
            if isinstance(path, dict):
                label = path.get("pathway_name") or path.get("label") or path.get("name") or path.get("pathway_id") or path.get("id")
                direction = _direction(path)
                if direction == "综合/方向未注明":
                    direction = _direction(row)
            else:
                label, direction = str(path), _direction(row)
            if label:
                result.append(f"{label}（{direction}）")
    return "；".join(_unique(result)[:5]) or "未提供对应通路证据"


def _contributors(rows):
    ranked, direct = {}, []
    for row in rows:
        for field in ("contributing_taxa", "contributor", "contributor_taxa", "contributing_species", "major_contributors", "main_contributors"):
            value = row.get(field)
            if isinstance(value, str):
                direct.extend(re.split(r"[；;、]", value))
            elif isinstance(value, list):
                direct.extend(v for v in value if isinstance(v, str))
        for member in row.get("contributors") or []:
            if not isinstance(member, dict):
                continue
            name = member.get("species") or member.get("taxon") or member.get("name")
            if not name or member.get("detected") is False:
                continue
            amount = finite(member.get("abundance", member.get("value")))
            if amount is not None and amount <= 0:
                continue
            name = str(name)
            if name.casefold() in {"unclassified", "unmapped", "unknown", "unassigned"}:
                continue
            ranked[name] = max(ranked.get(name, 0), amount or 0)
    names = [name for name in sorted(ranked, key=lambda name: -ranked[name])]
    return "；".join(_unique(names + direct)[:5]) or "未提供菌种分层贡献证据"


def detected_genes(rows):
    genes = []
    negative = {"not_detected", "negative", "missing", "absent", "not detected", "未检出"}

    def collect(value, declared_detected=False):
        if isinstance(value, list):
            for item in value:
                collect(item, declared_detected)
        elif isinstance(value, dict):
            if value.get("detected") is False or str(value.get("status", value.get("detection_status", ""))).lower() in negative:
                return
            measurements = [finite(value.get(key)) for key in ("abundance", "value", "reads", "read_count", "hits", "coverage") if key in value]
            if measurements and not any(v is not None and v > 0 for v in measurements):
                return
            supported = declared_detected or value.get("detected") is True or str(value.get("status", value.get("detection_status", ""))).lower() in {"detected", "positive", "present"} or any(v is not None and v > 0 for v in measurements)
            name = value.get("gene") or value.get("gene_name") or value.get("gene_symbol") or value.get("name") or value.get("id")
            if name and supported:
                collect(str(name), True)
        elif isinstance(value, str) and declared_detected:
            for symbol in re.split(r"[\s,;；、|]+", value.strip()):
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,39}", symbol) and symbol.lower() not in {"none", "unknown", "missing", "unclassified", "na"}:
                    genes.append(symbol)

    for row in rows:
        if row.get("detected") is False or str(row.get("detection_status", row.get("status", ""))).lower() in negative:
            continue
        for field in ("detected_genes", "detected_gene_names", "detected_gene_symbols"):
            collect(row.get(field), True)
        direct_support = row.get("detected") is True or any((finite(row.get(key)) or 0) > 0 for key in ("reads", "read_count", "hits"))
        for field in ("genes", "supporting_genes", "gene_evidence", "gene_annotations", "gene_hits", "gene", "gene_symbols"):
            collect(row.get(field), direct_support)
    return _unique(genes)[:5]


def table_rows(document, sub, data=None, labels=None):
    from .word_template import Data
    data = data or Data(document)
    groups = target_groups(data, sub)
    if labels is not None:
        groups = [(label, rows) for label, rows in groups if label in labels or any("其他" in str(seed) for seed in labels)]
    result = []
    for label, rows in groups:
        genes = detected_genes(rows)
        result.append([label, _paths(rows), _contributors(rows), "、".join(genes) if genes else "未提供检出基因证据"])
    return result


def chart_payload(document, spec):
    from .word_figures import _percentile
    from .word_template import Data

    sub = int(spec["id"].split(".")[1])
    data = Data(document)
    groups = target_groups(data, sub)
    modes = ("合成", "分解", "综合/方向未注明")
    series = []
    for mode in modes:
        values = []
        for _, rows in groups:
            scores = [_percentile(row) for row in rows if _direction(row) == mode] if not data.qc_failed else []
            valid = [score for score in scores if score is not None]
            values.append(math.fsum(valid) / len(valid) if valid else None)
        if any(value is not None for value in values):
            series.append({"name": mode, "values": values})
    if not series:
        series = [{"name": "代谢能力相对评分", "values": [None] * len(groups)}]
    return {
        "chapter_eight_mode": True,
        "labels": [label for label, _ in groups],
        "series": series,
        "unit": "代谢能力相对评分（0–100）",
        "scale_min": 0,
        "scale_max": 100,
        "status": "available" if any(v is not None for item in series for v in item["values"]) else "missing",
        "reason": "质控未通过" if data.qc_failed else "未提供有效参考评分",
        "method": "同一目标产物、同一方向的功能通路参考百分位算术平均",
    }


def draw_chart(payload, width):
    from PIL import Image, ImageDraw
    from .word_figures import _font, _text

    labels = payload["labels"] or ["暂无目标产物"]
    series = payload["series"]
    font = _font(max(25, int(width / 64)))
    small = _font(max(22, int(width / 78)))
    row_height = max(92, len(series) * (small.size + 12) + 22)
    top, footer = 70, 125
    height = top + row_height * len(labels) + footer
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    left, right = int(width * .30), int(width * .91)
    colors = ["#247A94", "#DB9960", "#747FA4"]
    for tick in range(0, 101, 25):
        x = left + (right - left) * tick / 100
        draw.line((x, top - 12, x, height - footer + 6), fill="#E4E9EE", width=2)
        draw.text((x, height - footer + 16), str(tick), font=small, fill="#485569", anchor="mt")
    for index, label in enumerate(labels):
        cy = top + (index + .5) * row_height
        _text(draw, (left - 20, cy - font.size), label, font, width=left - 35, anchor="ra", max_lines=2)
        for j, item in enumerate(series):
            y = cy + (j - (len(series) - 1) / 2) * (small.size + 12)
            value = item["values"][index] if index < len(item["values"]) else None
            if value is None:
                draw.text((left + 12, y), "未评分", font=small, fill="#8792A2", anchor="lm")
                continue
            end = left + (right - left) * value / 100
            if value > 0:
                draw.rounded_rectangle((left, y - small.size * .35, end, y + small.size * .35), radius=3, fill=colors[j % len(colors)])
            else:
                draw.line((left, y-small.size*.35, left, y+small.size*.35), fill=colors[j % len(colors)], width=3)
            draw.text((end + 10, y), f"{value:.1f}", font=small, fill="#334155", anchor="lm")
    y = height - 62
    x = int(width * .08)
    for j, item in enumerate(series):
        draw.rectangle((x, y, x + 18, y + 18), fill=colors[j % len(colors)])
        draw.text((x + 27, y - 4), item["name"], font=small, fill="#334155")
        x += int(draw.textlength(item["name"], font=small)) + 80
    draw.text((width / 2, 16), payload["unit"], font=font, fill="#334155", anchor="mt")
    return image
