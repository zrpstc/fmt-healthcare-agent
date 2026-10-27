"""Render every Word chart/flow from the compiled source and real sample data.

No example values from the DOCX enter this module. Shapes/colors originate in
DrawingML; each numeric panel has an explicit assay/unit/denominator binding.
"""

from __future__ import annotations
from .presentation_units import display_text

import hashlib
import io
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .fonts import resolve_cjk_fonts
from .inputs import finite
from .reference import species_key
from .template_catalog import CHAPTERS
from .word_template import (
    Data,
    _direction,
    _function_rows,
    _linked,
    _pick,
    contract,
    matching,
    redundancy_category,
    tables_for,
    valid_composites,
)

PALETTE = contract()["style"]["series"]


def _values(rows, field="value"):
    return [(r["label"], finite(r.get(field))) for r in rows]


def _dataset(labels=(), series=(), unit="", **extra):
    series = list(series)
    available = any(v is not None for s in series for v in s["values"])
    return {
        "labels": list(labels),
        "series": series,
        "unit": unit,
        "status": "available" if available else "missing",
        **extra,
    }


def _series(name, values):
    return {"name": name, "values": list(values)}


def _same_unit(rows):
    units = {r.get("unit") for r in rows if finite(r.get("value")) is not None}
    return next(iter(units)) if len(units) == 1 and None not in units and "" not in units else None


def _percentile(row):
    value = finite(row.get("percentile"))
    return (
        value
        if row.get("comparison") != "unknown" and value is not None and 0 <= value <= 100
        else None
    )


def _stack(rows, labeler, member="name"):
    labels = []
    values = []
    names = []
    for label, items in rows:
        if (
            not items
            or not _same_unit(items)
            or any(finite(r.get("value")) is None or r["value"] < 0 for r in items)
        ):
            continue
        total = math.fsum(r["value"] for r in items)
        if total <= 0:
            continue
        labels.append(label)
        values.append({labeler(r): 100 * r["value"] / total for r in items})
        names.extend(labeler(r) for r in items)
    names = list(dict.fromkeys(names))
    # Keep every denominator member; the final series collects remaining members.
    shown = names[:5]
    series = [_series(n, [r.get(n, 0) for r in values]) for n in shown]
    if len(names) > 5:
        series.append(
            _series(
                "其余已记录成员", [sum(v for k, v in r.items() if k not in shown) for r in values]
            )
        )
    return _dataset(labels, series, "已提供成员内部占比（%）")


