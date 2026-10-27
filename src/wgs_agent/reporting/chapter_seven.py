"""Compact, evidence-backed visual presentation for report sections 7.2–7.4."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .functional_metrics import contributor_summary, taxon_name
from .inputs import finite
from .template_body import Body, _linked

VERSION = "chapter-seven-visual-v1"
CATEGORIES = (
    ("蛋白质及氨基酸", "Protein & amino acids", "nutrient_metabolism.amino_acid"),
    ("脂质", "Lipids", "nutrient_metabolism.lipid"),
    ("维生素与辅酶", "Vitamins & cofactors", "nutrient_metabolism.vitamin"),
    ("嘌呤与嘧啶", "Purines & pyrimidines", "nutrient_metabolism.nucleotide"),
)
COLORS = {
    "sample": "#246A73",
    "reference": "#7F929B",
    "ink": "#263746",
    "muted": "#667780",
    "line": "#D9E1E5",
    "taxon": "#E2EDF0",
    "pathway": "#F3ECDD",
}
TAXA = {
    "blautia obeum": "奥贝布劳特菌",
    "streptococcus thermophilus": "嗜热链球菌",
    "eubacterium rectale": "直肠真杆菌",
    "bifidobacterium adolescentis": "青春双歧杆菌",
    "anaerostipes hadrus": "霍氏厌氧棍状菌",
    "bacteroides vulgatus": "普通拟杆菌",
}


def _unique(values, limit=5):
    return list(dict.fromkeys(v for v in values if v))[:limit]


def bilingual(document, raw):
    from .taxon_labels import display_taxon, FALLBACK

    name = taxon_name(raw)
    label = ""
    for field in (
        "chapter_one_taxon_labels",
        "chapter_two_taxon_labels",
        "chapter_three_taxon_labels",
        "overview_taxon_labels",
    ):
        result = display_taxon(document, {"species": name}, label_field=field)
        if result.get("label") not in {"菌种", "未定种", ""}:
            label = result["label"]
            break
    label = label or TAXA.get(name.lower(), "")
    if not label:
        genus = name.split()[0].lower() if name else ""
        label = (FALLBACK.get(genus, "") + "成员") if genus in FALLBACK else "未收录中文名"
    return f"{label}（{name}）" if name != label else label


def _direction(row):
    explicit = str(row.get("reaction_direction", row.get("direction", ""))).lower().strip()
    if explicit in {"generation", "synthesis", "biosynthesis", "production", "合成", "生成"}:
        return "synthesis"
    if explicit in {"use", "degradation", "utilization", "consumption", "降解", "利用"}:
        return "degradation"
    name = str(row.get("name", row.get("label", ""))).lower()
    generation = bool(re.search(r"biosynthesis|production|generation|合成|生成", name))
    degradation = bool(re.search(r"degradation|utilization|consumption|降解|利用", name))
    return (
        "synthesis"
        if generation and not degradation
        else "degradation"
        if degradation and not generation
        else "unresolved"
    )


def _unit(value):
    value = str(value or "").strip().lower()
    return {
        "相对丰度": "relative_abundance",
        "relative abundance": "relative_abundance",
        "percent": "%",
        "percentage": "%",
    }.get(value, value)


def _reference(row):
    """Never manufacture a median from interval endpoints or taxonomy references."""
    valid = (
        row.get("comparison") in {"within", "above", "below"}
        or row.get("reference_comparable") is True
    )
    if row.get("comparison_reason") in {
        "incompatible_unit",
        "invalid_observation",
        "zero_width_reference_interval",
    }:
        valid = False
    if row.get("reference_unit") and _unit(row["reference_unit"]) != _unit(row.get("unit")):
        valid = False
    unit = _unit(row.get("unit"))
    if not unit or unit in {"未提供", "单位未提供"}:
        valid = False
    median = finite(row.get("reference_median", row.get("reference_p50")))
    p5, p95 = finite(row.get("p5")), finite(row.get("p95"))
    if median is not None and median < 0:
        median = None
    interval = [p5, p95] if p5 is not None and p95 is not None and 0 <= p5 < p95 else None
    if median is not None and interval and not interval[0] <= median <= interval[1]:
        valid = False
    return {
        "median": median if valid else None,
        "interval": interval if valid else None,
        "status": "available" if valid and (median is not None or interval) else "missing",
        "n_reference": row.get("n_reference"),
        "population": row.get("reference_population", row.get("reference_source", "")),
    }


def _positive(row):
    if row.get("detected") is False:
        return False
    status = str(row.get("detection_status", row.get("result", row.get("status", "")))).lower()
    if any(
        x in status
        for x in ("未检出", "insufficient", "not_detected", "not detected", "覆盖不足", "negative")
    ):
        return False
    value = finite(row.get("value", row.get("abundance")))
    if value is not None:
        return value > 0
    return row.get("detected") is True or status in {"detected", "positive", "检出", "已检出"}


def detected_genes(rows):
    found = []
    for row in rows:
        if row.get("detected") is False:
            continue
        state = str(row.get("result", row.get("detection_status", ""))).lower()
        if any(w in state for w in ("未检出", "insufficient", "not_detected", "覆盖不足")):
            continue
        for key in ("detected_genes", "genes", "gene", "gene_id", "gene_family"):
            values = row.get(key)
            if isinstance(values, str):
                values = re.split(r"[;,；，]", values)
            elif isinstance(values, dict):
                values = [values]
            if not isinstance(values, list):
                continue
            for gene in values:
                if isinstance(gene, dict):
                    if not _positive(gene):
                        continue
                    name = gene.get("gene", gene.get("gene_id", gene.get("name", gene.get("id"))))
                else:
                    if key != "detected_genes" and not _positive(row):
                        continue
                    name = str(gene).strip()
                if name:
                    found.append(str(name).strip())
    return _unique(found)


def _ranked_taxa(rows, document, limit=3):
    units = {_unit(r.get("unit")) for r in rows if contributor_summary(r)["status"] == "available"}
    if len(units) != 1:
        return []
    totals = {}
    for row in rows:
        summary = contributor_summary(row)
        if summary["status"] != "available":
            continue
        for member in summary["members"]:
            name = member["name"]
            if name == "未分类贡献":
                continue
            totals[name] = totals.get(name, 0) + member["value"]
    return [
        {"name": name, "label": bilingual(document, name), "ranking_value": value}
        for name, value in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def nutrition_payload(document):
    data = Body(document)
    categories = []
    for label, english, tid in CATEGORIES:
        rows = [
            r for r in data.topic_rows(tid) if r.get("measurement_type") == "functional_potential"
        ]
        metrics = []
        for direction in ("synthesis", "degradation"):
            candidates = [
                r
                for r in rows
                if _direction(r) == direction
                and finite(r.get("value")) is not None
                and r["value"] >= 0
            ]
            candidates.sort(
                key=lambda r: (
                    _reference(r)["status"] != "available",
                    -r["value"],
                    str(r.get("id", "")),
                )
            )
            row = candidates[0] if candidates else {}
            reference = _reference(row)
            metrics.append(
                {
                    "direction": direction,
                    "value": finite(row.get("value")),
                    "unit": row.get("unit", ""),
                    "pathway_id": row.get("id", ""),
                    "pathway_name": row.get("name", row.get("label", "")),
                    "reference": reference,
                    "evidence_id": next(
                        (k for k, v in document["evidence"].items() if v is row), None
                    ),
                }
            )
        categories.append(
            {
                "label": label,
                "english": english,
                "topic_id": tid,
                "metrics": metrics,
                "taxa": _ranked_taxa(rows, document),
                "genes": detected_genes(rows),
                "record_count": len(rows),
            }
        )
    return {
        "categories": categories,
        "method": "one_observed_representative_pathway_per_category_and_direction; prefer_comparable_reference_then_abundance; no_sum_of_overlapping_pathways",
        "qc_failed": data.qc_failed,
    }


def cazy_payload(document):
    data = Body(document)
    rows = data.raw("cazy", "families", "clusters", "genes")
    chains = []
    for row in sorted(rows, key=lambda r: -(finite(r.get("value", r.get("abundance"))) or 0))[:3]:
        genes = detected_genes([row])
        host, proof = _linked(row, "host")
        supported = host != "宿主未确定"
        enzyme = str(row.get("enzyme", row.get("family", row.get("name", "酶注释未提供"))))
        chains.append(
            {
                "genes": genes[:2],
                "taxon": bilingual(document, host) if supported else "归属菌待确认",
                "enzyme": enzyme,
                "linked": supported,
                "link_evidence": proof if supported else "",
                "gene_cluster": row.get("gene_cluster", ""),
            }
        )
    return {
        "chains": chains,
        "record_count": len(rows),
        "qc_failed": data.qc_failed,
        "status": "available" if chains else "missing",
    }


def pathway_graph(document):
    data = Body(document)
    topics = {tid: label for label, _, tid in CATEGORIES}
    topics.update(
        {"nutrient_metabolism.carbohydrate": "碳水化合物", "nutrient_metabolism.fiber": "膳食纤维"}
    )
    candidates, seen = [], set()
    for tid, label in topics.items():
        for row in data.topic_rows(tid):
            ident = str(row.get("id", row.get("label", "")))
            if ident in seen or row.get("kind") not in {"function", "pathway"}:
                continue
            summary = contributor_summary(row)
            if summary["status"] != "available":
                continue
            members = [m for m in summary["members"] if m["name"] != "未分类贡献"][:3]
            if not members:
                continue
            seen.add(ident)
            candidates.append((row, label, members))
    candidates.sort(key=lambda item: -(finite(item[0].get("value")) or 0))
    # Select across categories before filling remaining slots, avoiding one dense category.
    selected, labels = [], set()
    for item in candidates:
        if item[1] not in labels:
            selected.append(item)
            labels.add(item[1])
        if len(selected) == 6:
            break
    for item in candidates:
        if len(selected) >= 6:
            break
        if item not in selected:
            selected.append(item)
    taxa = _ranked_taxa([item[0] for item in selected], document, limit=5)
    names = {t["name"] for t in taxa}
    paths, edges = [], []
    for row, label, members in selected:
        linked = [m for m in members if m["name"] in names]
        if not linked:
            continue
        ident = str(row.get("id", row.get("label")))
        direction = {"synthesis": "合成", "degradation": "降解", "unresolved": "代谢"}[
            _direction(row)
        ]
        paths.append(
            {
                "id": ident,
                "label": f"{label}·{direction}",
                "name": row.get("name", row.get("label", "")),
                "unit": row.get("unit"),
            }
        )
        for member in linked:
            edges.append(
                {
                    "source": member["name"],
                    "target": ident,
                    "value": member["value"],
                    "evidence_id": next(
                        (k for k, v in document["evidence"].items() if v is row), None
                    ),
                    "relation": "sample_stratified_pathway_contribution",
                }
            )
    active = {e["source"] for e in edges}
    return {
        "taxa": [t for t in taxa if t["name"] in active],
        "pathways": paths,
        "edges": edges,
        "status": "available" if edges else "missing",
        "qc_failed": data.qc_failed,
    }


def _text(draw, xy, text, size=30, fill=None, width=None, max_lines=3, anchor=None):
    from .word_figures import _font, _text as draw_text

    draw_text(
        draw,
        xy,
        text,
        _font(size),
        fill=fill or COLORS["ink"],
        width=width,
        max_lines=max_lines,
        anchor=anchor,
    )


def _canvas(height, title):
    image = Image.new("RGB", (1800, height), "white")
    draw = ImageDraw.Draw(image)
    _text(draw, (42, 25), title, 38)
    return image, draw


def draw_cazy(payload):
    chains = payload["chains"]
    image, draw = _canvas(290 + max(1, len(chains)) * 155, "检出基因 → 归属菌 → 糖活性酶")
    xpositions = (42, 650, 1258)
    for x, heading in zip(xpositions, ("基因检出", "菌群归属", "对应酶 / 酶家族")):
        _text(draw, (x, 98), heading, 31, COLORS["sample"])
    active = chains or [
        {
            "genes": ["序列检出与覆盖支持"],
            "taxon": "序列连接或分层归属",
            "enzyme": "酶家族注释与基因簇定位",
            "linked": False,
        }
    ]
    for i, chain in enumerate(active):
        y = 160 + i * 155
        labels = [
            "、".join(chain["genes"]) or "未提供基因检出明细",
            chain["taxon"],
            chain["enzyme"],
        ]
        for j, (x, label) in enumerate(zip(xpositions, labels)):
            draw.rounded_rectangle(
                (x, y, x + 500, y + 118),
                radius=12,
                fill=COLORS["taxon"] if j < 2 else COLORS["pathway"],
                outline=COLORS["line"],
                width=2,
            )
            _text(draw, (x + 20, y + 20), label, 31, width=460, max_lines=2)
        for j in (0, 1):
            a = xpositions[j] + 514
            b = xpositions[j + 1] - 16
            cy = y + 59
            supported = (
                bool(chains) and bool(chain["genes"]) and (chain["linked"] if j == 0 else True)
            )
            if supported:
                draw.line((a, cy, b, cy), fill=COLORS["sample"], width=4)
            else:
                for px in range(a, b, 15):
                    draw.line((px, cy, min(px + 7, b), cy), fill=COLORS["muted"], width=2)
            draw.polygon(
                [(b, cy), (b - 12, cy - 7), (b - 12, cy + 7)],
                fill=COLORS["sample"] if supported else COLORS["muted"],
            )
    _text(
        draw,
        (42, image.height - 70),
        (
            "实线表示已有对应证据；虚线表示记录或归属待补充。仅展示最多 3 条代表链路。"
            if chains
            else "以上为证据整理流程；本次未提供 CAZy 结果，尚未建立样本对应链路。"
        ),
        27,
        COLORS["muted"],
        width=1700,
        max_lines=2,
    )
    return image


def draw_nutrition(payload):
    image, draw = _canvas(1110, "营养物质合成与降解潜力：本样本与参考人群")
    draw.rectangle((47, 92, 81, 115), fill=COLORS["sample"])
    _text(draw, (96, 85), "本样本", 28)
    draw.rectangle((270, 92, 304, 115), outline=COLORS["reference"], width=3)
    _text(draw, (319, 85), "参考中位数", 28)
    _text(draw, (620, 85), "细线：参考 P5–P95；缺失数据留空", 28, COLORS["muted"])
    categories = payload["categories"]
    # Every plotted quantity shares a unit and a zero origin; no ratios or artificial scores.
    units = {_unit(m["unit"]) for c in categories for m in c["metrics"] if m["value"] is not None}
    common = next(iter(units)) if len(units) == 1 else None
    values = []
    for c in categories:
        for m in c["metrics"]:
            if _unit(m["unit"]) != common:
                continue
            values.extend(
                v
                for v in [m["value"], m["reference"]["median"], *(m["reference"]["interval"] or [])]
                if v is not None
            )
    maximum = max(values, default=0) * 1.15 or 1
    factor = 100 if common == "relative_abundance" else 1
    unit_label = (
        "相对丰度（%）"
        if factor == 100
        else ("%" if common == "%" else common or "单位不一致，暂不绘制数值")
    )
    for panel, title in enumerate(("合成潜力", "降解潜力")):
        x0 = 410 + panel * 840
        plotwidth = 420
        _text(draw, (x0, 145), title, 33, COLORS["sample"])
        for tick in range(5):
            xx = x0 + tick * plotwidth / 4
            draw.line((xx, 220, xx, 970), fill=COLORS["line"], width=1)
            _text(draw, (xx, 982), f"{maximum * factor * tick / 4:.3g}", 24, anchor="ma")
        _text(draw, (x0 + plotwidth / 2, 1030), unit_label, 26, anchor="ma")
        for i, c in enumerate(categories):
            y = 245 + i * 185
            m = c["metrics"][panel]
            if panel == 0:
                _text(draw, (42, y + 4), c["label"], 32, width=350, max_lines=2)
                _text(draw, (42, y + 49), c["english"], 26, COLORS["muted"], width=350, max_lines=2)
            if m["value"] is None:
                _text(draw, (x0, y + 7), "未单独判定", 29, COLORS["muted"])
                continue
            if common is None or _unit(m["unit"]) != common:
                _text(draw, (x0, y + 7), "单位不可比", 29, COLORS["muted"])
                continue

            def pos(value):
                return x0 + value / maximum * plotwidth

            end = pos(m["value"])
            if m["value"] > 0:
                draw.rectangle((x0, y, end, y + 29), fill=COLORS["sample"])
            _text(draw, (end + 9, y - 3), f"{m['value'] * factor:.3g}", 26)
            reference = m["reference"]
            median = reference["median"]
            interval = reference["interval"]
            if median is not None:
                draw.rectangle(
                    (x0, y + 45, pos(median), y + 73), outline=COLORS["reference"], width=3
                )
                _text(
                    draw, (pos(median) + 9, y + 42), f"{median * factor:.3g}", 26, COLORS["muted"]
                )
            if interval:
                lo, hi = map(pos, interval)
                cy = y + 59
                draw.line((lo, cy, hi, cy), fill=COLORS["ink"], width=2)
                for xx in (lo, hi):
                    draw.line((xx, cy - 10, xx, cy + 10), fill=COLORS["ink"], width=2)
            if reference["status"] == "missing":
                _text(draw, (x0, y + 44), "参考数据未提供", 27, COLORS["muted"])
            elif median is None:
                _text(draw, (x0, y + 83), "仅提供参考区间", 24, COLORS["muted"])
            _text(
                draw,
                (x0, y + 120),
                str(m["pathway_id"]),
                23,
                COLORS["muted"],
                width=650,
                max_lines=1,
            )
    return image


def draw_graph(payload):
    image, draw = _canvas(1160, "菌群 — 代谢通路知识图谱")
    taxa, paths = payload["taxa"], payload["pathways"]
    _text(draw, (65, 100), "主要贡献菌（最多 5 种）", 31, COLORS["sample"])
    _text(draw, (1180, 100), "代表代谢通路（最多 6 条）", 31, COLORS["sample"])
    if not payload["edges"]:
        _text(
            draw,
            (190, 420),
            "质控未通过，暂不展示关系"
            if payload["qc_failed"]
            else "未提供可核验的菌—通路分层贡献记录",
            38,
            width=1500,
        )
        return image

    def positions(items):
        return {
            item.get("name", item.get("id")): 180 + i * 760 / max(1, len(items) - 1)
            for i, item in enumerate(items)
        }

    ty = positions(taxa)
    py = {item["id"]: 180 + i * 760 / max(1, len(paths) - 1) for i, item in enumerate(paths)}
    for edge in payload["edges"]:
        start = (650, ty[edge["source"]] + 43)
        end = (1170, py[edge["target"]] + 43)
        draw.line((start, end), fill="#B0C2C8", width=3)
        draw.polygon([end, (end[0] - 13, end[1] - 7), (end[0] - 13, end[1] + 7)], fill="#B0C2C8")
    for item in taxa:
        y = ty[item["name"]]
        draw.rounded_rectangle(
            (50, y, 650, y + 102), radius=12, fill=COLORS["taxon"], outline=COLORS["line"], width=2
        )
        name = item["label"].replace("（", "\n", 1).rstrip("）")
        cn, _, latin = name.partition("\n")
        _text(draw, (68, y + 10), cn, 30, width=565, max_lines=1)
        if latin:
            _text(draw, (68, y + 54), latin, 27, COLORS["muted"], width=565, max_lines=1)
    for item in paths:
        y = py[item["id"]]
        draw.rounded_rectangle(
            (1170, y, 1750, y + 102),
            radius=12,
            fill=COLORS["pathway"],
            outline=COLORS["line"],
            width=2,
        )
        _text(draw, (1188, y + 10), item["label"], 29, width=542, max_lines=1)
        _text(draw, (1188, y + 54), item["id"], 26, COLORS["muted"], width=542, max_lines=1)
    _text(
        draw,
        (50, 1102),
        "连线表示本样本通路的分层贡献；节点不代表实测活性，未分类贡献不单列。",
        26,
        COLORS["muted"],
        width=1700,
        max_lines=2,
    )
    return image


def prepare(document):
    results = {
        "version": VERSION,
        "cazy": cazy_payload(document),
        "nutrition": nutrition_payload(document),
        "graph": pathway_graph(document),
    }
    document["chapter_seven_results"] = results
    chapters = document.get("presentation", {}).get("chapters", [])
    chapter = next((c for c in chapters if c.get("number") == 7), None)
    if chapter and len(chapter.get("subsections", [])) >= 4:
        chapter["subsections"][3] = "7.4 菌群与代谢通路关系图谱"
    return results


def render_figures(document, output, manifest):
    results = prepare(document)
    figures = {}
    for ident, kind, draw in [
        ("7.2.flow", "cazy", draw_cazy),
        ("7.3.1", "nutrition", draw_nutrition),
        ("7.4.graph", "graph", draw_graph),
    ]:
        image = draw(results[kind])
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        content = buffer.getvalue()
        digest = hashlib.sha256(content).hexdigest()[:20]
        role = ident.replace(".", "_")
        name = f"{document['sample_id']}_chapter7_{role}_{digest}.png"
        (Path(output) / name).write_bytes(content)
        manifest[ident] = {
            "filename": name,
            "items": [{"id": ident, "kind": kind, "data": results[kind]}],
            "width": image.width,
            "height": image.height,
        }
        figures[ident] = name
    return figures


def table_rows(document, payload=None):
    payload = payload or nutrition_payload(document)
    return [
        [
            f"{c['label']} / {c['english']}",
            "；".join(t["label"] for t in c["taxa"]) or "未提供可排序的分层贡献菌",
            "、".join(c["genes"]) or "未提供基因检出明细",
        ]
        for c in payload["categories"]
    ]


def render_sections(document):
    from .document import table

    results = prepare(document)
    figures = document.get("word_figures", {})
    output = []
    if results["nutrition"]["qc_failed"]:
        for heading in (
            "7.2 糖活性酶与相关基因簇",
            "7.3 其他营养物质的合成与降解",
            "7.4 菌群与代谢通路关系图谱",
        ):
            output.extend(["### " + heading, "本次样本质控未通过，暂不进行健康解读。"])
        return output

    def figure(ident, alt):
        item = figures.get(ident)
        if item:
            output.append(f"![{alt}]({item['filename']})")

    output.append("### 7.2 糖活性酶与相关基因簇")
    figure("7.2.flow", "图 7-2 基因检出—归属菌—糖活性酶链路")
    enzymes = _unique([c["enzyme"] for c in results["cazy"]["chains"]], 3)
    output.append(
        "已记录酶注释：" + "、".join(enzymes) + "。基因归属仅按已有连接证据展示。"
        if enzymes
        else "本次未提供 CAZy 与相关基因簇结果，暂不能建立基因—菌—酶对应链路。"
    )
    output.append("### 7.3 其他营养物质的合成与降解")
    figure("7.3.1", "图 7-3 合成与降解潜力的参考人群比较")
    output.append("图中为各类营养物质的代表通路相对丰度，合成与降解分别展示。")
    output.append(
        table(
            ["营养物质 / Nutrient", "主要贡献菌（前 3 种）", "相关检出基因 / 家族（最多 5 项）"],
            table_rows(document, results["nutrition"]),
        )
    )
    if not any(
        m["reference"]["status"] == "available"
        for c in results["nutrition"]["categories"]
        for m in c["metrics"]
    ):
        output.append("本次缺少同口径的功能参考数据，参考条形留空，暂不判定高低。")
    output.append("### 7.4 菌群与代谢通路关系图谱")
    figure("7.4.graph", "图 7-4 主要贡献菌与代表代谢通路知识图谱")
    output.append(
        ""
        if results["graph"]["edges"]
        else "本次缺少可核验的菌—通路分层贡献记录，暂不建立关系连线。"
    )
    return output
