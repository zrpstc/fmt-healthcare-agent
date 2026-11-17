"""Build the consumer web view model (``consumer-report/1``)."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from wgs_fmt_platform.paths import runtime_path

from .format import business_number_violations, text_violations
from .glossary import GlossaryService
from .graph import ReferenceIndex
from .names import NameRegistry, canonical
from .schema import ConsumerReport, GlossaryEntry, MethodNote, Omission, Section
from .sections import (
    actions as actions_section,
    beyond as beyond_section,
    composition as composition_section,
    diversity as diversity_section,
    key_taxa as key_taxa_section,
    learn as learn_section,
    metabolites as metabolites_section,
    more as more_section,
    nutrition as nutrition_section,
    overview as overview_section,
    resistance_section,
    virulence_section,
)
from .sections.context import Context
from .sections.panel import watch_species

BUILDER_VERSION = "consumer-web-builder-v4"
SCHEMA_VERSION = "consumer-report/1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _alias(sample_id: str, metadata: dict, provided: str | None) -> str:
    if provided and provided.strip():
        return provided.strip()
    name = str(metadata.get("name") or "").strip()
    if name:
        return name
    tail = sample_id.rsplit("_", 1)[-1]
    return "样本 " + (tail[-6:] if tail else sample_id[:6])


def _report_date(document: dict, analysis: dict) -> str:
    raw = str(document.get("generated_at") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return raw[:10]
    meta = analysis.get("metadata") if isinstance(analysis.get("metadata"), dict) else {}
    raw = str(meta.get("generated_at") or "")
    return raw[:10] if raw else datetime.now(UTC).date().isoformat()


# --------------------------------------------------------------------- blocks
TEXT_FIELDS = {
    "paragraph": ("text",),
    "callout": ("text",),
    "stacked_bar": ("segments",),
    "ranked_bars": ("rows",),
    "tier_scales": ("rows",),
    "taxon_cards": ("cards",),
    "category_cards": ("cards",),
    "stage_flow": ("stages", "footnote"),
    "table": ("columns", "rows", "footnote"),
    "card_grid": ("cards",),
    "scatter": ("caption",),
}


def _block_texts(block: Any) -> list[str]:
    kind = block.type
    if kind == "paragraph":
        return [block.text]
    if kind == "callout":
        return [block.text]
    if kind == "stacked_bar":
        return [segment.label for segment in block.segments] + [segment.note or "" for segment in block.segments]
    if kind == "donut":
        values = [block.title, block.caption or "", block.center_label or "", block.center_value or ""]
        return values + [segment.label for segment in block.segments] + [segment.note or "" for segment in block.segments]
    if kind == "ranked_bars":
        values = [row.label for row in block.rows] + [block.title or "", block.caption or ""]
        if block.axis:
            values.extend([block.axis.category_label, block.axis.value_label])
        return values
    if kind == "tier_scales":
        return [row.label for row in block.rows] + [row.note or "" for row in block.rows]
    if kind == "taxon_cards":
        return [card.name for card in block.cards] + [card.text or "" for card in block.cards]
    if kind == "category_cards":
        values = []
        for card in block.cards:
            values.extend([card.title, card.text, card.absent_text or ""])
            if card.callout:
                values.append(card.callout.text)
            for member in card.members:
                values.extend([member.name, member.text or ""])
        return values
    if kind == "stage_flow":
        values = [block.footnote]
        for stage in block.stages:
            values.extend([stage.title, stage.backup_label, stage.meaning])
            values.extend(stage.members)
            values.extend(member.name for member in stage.member_details)
        return values
    if kind == "table":
        values = list(block.columns)
        for row in block.rows:
            values.extend(str(cell) for cell in row)
        if block.footnote:
            values.append(block.footnote)
        return values
    if kind == "card_grid":
        values = []
        for card in block.cards:
            values.extend([card.title, card.text, card.status, card.score_label or ""])
            values.extend(str(name) for name in (card.members or []))
            for row in card.details or []:
                values.extend([row.label, row.text])
        return values
    if kind == "scatter":
        return [block.caption]
    return []


def _validate_and_clean(report: ConsumerReport, ctx: Context) -> None:
    """Remove any block that violates the consumer-copy or numeric contract."""
    for section in report.sections:
        if section.id == "learn":
            continue
        if section.intro and (text_violations(section.intro) or business_number_violations(section.intro)):
            section.intro = None
            ctx.omit(section.id, "导语", "正文校验未通过，已隐藏该段")
        for subsection in section.subsections:
            cleaned = []
            for block in subsection.blocks:
                violations = []
                for value in _block_texts(block):
                    violations.extend(text_violations(value))
                    violations.extend(business_number_violations(value))
                if violations:
                    ctx.omit(section.id, f"{subsection.id} 内容块", "正文或数字校验未通过，已隐藏该内容")
                    continue
                cleaned.append(block)
            subsection.blocks = cleaned
            if subsection.summary:
                if text_violations(subsection.summary) or business_number_violations(subsection.summary):
                    subsection.summary = None
                    ctx.omit(section.id, f"{subsection.id} 小结", "小结校验未通过，已隐藏")
            if not subsection.blocks:
                subsection.summary = None
                subsection.graph = None
    # Headline, status cards and key findings are also body copy.
    if text_violations(report.summary.headline) or business_number_violations(report.summary.headline):
        report.summary.headline = "本次报告从菌群组成、功能潜力和检测范围三个方面提供参考。"
        report.summary.headline_source = "rule"
    cards = []
    for card in report.summary.status_cards:
        values = [card.label, card.tier_label, card.line]
        if any(text_violations(value) or business_number_violations(value) for value in values):
            ctx.omit("overview", f"状态卡片 {card.id}", "正文或数字校验未通过，已隐藏该卡片")
            continue
        cards.append(card)
    report.summary.status_cards = cards
    findings = []
    for finding in report.summary.key_findings:
        values = [finding.title, finding.compare, finding.meaning, finding.big.display]
        if any(text_violations(value) or business_number_violations(value) for value in values):
            ctx.omit("overview", f"重点发现 {finding.rank}", "正文或数字校验未通过，已隐藏该条")
            continue
        findings.append(finding)
    report.summary.key_findings = findings
    assessments = []
    for item in report.summary.assessments:
        values = [item.title, item.verdict, item.text, *item.points]
        if any(text_violations(value) or business_number_violations(value) for value in values):
            ctx.omit("overview", f"总体评价 {item.id}", "正文或数字校验未通过，已隐藏该条")
            continue
        assessments.append(item)
    report.summary.assessments = assessments
    report.actions = [
        action for action in report.actions
        if not text_violations(action.because)
        and not text_violations(action.title)
        and not text_violations(action.how)
        and not business_number_violations(action.because + action.title + action.how)
    ]
    # Glossary markup must reference approved (or explicitly allowed pending) terms.
    for section in report.sections:
        if section.id == "learn":
            continue
        for subsection in section.subsections:
            for block in subsection.blocks:
                for value in _block_texts(block):
                    errors = ctx.glossary.validate_markup(value)
                    if errors:
                        ctx.omit(section.id, f"{subsection.id} 术语标记", "术语标记未经审核，已隐藏该内容")
                        subsection.blocks = [item for item in subsection.blocks if item is not block]
                        break

    # Drop empty subsections and sections, but keep the learn appendix.
    for section in report.sections:
        section.subsections = [
            subsection for subsection in section.subsections
            if subsection.blocks or subsection.graph
        ]
    report.sections = [
        section for section in report.sections
        if section.id == "learn" or section.subsections
    ]

    # Every watch taxon must have a conclusion in the virulence source subsection.
    watch_names = {canonical(row["name"]) for row in watch_species(ctx)}
    source_rows = []
    for section in report.sections:
        if section.id != "virulence":
            continue
        for subsection in section.subsections:
            if subsection.id != "virulence-source":
                continue
            for block in subsection.blocks:
                if block.type == "table":
                    source_rows.extend(str(cell) for cell in block.rows)
    missing = [
        name for name in watch_names
        if not any(ctx.names.plain(name) in cell for cell in source_rows)
    ]
    if missing:
        ctx.omit("virulence", "需留意菌的来源结论", "个别菌种没有可用的来源结论，未在正文展示")

    # Graph contract: Chinese labels, no forbidden relation wording, >=2 edges.
    for section in report.sections:
        for subsection in section.subsections:
            graph = subsection.graph
            if graph is None:
                continue
            if len(graph.edges) < 2 or not graph.nodes:
                subsection.graph = None
                ctx.omit(section.id, f"{subsection.id} 知识子图", "清洗后的知识子图不足两条关系")
                continue
            for node in graph.nodes:
                if not re.search(r"[\u4e00-\u9fff]", node.label):
                    subsection.graph = None
                    ctx.omit(section.id, f"{subsection.id} 知识子图", "子图节点标签未全部中文化，已隐藏")
                    break
            if subsection.graph is None:
                continue
            for edge in subsection.graph.edges:
                if any(word in edge.label for word in ("位于", "靶向", "测定方法为", "待审核")):
                    subsection.graph = None
                    ctx.omit(section.id, f"{subsection.id} 知识子图", "子图关系不符合展示规则，已隐藏")
                    break

    report.omissions = [
        Omission(**row) for row in ctx.omissions
    ]


# ------------------------------------------------------------------- downloads
def _csv_rows(path: Path, columns: list[str], rows: Iterable[Iterable[Any]]) -> bool:
    rows = list(rows)
    if not rows:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    os.replace(temporary, path)
    return True


def _export_csvs(document: dict, results_dir: Path, sample_id: str) -> list[dict]:
    downloads = []
    prefix = f"/backend/api/reports/{sample_id}/consumer/downloads/"
    from .sections.virulence import load_vfdb_index
    virulence = document.get("template_inputs", {}).get("virulence") or {}
    markers = virulence.get("markers", []) if isinstance(virulence, dict) else []
    index = load_vfdb_index()
    rows = []
    for marker in markers if isinstance(markers, list) else []:
        meta = index.get(str(marker.get("gene"))) or {}
        rows.append([
            marker.get("gene", ""), meta.get("symbol", ""), meta.get("vf_name", ""),
            meta.get("vf_category", ""), meta.get("host", ""), marker.get("read_count", ""),
            marker.get("breadth", ""), marker.get("identity", ""),
        ])
    path = results_dir / f"{sample_id}_consumer_virulence.csv"
    if _csv_rows(path, ["VFG编号", "基因符号", "毒力因子", "类别", "参考宿主", "支持reads", "覆盖广度", "一致性"], rows):
        downloads.append({"kind": "virulence", "label": "毒力基因明细 CSV", "href": prefix + "virulence"})

    mge = document.get("template_inputs", {}).get("mobile_elements") or {}
    rows = []
    for row in mge.get("results", []) if isinstance(mge, dict) and isinstance(mge.get("results"), list) else []:
        rows.append([row.get("name", ""), row.get("element_type", ""), row.get("family", ""), row.get("mapped_reads", ""), row.get("breadth_coverage", ""), row.get("abundance", "")])
    path = results_dir / f"{sample_id}_consumer_mobile_elements.csv"
    if _csv_rows(path, ["元件名称", "类型", "家族", "支持reads", "覆盖广度", "丰度RPKM"], rows):
        downloads.append({"kind": "mobile_elements", "label": "可移动元件明细 CSV", "href": prefix + "mobile_elements"})

    viruses = document.get("template_inputs", {}).get("dna_viruses") or {}
    rows = []
    for row in viruses.get("records", []) if isinstance(viruses, dict) and isinstance(viruses.get("records"), list) else []:
        rows.append([row.get("name", ""), row.get("reference_genome", ""), row.get("breadth_of_coverage", ""), row.get("depth_of_coverage_mean", ""), row.get("genome_type", ""), row.get("dna_confirmed", "")])
    path = results_dir / f"{sample_id}_consumer_viral_clusters.csv"
    if _csv_rows(path, ["病毒簇", "参考基因组", "覆盖广度", "平均深度", "基因组类型", "DNA确认"], rows):
        downloads.append({"kind": "viral_clusters", "label": "病毒簇明细 CSV", "href": prefix + "viral_clusters"})

    rows = []
    for row in document.get("evidence", {}).values():
        if not isinstance(row, dict) or row.get("kind") not in {"pathway", "function"}:
            continue
        for member in row.get("contributors") or []:
            if isinstance(member, dict):
                rows.append([row.get("id", ""), row.get("name", ""), row.get("value", row.get("abundance", "")), member.get("taxon", ""), member.get("abundance", "")])
    path = results_dir / f"{sample_id}_consumer_pathway_contributions.csv"
    if _csv_rows(path, ["通路ID", "通路名称", "通路丰度", "分类单元", "分层贡献"], rows):
        downloads.append({"kind": "pathway_contributions", "label": "通路贡献明细 CSV", "href": prefix + "pathway_contributions"})
    return downloads


# --------------------------------------------------------------------- build
def build_report(
    sample_id: str,
    *,
    report_path: Path | str | None = None,
    analysis_path: Path | str | None = None,
    results_dir: Path | str | None = None,
    refresh: bool = False,
    allow_pending: bool | None = None,
    alias: str | None = None,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sample_id):
        raise ValueError("invalid_sample_id")
    results_dir = Path(results_dir) if results_dir else runtime_path("WGS_RESULTS_DIR", "results")
    report_path = Path(report_path) if report_path else results_dir / f"{sample_id}_report.json"
    analysis_path = Path(analysis_path) if analysis_path else results_dir / f"{sample_id}_analysis.json"
    if not report_path.is_file():
        raise ValueError("report_missing")
    source_hash = _sha256(report_path)
    glossary = GlossaryService(allow_pending=allow_pending)
    cache_path = results_dir / f"{sample_id}_consumer_report.cache.json"
    cache_key = hashlib.sha256(
        "|".join([
            source_hash, BUILDER_VERSION, "1", glossary.version,
            glossary.review_version(), str(glossary.allow_pending),
        ]).encode()
    ).hexdigest()
    output_path = results_dir / f"{sample_id}_consumer_report.json"
    if not refresh and output_path.is_file() and cache_path.is_file():
        cache = _json_object(cache_path)
        if cache.get("cache_key") == cache_key:
            return _json_object(output_path)
    document = _json_object(report_path)
    analysis = _json_object(analysis_path)
    document["_analysis"] = analysis
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    names = NameRegistry(document)
    refs = ReferenceIndex(document)
    from .graph import GraphBuilder
    graph = GraphBuilder(document, refs)
    ctx = Context(document, analysis, glossary, names, refs, graph)
    ctx.omit("overview", "疾病风险模型分数", "产品要求不展示疾病风险模型分数")
    ctx.omit("overview", "综合健康分与肠龄", "产品要求不使用单一综合分数")
    ctx.omit("symptoms", "症状推断", "本次报告不把症状与菌群做因果推断")

    overview = overview_section.build(ctx)
    sections = [
        composition_section.build(ctx),
        diversity_section.build(ctx),
        key_taxa_section.build(ctx),
        virulence_section.build(ctx),
        resistance_section.build(ctx),
        beyond_section.build(ctx),
        nutrition_section.build(ctx),
        metabolites_section.build(ctx),
        more_section.build(ctx),
    ]
    actions = actions_section.build(ctx)

    # Method references from the saved report become R-ids in the appendix.
    for row in ctx.evidence("method_reference"):
        refs.add_method(row)

    downloads = []
    if (results_dir / f"{sample_id}_health_report.pdf").is_file():
        downloads.append({
            "kind": "professional_pdf",
            "label": "专业版 PDF（给医生看）",
            "href": f"/backend/api/reports/{sample_id}/pdf",
        })
    downloads.extend(_export_csvs(document, results_dir, sample_id))

    learn = learn_section.build(ctx, downloads)

    sample = {
        "sample_id": sample_id,
        "alias": _alias(sample_id, metadata, alias),
        "report_date": _report_date(document, analysis),
        "generated_at": datetime.now(UTC).isoformat(),
        "source_report_sha256": source_hash,
        "builder_version": BUILDER_VERSION,
    }
    report = ConsumerReport(
        schema_version=SCHEMA_VERSION,
        sample=sample,
        summary=overview["summary"],
        sections=[*sections, learn],
        actions=actions["actions"],
        retest=actions["retest"],
        red_flags=actions["red_flags"],
        glossary=[],
        references=[],
        omissions=[],
        methods=[],
        downloads=downloads,
    )
    _validate_and_clean(report, ctx)
    # Re-bind graph first-in-report and ensure the appendix is last.
    report.sections.sort(key=lambda section: 0 if section.id != "learn" else 1)
    for section in report.sections:
        for term_id in section.terms_banner:
            ctx.glossary.used.add(term_id)

    # Methods are top-level, not a body block.
    report.methods = [
        MethodNote(section="参考人群", title="参考数据与对照", body="curatedMetagenomicData 健康标签成人粪便对照，n=3,537；MetaPhlAn 3 / v30，目标谱 MetaPhlAn 3.0.14；已分类物种内归一化；P5–P95 与 bootstrap 经验百分位不是疾病概率。"),
        MethodNote(section="分档", title="分档规则", body="P5/P25/P75/P95 切分；置信区间跨越档位边界时降一档，不使用“明显”。"),
        MethodNote(section="口径", title="两套口径", body="主分析物种谱与 cMD 独立对照谱分开使用，不能相加；组成比较使用对照谱重新归一化数值。"),
        MethodNote(section="典型度", title="组成典型度", body="样本与参考个体的 Bray-Curtis 距离，换算为留一法参考分布中的百分位。"),
        MethodNote(section="功能", title="功能潜力与聚合", body="按类别汇总所有已观测 HUMAnN 通路；EC 注释只补充贡献菌，不加入通路丰度或占比分母。"),
        MethodNote(section="毒力", title="毒力筛查", body="VFDB core 参考序列 reads 筛查；阈值和序列连接证据按模块输出记录；不等同于致病性判断。"),
        MethodNote(section="耐药", title="耐药筛查", body="ResFinder 获得性耐药参考序列 reads 筛查；不覆盖点突变、完整质粒或药敏表型。"),
        MethodNote(section="子图", title="知识子图清洗", body="删除研究分组、探针、编号、测定方法、仪器和样本类型节点；删除“位于”“靶向”“测定方法为”等关系；清洗后少于两条关系不展示。"),
    ]
    report.references = refs.references
    report.omissions = [Omission(**row) for row in ctx.omissions]
    report.glossary = [GlossaryEntry(**row) for row in ctx.glossary.used_entries()]
    final_learn = Section(**learn_section.build(ctx, downloads))
    report.sections = [section for section in report.sections if section.id != "learn"] + [final_learn]
    report.sections.sort(key=lambda section: 0 if section.id != "learn" else 1)
    payload = report.model_dump(by_alias=True)
    _atomic_json(output_path, payload)
    # Displayed taxa without any reviewable text: input for the drafting queue.
    _atomic_json(results_dir / f"{sample_id}_consumer_glossary_needs.json", {
        "sample_id": sample_id,
        "generated_at": sample["generated_at"],
        "needs": sorted(ctx.glossary_needs.values(), key=lambda row: (row["latin"], row["field"])),
    })
    _atomic_json(cache_path, {"cache_key": cache_key, "builder_version": BUILDER_VERSION,
                              "source_report_sha256": source_hash,
                              "glossary_version": glossary.version,
                              "glossary_review_version": glossary.review_version()})
    return payload