def chart_data(document, spec):
    if spec.get("id") in {"3.1.1", "3.3.1"}:
        from .chapter_three import chart_payload
        return chart_payload(document, spec["id"])
    ident = spec["id"]
    chapter, sub = map(int, ident.split(".")[:2])
    if chapter == 10:
        from .chapter_ten import chart_payload
        return chart_payload(document, spec)
    if chapter == 8:
        from .chapter_eight import chart_payload
        return chart_payload(document, spec)
    if ident in {"2.1.1", "2.3.1"}:
        from .chapter_two import chart_payload
        return chart_payload(document, spec)
    data = Data(document)
    if data.qc_failed:
        return _dataset(reason="质控未通过，暂不展示结果")
    from .chapter_one import TARGETS, chart_payload
    if ident in TARGETS:
        return chart_payload(document, spec)
    if ident in {"1.1.1", "1.1.2", "1.1.3", "1.2.1"}:
        kind = {
            "1.1.1": "tax_phylum",
            "1.1.2": "tax_genus",
            "1.1.3": "species",
            "1.2.1": "species",
        }[ident]
        rows = sorted(
            [
                r
                for r in data.group(kind)
                if r.get("unit") == "%" and finite(r.get("value")) is not None and r["value"] >= 0
            ],
            key=lambda r: -r["value"],
        )
        if ident == "1.1.1":
            if not rows:
                return _dataset()
            shown = rows[:5]
            remaining = math.fsum(r["value"] for r in rows[5:])
            series = [_series(r["label"], [r["value"]]) for r in shown]
            if remaining:
                series.append(_series("其余已记录类群", [remaining]))
            return _dataset(["本样本"], series, "相对丰度（%）")
        rows = rows[: 6 if ident == "1.2.1" else 5]
        return _dataset(
            [r["label"] for r in rows], [_series("相对丰度", [r["value"] for r in rows])], "%"
        )
    if ident == "1.2.2":
        core = data.raw("core_microbiome", "members")
        module = data.inputs.get("core_microbiome") or {}
        species = {species_key(r.get("species") or r["label"]): r for r in data.group("species")}
        vals = [
            finite(
                r.get(
                    "value",
                    r.get(
                        "abundance",
                        species.get(species_key(_pick(r, "species", "name")), {}).get("value"),
                    ),
                )
            )
            for r in core
        ]
        unique = len({species_key(_pick(r, "species", "name")) for r in core}) == len(core)
        if (
            core
            and unique
            and module.get("definition")
            and all(v is not None and v >= 0 for v in vals)
        ):
            count = sum(v > 0 for v in vals)
            return _dataset(
                ["已检出核心菌群", "其余核心菌群"],
                [_series("检出数", [count, len(vals) - count])],
                "成员数",
                center=f"{count}/{len(vals)}",
            )
        return _dataset(reason="核心清单或检出记录不足")
    if spec["kind"] == "scatterChart":
        module = data.inputs.get("diversity") or {}
        key = "enterotype_ordination" if chapter == 1 else "ordination"
        payload = module.get(key) or {}
        if chapter == 2 and data.inputs.get("healthy_comparison"):
            payload = data.inputs["healthy_comparison"].get("ordination") or {}
        points = []
        for row in payload.get("points", []):
            if not isinstance(row, dict):
                continue
            x, y = finite(row.get("x")), finite(row.get("y"))
            if x is not None and y is not None:
                points.append({"x": x, "y": y, "group": str(row.get("group", "参考人群")), "sample": row.get("is_sample") is True})
        ready = bool(points) and any(p["sample"] for p in points) and any(not p["sample"] for p in points) and bool(payload.get("method"))
        return _dataset(
            points=points if ready else [], status="available" if ready else "missing",
            reason="未提供可核对的样本与参考人群降维坐标",
            axis_x=payload.get("axis_x", "PCoA 1"), axis_y=payload.get("axis_y", "PCoA 2"),
            method=payload.get("method"), n_reference=payload.get("n_reference"),
        )
    if ident == "1.4.1":
        mho = bool(data.inputs.get("healthy_comparison"))
        rows = sorted(
            [
                r
                for r in data.group("healthy_species" if mho else "species")
                if r.get("comparison") in {"above", "below", "within"} and r.get("unit") == "%"
            ],
            key=lambda r: (r.get("comparison") == "within", -(r.get("value") or 0)),
        )[:5]
        return _dataset(
            [r["label"] for r in rows],
            [
                _series("MHNO 独立谱" if mho else "本次样本", [finite(r.get("value")) for r in rows]),
                _series("参考人群中位数", [finite(r.get("reference_median")) for r in rows]),
            ],
            "%",
        )
    if ident == "2.1.1":
        if data.inputs.get("healthy_comparison"):
            rows = data.group("healthy_diversity")
            return _dataset(["MHNO · " + r["label"] for r in rows],
                            [_series("MHNO 独立谱经验百分位", [_percentile(r) for r in rows])],
                            "MHNO 经验百分位（0–100）")
        rows = data.group("div_richness", "div_shannon", "div_evenness")
        refs = data.group("div_reference")
        vals = []
        for key in ("richness", "richness_estimate", "evenness", "shannon"):
            r = next((r for r in rows if r["kind"] == "div_" + key), {})
            ref = next((v for v in refs if str(v.get("metric", "")).lower() == key), r)
            vals.append(_percentile(ref))
        return _dataset(
            ["观测物种数", "丰富度估计", "均匀度", "Shannon指数"],
            [_series("人群分位数", vals)],
            "人群分位数（0–100）",
        )
    if ident == "2.3.1":
        rows = []
        for r in data.group("function", "pathway"):
            if redundancy_category(r.get("label", "")) is None:
                continue
            if r.get("contributors_complete") is not True:
                continue
            items = [
                {
                    **v,
                    "label": str(_pick(v, "taxon", "species", "name")),
                    "value": finite(v.get("abundance")),
                    "unit": v.get("unit", r.get("unit")),
                }
                for v in r.get("contributors", [])
                if isinstance(v, dict)
            ]
            if items:
                rows.append((r["label"], items))
        return _stack(rows[:3], lambda r: r["label"])
    if ident == "3.1.1":
        data.load(3, 1)
        rows = data.topic_rows(*CHAPTERS[2][3][0][1])
        rows = [r for r in rows if r.get("unit") == "%"][:6]
        return _dataset(
            [r["label"] for r in rows],
            [
                _series("本次样本", [finite(r.get("value")) for r in rows]),
                _series(
                    "参考人群中位数",
                    [
                        finite(r.get("reference_median"))
                        if r.get("comparison") != "unknown"
                        else None
                        for r in rows
                    ],
                ),
            ],
            "%",
        )
    if ident == "3.3.1":
        data.load(3, 3)
        rows = data.topic_rows("key_taxa.opportunists", "key_taxa.pathogens")[:6]
        return _dataset(
            [r["label"] for r in rows],
            [_series("支持读段数", [finite(r.get("read_count", r.get("reads"))) for r in rows])],
            "读段数",
        )
    if ident == "5.2.1":
        rows = data.group("amr")
        unit = _same_unit(rows)
        if unit is None:
            return _dataset(reason="未提供统一单位的标准化耐药标记丰度")
        groups = {}
        for r in rows:
            # Multi-class markers cannot be counted into several totals.
            cat = r.get("drug_class")
            v = finite(r.get("value"))
            if (
                isinstance(cat, str)
                and not re.search(r"[,;；/|]", cat)
                and v is not None
                and v >= 0
            ):
                groups[cat] = groups.get(cat, 0) + v
        return _dataset(groups.keys(), [_series("标准化丰度", groups.values())], unit)
    if ident == "6.0.1":
        sets = []
        for module, label in (
            ("archaea", "古菌内部组成"),
            ("fungi", "真菌内部组成"),
            ("dna_viruses", "DNA病毒内部组成"),
        ):
            parent = data.inputs.get(module) or {}
            rows = [
                {
                    **r,
                    "label": str(_pick(r, "species", "name")),
                    "value": finite(r.get("value", r.get("abundance"))),
                    "unit": r.get("unit", parent.get("unit")),
                }
                for r in data.raw(module, "members", "species", "viruses")
            ]
            sets.append((label, rows))
        return _stack(sets, lambda r: r["label"])
    if ident == "7.1.1":
        rows = _function_rows(data, 7, 1)
        labels = ["抗性淀粉", "果胶", "菊粉", "木聚糖"]
        vals = [
            next(
                (_percentile(r) for r in matching(rows, label) if _percentile(r) is not None), None
            )
            for label in labels
        ]
        return _dataset(labels, [_series("人群分位数", vals)], "人群分位数（0–100）")
    if ident == "8.1.1":
        rows = _function_rows(data, 8, 1)
        return _stack(
            [
                (
                    label,
                    [r for r in matching(rows, label) if _direction(r) in {"generation", "both"}],
                )
                for label in ("乙酸", "丙酸", "丁酸")
            ],
            lambda r: r["label"],
        )
    if ident in {"8.5.1", "10.1.1"}:
        rows = _function_rows(data, chapter, sub)
        labels = (
            ["对甲酚", "组胺", "腐胺", "尸胺"]
            if chapter == 8
            else list(dict.fromkeys(r["label"] for r in rows))[:4]
        )
        series = []
        for mode, name in (("generation", "生成相关功能"), ("use", "利用或降解相关功能")):
            vals = []
            for label in labels:
                selected = (
                    matching(rows, label)
                    if chapter == 8
                    else [r for r in rows if r["label"] == label]
                )
                selected = [
                    r
                    for r in selected
                    if _direction(r) in {mode, "both"} and _percentile(r) is not None
                ]
                # Do not aggregate percentiles from different functions.
                vals.append(_percentile(selected[0]) if len(selected) == 1 else None)
            series.append(_series(name, vals))
        return _dataset(labels, series, "各功能各自的人群分位数（0–100）")
    if ident == "8.6.1":
        rows = _function_rows(data, 8, 6)
        unit = _same_unit(rows)
        if not unit:
            return _dataset(reason="未提供同口径气体代谢功能丰度")
        rows = rows[:5]
        return _dataset(
            [r["label"] for r in rows],
            [_series("功能丰度", [finite(r.get("value")) for r in rows])],
            unit,
        )
    if ident in {"14.4.1", "14.4.2"}:
        name = "综合健康分" if ident.endswith(".1") else "失衡分"
        row = next((r for r in valid_composites(data) if r.get("name") == name), None)
        if row:
            low, high = finite(row.get("scale_min")), finite(row.get("scale_max"))
            v = finite(row.get("value"))
            if low is not None and high is not None and low <= v <= high and high > low:
                return _dataset(
                    [name, "其余量尺"],
                    [_series(name, [v - low, high - v])],
                    str(row.get("unit", "")),
                    center=str(v),
                )
        return _dataset(reason="未启用：缺少量尺、验证或适用性")
    return _dataset()


