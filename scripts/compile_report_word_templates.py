"""Compile the user's Word layout as data; never execute document instructions."""

import hashlib
import json
import re
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E

ROOT = Path(__file__).resolve().parents[1]
NS = {
    k: v
    for k, v in (
        ("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main"),
        ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"),
        ("c", "http://schemas.openxmlformats.org/drawingml/2006/chart"),
        ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
        ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"),
        ("wpg", "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"),
        ("wps", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"),
    )
}


def text(x):
    return "".join(x.xpath(".//w:t/text()", namespaces=NS))


def first(x, path, default=None):
    values = x.xpath(path, namespaces=NS)
    return values[0] if values else default


def renumber(s):
    s = re.sub(r"^(0?[3-9]|1[0-6])(?=\s|\.\d)", lambda m: str(int(m[0]) - 2), s)
    s = re.sub(r"(第)0?(\d+)(章|\.\d+节)", lambda m: m[1] + str(int(m[2]) - 2) + m[3], s)
    s = re.sub(r"^([图表]\s*)0?(\d+)([ -]+)", lambda m: m[1] + str(int(m[2]) - 2) + "-", s)
    return s


def chart(z, target, node, key):
    x = E.fromstring(z.read("word/" + target))
    plot = x.find(".//c:plotArea", NS)
    kind = next(E.QName(e).localname for e in plot if E.QName(e).localname.endswith("Chart"))
    series = []
    for s in x.findall(".//c:ser", NS):
        colors = s.xpath("./c:spPr/a:solidFill/a:srgbClr/@val", namespaces=NS)
        points = s.xpath("./c:dPt/c:spPr/a:solidFill/a:srgbClr/@val", namespaces=NS)
        series.append(
            {
                "name": first(s, "./c:tx//c:v/text()", ""),
                "categories": s.xpath("./c:cat//c:pt/c:v/text()", namespaces=NS),
                "color": colors[0] if colors else "246A73",
                "point_colors": points,
            }
        )
    return {
        "type": "chart",
        "id": key,
        "kind": kind,
        "series": series,
        "grouping": first(x, "//c:grouping/@val", "clustered"),
        "legend": x.find(".//c:legend", NS) is not None,
        "extent": [int(first(node, ".//wp:extent/@" + a, 0)) for a in ("cx", "cy")],
    }


chapters = []
sources = []
for file in sorted((ROOT / "docs/report_templates").glob("*.docx")):
    sources.append({"name": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    with ZipFile(file) as z:
        doc = E.fromstring(z.read("word/document.xml"))
        rels = {
            e.get("Id"): e.get("Target")
            for e in E.fromstring(z.read("word/_rels/document.xml.rels"))
        }
        current = None
        sub = 0
        seq = {}
        table_index = 0
        for node in doc.find("w:body", NS):
            kind = E.QName(node).localname
            s = text(node)
            if kind == "p" and re.match(r"^(0[3-9]|1[0-6])\s", s):
                n = int(s.split()[0]) - 2
                current = {"number": n, "title": s.split(" ", 1)[1], "blocks": []}
                chapters.append(current)
                sub = 0
                table_index = 0
                continue
            if current is None:
                continue
            if kind == "sectPr":
                continue
            heading = re.match(r"^(\d+)\.(\d+)\s+(.+)", s) if kind == "p" else None
            if heading:
                sub = int(heading[2])
                table_index = 0
                current["blocks"].append(
                    {
                        "type": "heading",
                        "sub": sub,
                        "text": f"{current['number']}.{sub} {heading[3]}",
                    }
                )
                continue
            if "图形仅作占位示意" in s or "以下圆环为排版占位" in s:
                continue
            charts = node.findall(".//c:chart", NS)
            groups = node.findall(".//wpg:wgp", NS)
            if charts or groups:
                visuals = []
                for c in charts:
                    base = f"{current['number']}.{sub}"
                    seq[base] = seq.get(base, 0) + 1
                    visuals.append(
                        chart(z, rels[c.get("{" + NS["r"] + "}id")], node, base + f".{seq[base]}")
                    )
                for group in groups:
                    shapes = []
                    for shape in group.findall("wps:wsp", NS):
                        pos = shape.find("wps:spPr/a:xfrm", NS)
                        if pos is None:
                            continue
                        off = pos.find("a:off", NS)
                        ext = pos.find("a:ext", NS)
                        shapes.append(
                            {
                                "geometry": first(shape, "./wps:spPr/a:prstGeom/@prst", "rect"),
                                "box": [
                                    int(off.get("x")),
                                    int(off.get("y")),
                                    int(ext.get("cx")),
                                    int(ext.get("cy")),
                                ],
                                "fill": first(
                                    shape, "./wps:spPr/a:solidFill/a:srgbClr/@val", "FFFFFF"
                                ),
                                "line": first(
                                    shape, "./wps:spPr/a:ln/a:solidFill/a:srgbClr/@val", "246A73"
                                ),
                                "text": [
                                    renumber(text(p))
                                    for p in shape.findall(".//w:txbxContent/w:p", NS)
                                ],
                            }
                        )
                    extent = group.find("wpg:grpSpPr/a:xfrm/a:ext", NS)
                    visuals.append(
                        {
                            "type": "flow",
                            "id": f"{current['number']}.{sub}.flow",
                            "shapes": shapes,
                            "extent": [int(extent.get("cx")), int(extent.get("cy"))],
                        }
                    )
                # Preserve side-by-side charts and the score/age triptych.
                current["blocks"].append(
                    {
                        "type": "visuals",
                        "sub": sub,
                        "items": visuals,
                        "age_panel": kind == "tbl" and current["number"] == 14,
                    }
                )
                continue
            if kind == "tbl":
                rows = [
                    [renumber(text(c)) for c in r.findall("w:tc", NS)]
                    for r in node.findall("w:tr", NS)
                ]
                widths = [
                    int(e.get("{" + NS["w"] + "}w"))
                    for e in node.findall("w:tblGrid/w:gridCol", NS)
                ]
                table_index += 1
                current["blocks"].append(
                    {
                        "type": "table",
                        "sub": sub,
                        "id": f"{current['number']}.{sub}.t{table_index}",
                        "rows": rows,
                        "widths": widths,
                    }
                )
            elif kind == "p" and s.strip():
                style = first(node, "./w:pPr/w:pStyle/@w:val", "Normal")
                current["blocks"].append(
                    {"type": "paragraph", "sub": sub, "text": renumber(s), "style": style}
                )

contract = {
    "version": "word-native-1-14-v2",
    "sources": sources,
    "chapters": chapters,
    "style": {
        "page_mm": [215.9, 279.4],
        "margins_mm": [18.2915, 15.9985, 18.2915, 15.24],
        "chapter": "3465A4",
        "subheading": "EA7500",
        "table_header": "E2EDF0",
        "alternate_row": "F6F8F9",
        "border": "D9D9D9",
        "series": ["246A73", "4A86A4", "8AB8C2", "B5D2CD", "C6B694", "E7E9EC"],
    },
}
out = ROOT / "src/wgs_agent/reporting/word_contract.json"
out.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    "chapters",
    len(chapters),
    "charts",
    sum(
        len([v for v in b.get("items", []) if v["type"] == "chart"])
        for c in chapters
        for b in c["blocks"]
    ),
    "flows",
    sum(
        len([v for v in b.get("items", []) if v["type"] == "flow"])
        for c in chapters
        for b in c["blocks"]
    ),
    "tables",
    sum(b["type"] == "table" for c in chapters for b in c["blocks"]),
)
for c in chapters:
    for b in c["blocks"]:
        if b["type"] == "table":
            print(b["id"], " | ".join(b["rows"][0]))
