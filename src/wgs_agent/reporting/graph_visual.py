"""Chinese evidence networks with connected-component layouts and semantic colors."""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .fonts import resolve_cjk_fonts

NODE_COLORS = {
    "菌群": ("#d9f1e9", "#22846c"),
    "代谢物": ("#fff0ce", "#b18426"),
    "疾病与结局": ("#fce0e4", "#bd5367"),
    "基因与蛋白": ("#e4def7", "#7f62aa"),
    "生理过程": ("#dcecfb", "#387fb3"),
    "研究对象": ("#e4e9ef", "#637b94"),
    "干预与营养": ("#fce5d4", "#bf7b42"),
    "其他": ("#e4eef0", "#5c8c91"),
}
EDGE_COLORS = {
    "关联": "#8661ad",
    "促进与产生": "#298d68",
    "抑制与降低": "#ca694f",
    "组间差异": "#3989bc",
    "研究描述": "#7c8e9d",
    "干预": "#c18b30",
    "影响与调节": "#567bbb",
}


def node_category(raw: str) -> str:
    value = raw.casefold()
    if any(t in value for t in ("microb", "organism", "taxon")):
        return "菌群"
    if any(t in value for t in ("compound", "metabolite", "chemical")):
        return "代谢物"
    if any(t in value for t in ("disease", "symptom", "outcome", "phenotype")):
        return "疾病与结局"
    if any(
        t in value for t in ("gene", "protein", "mutation", "sequence", "complex", "rna", "dna")
    ):
        return "基因与蛋白"
    if any(t in value for t in ("process", "pathway", "function")):
        return "生理过程"
    if any(t in value for t in ("model", "group", "cohort", "cell", "host", "population", "assay")):
        return "研究对象"
    if any(t in value for t in ("intervention", "diet", "nutrient", "treatment")):
        return "干预与营养"
    return "其他"


def edge_category(raw: str) -> str:
    value = raw.upper()
    if any(t in value for t in ("CORRELAT", "ASSOCIAT")):
        return "关联"
    if any(t in value for t in ("INHIB", "DECREASE", "REDUCE", "SUPPRESS")):
        return "抑制与降低"
    if any(t in value for t in ("PROMOT", "INCREASE", "PRODUC", "STIMULAT")):
        return "促进与产生"
    if "DIFFER" in value:
        return "组间差异"
    if any(t in value for t in ("MEASURE", "HAS_", "PART_OF", "IS_A")):
        return "研究描述"
    if "TREAT" in value:
        return "干预"
    return "影响与调节"


def _components(nodes: list[dict], edges: list[dict]) -> list[list[str]]:
    adjacency = {node["id"]: set() for node in nodes}
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    result, visited = [], set()
    for node in nodes:
        if node["id"] in visited:
            continue
        stack, component = [node["id"]], []
        while stack:
            key = stack.pop()
            if key in visited:
                continue
            visited.add(key)
            component.append(key)
            stack.extend(sorted(adjacency[key] - visited, reverse=True))
        result.append(component)
    return sorted(result, key=lambda c: (-len(c), c[0]))


def property_caption(edge: dict) -> str:
    """Compact display of declared study qualifiers; the full translation is retained."""
    qualifiers = edge.get("qualifiers") or {}
    process = edge.get("process") or {}
    subject = process.get("subject") or {}
    metric = qualifiers.get("metric") or subject.get("kind")
    direction = qualifiers.get("direction") or subject.get("direction")
    metrics = {
        "abundance": "丰度",
        "relative_abundance": "相对丰度",
        "concentration": "浓度",
        "expression": "表达",
        "activity": "活性",
        "prevalence": "检出比例",
        "percentage": "占比",
        "expansion": "扩增",
    }
    directions = {
        "increased": "升高",
        "decreased": "降低",
        "unchanged": "不变",
        "unknown": "方向未明确",
    }
    parts = []
    if metric in metrics and direction in directions:
        parts.append(metrics[metric] + directions[direction])
    association = {"positive": "正相关", "negative": "负相关"}.get(
        qualifiers.get("association_direction")
    )
    if association:
        parts.append(association)
    study = {"observational": "观察研究", "experimental": "实验研究"}.get(
        qualifiers.get("evidence_type")
    )
    if study:
        parts.append(study)
    if parts:
        return " · ".join(parts)
    value = edge.get("display_attributes") or ""
    if len(value) > 14 and any(s in value for s in ("未指明", "未明确", "未提供")):
        return "研究条件未详述"
    return value