def _wrap(draw, text, font, width, max_lines=3):
    lines = []
    line = ""
    for ch in str(text).replace("\n", " "):
        if line and draw.textlength(line + ch, font=font) > width:
            lines.append(line)
            line = ""
        line += ch
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _font(size):
    return ImageFont.truetype(resolve_cjk_fonts()[0], max(10, int(size)))


def _text(draw, xy, text, font, fill="#30343A", width=None, anchor="la", max_lines=3):
    text = display_text(text)
    lines = _wrap(draw, text, font, width, max_lines) if width else str(text).splitlines()
    step = font.size * 1.32
    for i, line in enumerate(lines):
        draw.text((xy[0], xy[1] + i * step), line, font=font, fill=fill, anchor=anchor)


def draw_chart(spec, payload, width):
    if payload.get("chapter_eight_mode"):
        from .chapter_eight import draw_chart as draw_chapter_eight
        return draw_chapter_eight(payload, width)
    if payload.get("chapter_three_mode"):
        from .chapter_three import draw_chart as draw_chapter_three
        return draw_chapter_three(payload, width)
    if payload.get("chapter_two_mode"):
        from .chapter_two import draw_chart as draw_chapter_two
        return draw_chapter_two(spec, payload, width)
    if payload.get("chapter_one_mode"):
        from .chapter_one import draw_chart as draw_chapter_chart
        return draw_chapter_chart(spec, payload, width)
    height = max(170, int(width * spec["extent"][1] / max(1, spec["extent"][0])))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(max(30, width / 58))
    small = _font(max(26, width / 70))
    colors = ["#" + s["color"] for s in spec["series"]] or ["#246A73"]
    if spec["kind"] == "doughnutChart":
        r = min(height * 0.33, width * 0.3)
        cx = width * 0.5
        cy = height * 0.43
        box = (cx - r, cy - r, cx + r, cy + r)
        vals = payload.get("series", [{}])[0].get("values", []) if payload.get("series") else []
        if payload["status"] == "available" and sum(vals) > 0:
            angle = -90
            for i, v in enumerate(vals):
                end = angle + 360 * v / sum(vals)
                color = "#246A73" if i == 0 else "#E7E9EC"
                draw.pieslice(box, angle, end, fill=color)
                angle = end
        else:
            draw.ellipse(box, fill="#E7E9EC")
        rr = r * 0.55
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill="white")
        _text(draw, (cx, cy - font.size * 0.5), payload.get("center", "未启用"), small, anchor="ma")
        _text(
            draw,
            (width * 0.5, height * 0.83),
            " / ".join(payload.get("labels", [])) or payload.get("reason", "未提供对应数据"),
            small,
            width=width * 0.95,
            anchor="ma",
            max_lines=2,
        )
        return image
    if spec["kind"] == "scatterChart":
        left, right, top, bottom = width * 0.12, width * 0.96, height * 0.1, height * 0.73
        draw.line((left, bottom, right, bottom), fill="#BEC5C8", width=1)
        draw.line((left, top, left, bottom), fill="#BEC5C8", width=1)
        points = payload.get("points", [])
        if points:
            xs = [p["x"] for p in points]
            ys = [p["y"] for p in points]
            xlo, xhi = min(xs), max(xs)
            ylo, yhi = min(ys), max(ys)
            groups = list(dict.fromkeys(p["group"] for p in points if not p["sample"]))
            for p in points:
                x = left + (right - left) * (0.08 + 0.84 * (p["x"] - xlo) / (xhi - xlo or 1))
                y = bottom - (bottom - top) * (0.08 + 0.84 * (p["y"] - ylo) / (yhi - ylo or 1))
                r = width * 0.005
                if p["sample"]:
                    draw.polygon(
                        [(x, y - r * 1.6), (x + r * 1.6, y), (x, y + r * 1.6), (x - r * 1.6, y)],
                        fill="#1F2937",
                    )
                else:
                    draw.ellipse(
                        (x - r, y - r, x + r, y + r),
                        fill=colors[groups.index(p["group"]) % max(1, len(colors) - 1)],
                    )
            legend = " · ".join(groups) + " ◆ 本次样本"
        else:
            _text(
                draw,
                ((left + right) / 2, (top + bottom) / 2),
                payload.get("reason", "未提供群落坐标"),
                font,
                width=right - left - 30,
                anchor="ma",
            )
            legend = "参考圆点与本次样本菱形仅在提供实际坐标后绘制"
        _text(draw, ((left + right) / 2, height * 0.79), payload.get("axis_x", '群落组成维度一'), small, anchor="ma")
        axis_label = payload.get("axis_y", '群落组成维度二')
        axis = Image.new(
            "RGB", (int(draw.textlength(axis_label, font=small) + 8), small.size * 2), "white"
        )
        ImageDraw.Draw(axis).text((4, 0), axis_label, font=small, fill="#606A70")
        axis = axis.rotate(90, expand=True)
        image.paste(axis, (int(width * 0.02), int((top + bottom - axis.height) / 2)))
        _text(
            draw,
            (width / 2, height * 0.9),
            legend,
            small,
            width=width * 0.95,
            anchor="ma",
            max_lines=2,
        )
        return image
    labels = (
        payload["labels"]
        or [
            re.sub(r"【[^】]*】", "对应项目", s)
            for s in spec["series"][0].get("categories", [])[:5]
        ]
        or ["本次结果"]
    )
    series = payload["series"]
    legend_rows = []
    if spec.get("legend", True):
        row = []
        used = 0
        for index, item in enumerate(series):
            label = item["name"]
            if item["values"] and all(v is None for v in item["values"]):
                label += "（未提供）"
            entry_width = min(width * 0.9, draw.textlength(label, font=small) + small.size * 2.2)
            if row and used + entry_width > width * 0.94:
                legend_rows.append(row)
                row = []
                used = 0
            color = colors[index] if index < len(colors) else "#" + PALETTE[index % len(PALETTE)]
            row.append((label, color, entry_width))
            used += entry_width
        if row:
            legend_rows.append(row)
    stacked = spec.get("grouping") in {"stacked", "percentStacked"}
    compact = stacked and len(labels) == 1
    left = width * 0.02 if compact else width * (0.4 if width < 1200 else 0.28)
    right = width * 0.98
    label_lines = [_wrap(draw, label, font, left - width * 0.04, 2) for label in labels]
    if not compact:
        needed = (
            len(labels) * (max(len(lines) for lines in label_lines) * font.size * 1.32 + 12) / 0.63
        )
        if needed > height:
            height = math.ceil(needed)
            image = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(image)
    if legend_rows:
        needed = math.ceil((len(legend_rows) * small.size * 1.3 + small.size * 1.3) / 0.25)
        if needed > height:
            height = needed
            image = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(image)
    top = height * 0.08
    bottom = height * 0.71
    ystep = (bottom - top) / len(labels)
    barh = min(
        ystep * (0.5 if len(series) <= 1 or stacked else 0.32),
        font.size * (1.65 if compact else 1.1),
    )
    maxval = max([v for s in series for v in s["values"] if v is not None] + [0]) or 1
    if stacked:
        maxval = max(
            [sum(s["values"][i] or 0 for s in series) for i in range(len(payload["labels"]))] + [1]
        )
    if "分位数" in payload.get("unit", ""):
        maxval = 100
    for i, label in enumerate(labels):
        cy = top + (i + 0.5) * ystep
        if not compact:
            lines = label_lines[i]
            for index, line in enumerate(lines):
                draw.text(
                    (left - width * 0.015, cy + (index - (len(lines) - 1) / 2) * font.size * 1.32),
                    line,
                    font=font,
                    fill="#30343A",
                    anchor="rm",
                )
        if not series:
            draw.rectangle(
                (left, cy - barh / 2, right, cy + barh / 2), fill="#F6F8F9", outline="#E2EDF0"
            )
            continue
        offset = left
        for j, s in enumerate(series):
            v = s["values"][i] if i < len(s["values"]) else None
            if v is None:
                continue
            y = (
                cy - barh / 2
                if stacked or len(series) == 1
                else cy + (j - (len(series) - 1) / 2) * barh * 1.1 - barh / 2
            )
            x = offset if stacked else left
            x2 = x + (right - left) * max(0, v) / maxval
            draw.rectangle(
                (x, y, x2, y + barh),
                fill=colors[j % len(colors)]
                if j < len(colors)
                else "#" + PALETTE[j % len(PALETTE)],
            )
            if stacked:
                offset = x2
    if payload["status"] != "available":
        _text(
            draw,
            ((left + right) / 2, (top + bottom) / 2),
            payload.get("reason", "未提供对应数据"),
            font,
            width=right - left - 20,
            anchor="ma",
            max_lines=2,
        )
    # Native palettes retained for every series; legends wrap instead of clipping.
    for row_index, row in enumerate(legend_rows):
        x = (width - sum(item[2] for item in row)) / 2
        y = height * 0.76 + row_index * small.size * 1.3
        for label, color, entry_width in row:
            side = small.size * 0.43
            draw.rectangle(
                (x, y + small.size * 0.4, x + side, y + small.size * 0.4 + side), fill=color
            )
            _text(
                draw,
                (x + small.size * 0.7, y),
                label,
                small,
                width=entry_width - small.size * 0.7,
                max_lines=1,
            )
            x += entry_width
    _text(
        draw,
        (width / 2, height - small.size * 1.6),
        payload.get("unit", "") or "未提供对应数据",
        small,
        fill="#606A70",
        anchor="ma",
    )
    return image


def flow_labels(document, spec):
    if spec["id"] == "2.4.flow":
        from .chapter_two import cooperation_payload
        return cooperation_payload(document)["labels"]
    chapter, sub = map(int, spec["id"].split(".")[:2])
    data = Data(document).load(chapter, sub)
    tables = tables_for(document, chapter, sub)
    rows = [r for _, rs in tables for r in rs]
    labels = []
    for shape in spec["shapes"]:
        if not shape["text"]:
            labels.append([])
            continue
        text = [re.sub(r"【[^】]*】", "未提供", line) for line in shape["text"]]
        labels.append(text)
    boxes = [i for i, s in enumerate(spec["shapes"]) if s["text"]]
    if data.qc_failed:
        for i in boxes:
            labels[i] = [labels[i][0], "质控未通过"]
        return labels
    if (chapter, sub) == (2, 4):
        for i, row in zip(boxes, rows):
            labels[i] = [str(row[0]), str(row[1]), str(row[2])]
    elif (chapter, sub) == (4, 3):
        markers = data.raw("virulence", "markers", "genes")
        if markers:
            r = markers[0]
            host, proof = _linked(r, "host")
            vals = [
                host,
                "已支持" if "未确定" not in host else "未确定",
                str(_pick(r, "gene", "marker", "name")),
            ]
            for i, v in zip(boxes, vals):
                labels[i] = [labels[i][0], v]
    elif (chapter, sub) == (5, 3):
        amr = data.group("amr")
        if amr:
            r = amr[0]
            vals = [r["label"], _linked(r, "mobile_element")[0], _linked(r, "host")[0]]
            for i, v in zip(boxes, vals):
                labels[i] = [labels[i][0], v]
    elif (chapter, sub) == (8, 2):
        fs = _function_rows(data, 8, 2)
        generation = [r for r in fs if _direction(r) in {"generation", "both"}]
        use = [r for r in fs if _direction(r) in {"use", "both"}]
        vals = [
            "；".join(r["label"] for r in generation) or "未提供生成路径",
            "乳酸 / 琥珀酸",
            "；".join(r["label"] for r in use) or "未提供利用路径",
        ]
        for i, v in zip(boxes, vals):
            labels[i] = [labels[i][0], v]
    elif (chapter, sub) == (8, 4):
        fs = _function_rows(data, 8, 4)
        if fs:
            labels[boxes[1]] = ["不同反应分支", "；".join(r["label"] for r in fs)]
    elif (chapter, sub) == (8, 7):
        fs = _function_rows(data, 8, 7)
        if fs:
            labels[boxes[1]] = ["独立反应路径", "；".join(r["label"] for r in fs)]
            labels[boxes[2]] = ["TMA生成潜力", "；".join(r["result_text"] for r in fs)]
    elif (chapter, sub) == (9, 1):
        for i in boxes:
            fs = [
                r
                for r in data.topic_rows(*CHAPTERS[8][3][0][1])
                if str(r.get("dimension", "")) in labels[i][0]
            ]
            if fs:
                labels[i] = [labels[i][0], "；".join(r["label"] for r in fs)]
    elif (chapter, sub) == (11, 2):
        if rows and rows[0][0] != "未提供":
            r = rows[0]
            vals = [r[2], r[1], r[3]]
            for i, v in zip(boxes, vals):
                labels[i] = [labels[i][0], str(v)]
    elif (chapter, sub) == (12, 1):
        ds = data.group("disease")
        models = data.group("prediction")
        vals = [
            "；".join(r["label"] for r in ds) or "未提供",
            "见本章关联证据" if ds else "未提供关联证据",
            "另列模型输出" if models else "模型未启用",
        ]
        for i, v in zip(boxes, vals):
            labels[i] = [labels[i][0], v]
    elif (chapter, sub) == (13, 1):
        raw = data.raw("specialized_metabolism", "dietary")
        if raw:
            r = raw[0]
            vals = [
                _pick(r, "substrate", "name"),
                _pick(r, "pathway", "enzyme"),
                _pick(r, "product", "target_product"),
            ]
            for i, v in zip(boxes, vals):
                labels[i] = [labels[i][0], str(v)]
    elif (chapter, sub) == (14, 2):
        findings = document.get("overview_findings", [])
        actions = tables[0][1] if tables else []
        if findings and actions and any("未提供" not in str(v) for v in actions[0]):
            vals = [findings[0]["finding"], actions[0][1], actions[0][-1]]
            for i, v in zip(boxes, vals):
                labels[i] = [labels[i][0], str(v)]
    elif (chapter, sub) == (12, 4):
        enabled = bool(data.group("prediction"))
        vals = [
            "已满足" if enabled else "未启用",
            data.group("prediction")[0]["result_text"] if enabled else "未启用",
            "见本节适用范围",
        ]
        for i, v in zip(boxes, vals):
            labels[i] = [labels[i][0], v]
    return labels