def _wrap(draw, text: str, font, width: float, maximum=3) -> str:
    lines, current = [], ""
    for char in text:
        if draw.textlength(current + char, font=font) > width:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    if len(lines) > maximum:
        lines = lines[:maximum]
        lines[-1] = lines[-1][:-1] + "…"
    return "\n".join(lines)


def render_graph_figures(document: dict, directory: Path) -> dict[str, str]:
    from .knowledge_graph import relation_label, _confidence

    regular_path, bold_path = resolve_cjk_fonts()

    @lru_cache(maxsize=32)
    def font(size, bold=False):
        return ImageFont.truetype(bold_path if bold else regular_path, size)

    figures = {}
    for section in document["sections"]:
        for topic in section["topics"]:
            graph = topic.get("knowledge_subgraph", {})
            nodes, edges = graph.get("nodes", []), graph.get("edges", [])
            if not edges or graph.get("display_status") != "ready":
                continue
            degree = {n["id"]: 0 for n in nodes}
            for edge in edges:
                degree[edge["source"]] += 1
                degree[edge["target"]] += 1
            components = _components(nodes, edges)
            columns = 2 if len(components) > 1 and max(map(len, components)) <= 4 else 1
            cell_w = 880 if columns == 2 else 1680

            def component_height(size):
                return 300 if size <= 2 else 450 if size == 3 else 600 if size == 4 else 720

            row_heights = [
                max(component_height(len(c)) for c in components[i : i + columns])
                for i in range(0, len(components), columns)
            ]
            width, height = cell_w * columns + 80, sum(row_heights) + 250
            canvas = Image.new("RGB", (width, height), "#f7fafc")
            draw = ImageDraw.Draw(canvas)
            draw.text(
                (42, 30), topic["title"] + " · 相关知识子图", font=font(37, True), fill="#193c64"
            )
            positions, sizes = {}, {}
            node_map = {n["id"]: n for n in nodes}
            for index, component in enumerate(components):
                left = 40 + (index % columns) * cell_w
                row_index = index // columns
                top = 110 + sum(row_heights[:row_index])
                cell_h = row_heights[row_index]
                ordered = sorted(component, key=lambda key: (-degree[key], key))
                if len(ordered) == 1:
                    local = [(cell_w / 2, cell_h / 2)]
                elif len(ordered) == 2:
                    local = [(cell_w * 0.19, cell_h * 0.48), (cell_w * 0.81, cell_h * 0.48)]
                elif len(ordered) == 3:
                    local = [
                        (cell_w * 0.19, cell_h * 0.50),
                        (cell_w * 0.80, cell_h * 0.22),
                        (cell_w * 0.80, cell_h * 0.80),
                    ]
                else:
                    local = [(cell_w / 2, cell_h / 2)]
                    count = len(ordered) - 1
                    local += [
                        (
                            cell_w / 2
                            + math.cos(-math.pi / 2 + j * 2 * math.pi / count) * cell_w * 0.36,
                            cell_h / 2
                            + math.sin(-math.pi / 2 + j * 2 * math.pi / count) * cell_h * 0.35,
                        )
                        for j in range(count)
                    ]
                for key, (x, y) in zip(ordered, local):
                    positions[key] = (left + x, top + y)
                    node = node_map[key]
                    importance = min(4, degree[key] - 1)
                    label = node["display_label"]
                    label_font = font(30 + importance * 2, True)
                    box_w = (
                        min(344, max(190, draw.textlength(label[:9], font=label_font) + 42))
                        + importance * 5
                    )
                    wrapped = _wrap(draw, label, label_font, box_w - 24, 3)
                    bounds = draw.multiline_textbbox((0, 0), wrapped, font=label_font, spacing=4)
                    box_h = max(108, bounds[3] - bounds[1] + 68) + importance * 4
                    sizes[key] = (box_w, box_h)
            for edge_index, edge in enumerate(edges):
                a, b = positions[edge["source"]], positions[edge["target"]]
                if a == b:
                    # Self relations retain an explicit loop, rather than a zero-length arrow.
                    bx, by = a
                    w, h = sizes[edge["source"]]
                    draw.arc(
                        (bx - w / 2, by - h, bx + w / 2, by),
                        190,
                        530,
                        fill=EDGE_COLORS[edge_category(edge["predicate"])],
                        width=4,
                    )
                    color = EDGE_COLORS[edge_category(edge["predicate"])]
                    draw.polygon(
                        [
                            (bx + w / 2, by - h / 2),
                            (bx + w / 2 - 16, by - h / 2 - 10),
                            (bx + w / 2 + 3, by - h / 2 - 18),
                        ],
                        fill=color,
                    )
                    label = relation_label(edge)
                    if edge.get("display_attributes"):
                        label += "\n" + edge["display_attributes"]
                    label = _wrap(draw, label, font(23), 360, 3)
                    box = draw.multiline_textbbox((0, 0), label, font=font(23), spacing=4)
                    draw.multiline_text(
                        (bx - (box[2] - box[0]) / 2, by - h - 45),
                        label,
                        font=font(23),
                        spacing=4,
                        align="center",
                        fill=color,
                    )
                    continue
                dx, dy = b[0] - a[0], b[1] - a[1]
                distance = math.hypot(dx, dy)
                ux, uy = dx / distance, dy / distance

                def trim(key):
                    w, h = sizes[key]
                    return min(w / 2 / max(abs(ux), 0.001), h / 2 / max(abs(uy), 0.001)) + 9

                start = (a[0] + ux * trim(edge["source"]), a[1] + uy * trim(edge["source"]))
                end = (b[0] - ux * trim(edge["target"]), b[1] - uy * trim(edge["target"]))
                category = edge_category(edge["predicate"])
                color = EDGE_COLORS[category]
                line_w = 3 + int(min(1, max(0, _confidence(edge))) * 2)
                # A slight curve separates multiple relationships between the same entities.
                peers = [
                    e
                    for e in edges
                    if {e["source"], e["target"]} == {edge["source"], edge["target"]}
                ]
                curve = (peers.index(edge) - (len(peers) - 1) / 2) * 48
                mid = ((start[0] + end[0]) / 2 - uy * curve, (start[1] + end[1]) / 2 + ux * curve)
                points = []
                for step in range(31):
                    t = step / 30
                    points.append(
                        (
                            (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * mid[0] + t * t * end[0],
                            (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * mid[1] + t * t * end[1],
                        )
                    )
                if edge.get("speculative"):
                    for i in range(0, len(points) - 1, 3):
                        draw.line(points[i : i + 2], fill=color, width=line_w)
                else:
                    draw.line(points, fill=color, width=line_w)
                tx, ty = points[-1][0] - points[-2][0], points[-1][1] - points[-2][1]
                length = math.hypot(tx, ty)
                tx, ty = tx / length, ty / length
                draw.polygon(
                    [
                        end,
                        (end[0] - 18 * tx + 8 * ty, end[1] - 18 * ty - 8 * tx),
                        (end[0] - 18 * tx - 8 * ty, end[1] - 18 * ty + 8 * tx),
                    ],
                    fill=color,
                )
                label = (
                    relation_label(edge)
                    .replace("在组间存在差异", "组间差异")
                    .replace("与…相关", "相关")
                    .replace("与...相关", "相关")
                )
                if property_caption(edge):
                    label += "\n" + property_caption(edge)
                label = "\n".join(
                    _wrap(draw, s, font(25), max(230, min(350, distance * 0.7)), 4)
                    for s in label.splitlines()
                )
                if abs(dy) > abs(dx) * 1.5:
                    label_x, label_y = points[15][0] + 185, points[15][1]
                else:
                    label_x, label_y = points[15][0], points[15][1] - 25
                box = draw.multiline_textbbox(
                    (0, 0), label, font=font(25), align="center", spacing=5
                )
                text_x = label_x - (box[2] - box[0]) / 2 - box[0]
                text_y = label_y - (box[3] - box[1]) / 2 - box[1]
                draw.rounded_rectangle(
                    (
                        text_x + box[0] - 8,
                        text_y + box[1] - 5,
                        text_x + box[2] + 8,
                        text_y + box[3] + 5,
                    ),
                    radius=7,
                    fill="#f7fafc",
                )
                draw.multiline_text(
                    (text_x, text_y), label, font=font(25), align="center", spacing=5, fill=color
                )
            for node in nodes:
                x, y = positions[node["id"]]
                w, h = sizes[node["id"]]
                category = node_category(node["type"])
                fill, border = NODE_COLORS[category]
                draw.rounded_rectangle(
                    (x - w / 2, y - h / 2, x + w / 2, y + h / 2),
                    radius=24,
                    fill=fill,
                    outline=border,
                    width=3,
                )
                label_font = font(30 + min(4, degree[node["id"]] - 1) * 2, True)
                label = _wrap(draw, node["display_label"], label_font, w - 24, 3)
                bounds = draw.multiline_textbbox((0, 0), label, font=label_font, spacing=4)
                label_height = bounds[3] - bounds[1]
                label_width = bounds[2] - bounds[0]
                draw.multiline_text(
                    (x - label_width / 2 - bounds[0], y - label_height / 2 - bounds[1] - 18),
                    label,
                    font=label_font,
                    align="center",
                    spacing=4,
                    fill="#203c54",
                )
                draw.text(
                    (x, y + h / 2 - 25),
                    node["display_type"],
                    font=font(20),
                    anchor="mm",
                    fill=border,
                )
            legend_y = height - 115
            cursor = 45
            used_nodes = sorted({node_category(n["type"]) for n in nodes})
            for category in used_nodes:
                draw.ellipse(
                    (cursor, legend_y, cursor + 18, legend_y + 18), fill=NODE_COLORS[category][1]
                )
                draw.text((cursor + 26, legend_y - 5), category, font=font(22), fill="#4a6174")
                cursor += 45 + len(category) * 24
            cursor = 45
            for category in sorted({edge_category(e["predicate"]) for e in edges}):
                draw.line(
                    (cursor, legend_y + 54, cursor + 32, legend_y + 54),
                    fill=EDGE_COLORS[category],
                    width=4,
                )
                draw.text((cursor + 42, legend_y + 38), category, font=font(22), fill="#4a6174")
                cursor += 62 + len(category) * 24
            graph["visual_style"] = {
                "version": "chinese-network-v2",
                "node_colors": {n["id"]: NODE_COLORS[node_category(n["type"])][1] for n in nodes},
                "node_sizes": {key: list(value) for key, value in sizes.items()},
                "edge_colors": {e["id"]: EDGE_COLORS[edge_category(e["predicate"])] for e in edges},
            }
            digest = hashlib.sha256(
                json.dumps(
                    {k: v for k, v in graph.items() if k != "figure"},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()[:12]
            name = f"{document['sample_id']}_{topic['id'].replace('.', '_')}_kg_{digest}.png"
            directory.mkdir(parents=True, exist_ok=True)
            canvas.save(directory / name, "PNG")
            (directory / name).chmod(0o600)
            graph["figure"] = name
            figures[topic["id"]] = name
    return figures