def draw_flow(spec, labels, width):
    ex, ey = spec["extent"]
    height = max(160, int(width * ey / ex))
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    factor = width / ex
    font = _font(width / 48)
    for shape, text in zip(spec["shapes"], labels):
        x, y, w, h = [v * factor for v in shape["box"]]
        if shape["geometry"] == "line":
            draw.line(
                (x, y, x + w, y + h), fill="#" + shape["line"], width=max(2, int(width / 600))
            )
            r = width * 0.006
            draw.polygon(
                [(x + w, y + h), (x + w - r, y + h - r * 0.55), (x + w - r, y + h + r * 0.55)],
                fill="#" + shape["line"],
            )
        else:
            draw.rectangle(
                (x + 1, y + 1, x + w - 1, y + h - 1),
                fill="#" + shape["fill"],
                outline="#" + shape["line"],
                width=2,
            )
            lines = [line for t in text for line in _wrap(draw, t, font, w * 0.88, 2)]
            # Preserve shape geometry, with readable ellipsis for long observations.
            allowed = max(2, int((h - 14) / (font.size * 1.3)))
            if len(lines) > allowed:
                lines = lines[:allowed]
                lines[-1] = lines[-1][:-1] + "…"
            top = y + (h - len(lines) * font.size * 1.3) / 2
            for i, line in enumerate(lines):
                draw.text(
                    (x + w / 2, top + i * font.size * 1.3),
                    line,
                    font=font,
                    fill="#30343A",
                    anchor="ma",
                )
    return image


def render_word_figures(document, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # Overview is needed by the action diagram, and is kept traceable in the JSON.
    from .template_body import prepare_presentation

    prepare_presentation(document)
    figures = {}
    manifest = {}
    for chapter in contract()["chapters"]:
        for block in chapter["blocks"]:
            if block["type"] != "visuals":
                continue
            key = "+".join(v["id"] for v in block["items"])
            width = 1800
            active_items = block["items"]
            if chapter["number"] == 1 and any(v["id"] == "1.2.2" for v in active_items):
                core = next(v for v in active_items if v["id"] == "1.2.2")
                if chart_data(document, core)["status"] != "available":
                    active_items = [v for v in active_items if v["id"] != "1.2.2"]
            partwidth = width // (3 if block.get("age_panel") else len(active_items))
            payloads = []
            images = []
            for spec in active_items:
                if spec["type"] == "chart":
                    payload = chart_data(document, spec)
                    im = draw_chart(spec, payload, partwidth)
                elif spec["id"] == "2.4.flow":
                    from .chapter_two import cooperation_payload, draw_cooperation
                    payload = cooperation_payload(document)
                    im = draw_cooperation(payload, partwidth)
                else:
                    payload = {"labels": flow_labels(document, spec)}
                    im = draw_flow(spec, payload["labels"], partwidth)
                payloads.append(
                    {"id": spec["id"], "kind": spec.get("kind", "flow"), "data": payload}
                )
                images.append(im)
            height = max(im.height for im in images)
            header = 48 if block.get("age_panel") else 0
            height += header
            combined = Image.new("RGB", (width, height), "white")
            for i, im in enumerate(images):
                combined.paste(im, (i * partwidth, header + (height - header - im.height) // 2))
            if block.get("age_panel"):
                draw = ImageDraw.Draw(combined)
                font = _font(27)
                draw.rectangle((0, 0, width, header), fill="#E2EDF0")
                for i, title in enumerate(("健康分展示", "失衡分展示", "肠龄解释")):
                    _text(draw, ((i + 0.5) * partwidth, 7), title, font, anchor="ma")
                models = valid_composites(Data(document))
                age = next((r for r in models if r.get("name") == "模型肠龄"), {})
                actual = document.get("metadata", {}).get("age")
                ageval = finite(age.get("value"))
                actualval = finite(actual)
                lines = [
                    "肠龄解释",
                    f"实际年龄：{actual if actual is not None else '未提供'}",
                    f"模型肠龄：{str(ageval) + '岁' if ageval is not None else '未启用'}",
                    f"差值：{ageval - actualval:g}岁"
                    if ageval is not None and actualval is not None
                    else "差值及含义：无法判断",
                ]
                for i, line in enumerate(lines):
                    _text(
                        draw,
                        (width * 0.69, header + 25 + i * 45),
                        line,
                        font,
                        width=width * 0.3,
                        max_lines=1,
                    )
            buffer = io.BytesIO()
            combined.save(buffer, format="PNG", optimize=True)
            encoded = buffer.getvalue()
            digest = hashlib.sha256(encoded).hexdigest()[:20]
            role = hashlib.sha256(key.encode()).hexdigest()[:8]
            name = f"{document['sample_id']}_word_{role}_{digest}.png"
            (output / name).write_bytes(encoded)
            manifest[key] = {"filename": name, "items": payloads, "width": width, "height": height}
            figures[key] = name
    from .chapter_seven import render_figures as render_chapter_seven_figures
    figures.update(render_chapter_seven_figures(document, output, manifest))
    document["word_figures"] = manifest
    document["presentation"]["word_source_hashes"] = contract()["sources"]
    document['presentation']['word_chart_count'] = sum(item.get('type') == 'chart' for chapter in contract()['chapters'] for block in chapter['blocks'] for item in block.get('items', []))
    document["presentation"]["word_flow_count"] = 12
    return figures
