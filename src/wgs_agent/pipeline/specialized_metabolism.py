"""Local, traceable specialist metabolism annotations from existing HUMAnN families.

Known UniRef abundances retain their original units. Unrecognized feature rows
are quarantined, never interpreted or exposed; incomplete inputs cannot support
negative calls. EC families and reference-protein clusters are annotation
evidence, not enzyme assays, strain linkage, complete pathways or drug response.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

from .resistome_mge import atomic_json, lock, sample_name

VERSION = "specialized-metabolism-v1"
CATALOG = Path(__file__).with_name("specialized_metabolism_catalog.json")
STATES = {"not_run", "completed", "partial", "missing_input", "invalid_input", "missing_database"}
FAMILY = re.compile(r"UniRef(?:50|90)_[A-Za-z0-9]+")
SPECIAL = {"UNMAPPED", "READS_UNMAPPED", "UNINTEGRATED", "UNGROUPED"}
LIMITATIONS = [
    "丰度是HUMAnN基因家族注释，保留原始单位；不代表酶活、产物浓度或体内转化量。",
    "EC家族可重叠；同一面板的基因取并集，跨面板丰度不能相加。",
    "分层贡献来自HUMAnN分类指派，不证明基因在某菌株的序列连接。",
    "未在谱中报告对应标记不等于功能阴性；药物底物专一性和用药背景分别核验。",
]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def artifact_path(root, sid):
    return Path(root) / "profiles/specialized_metabolism" / (sample_name(sid) + ".json")


def envelope(sid, status="not_run", reason="NOT_RUN", **extra):
    return {"specialized_metabolism_schema": VERSION, "generated_by": VERSION,
            "sample_id": sample_name(sid), "status": status, "reason_code": reason,
            "dietary": [], "drugs": [], "validation": [], "limitations": LIMITATIONS, **extra}


def load_catalog(path=CATALOG):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not value.get("version") or not isinstance(value.get("panels"), list) or not value["panels"]:
        raise ValueError("INVALID_SPECIALIZED_REFERENCE")
    seen = set()
    for panel in value["panels"]:
        if (not isinstance(panel, dict) or not panel.get("id") or panel["id"] in seen
                or panel.get("section") not in {"dietary", "drugs"}
                or not panel.get("name") or not panel.get("reaction") or not panel.get("references")
                or panel.get("kind") not in {"ec_family", "reference_cluster_panel"}):
            raise ValueError("INVALID_SPECIALIZED_REFERENCE")
        seen.add(panel["id"])
        if panel["kind"] == "ec_family" and (not panel.get("ec")
                or not all(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", x) for x in panel["ec"])):
            raise ValueError("INVALID_SPECIALIZED_EC")
        if panel["kind"] == "reference_cluster_panel" and (not panel.get("markers")
                or not all(isinstance(m, dict) and m.get("name") and m.get("families")
                           and all(FAMILY.fullmatch(x) and x.startswith("UniRef90_") for x in m["families"])
                           for m in panel["markers"])):
            raise ValueError("INVALID_SPECIALIZED_MARKER")
        if not all(isinstance(r, dict) and str(r.get("url", "")).startswith("https://") for r in panel["references"]):
            raise ValueError("INVALID_SPECIALIZED_CITATION")
    return value


def read_profile(path):
    community, strata, audit = {}, defaultdict(dict), Counter()
    with Path(path).open(encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 2:
                raise ValueError("INVALID_GENE_COLUMNS")
            audit["input_rows"] += 1
            base, _, taxon = fields[0].partition("|")
            family = base.split(":", 1)[0]
            if family in SPECIAL:
                continue
            if not FAMILY.fullmatch(family):
                audit["quarantined_rows"] += 1
                if re.fullmatch(r"(?:EC:)?[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", base):
                    audit["quarantined_ec_rows"] += 1
                elif re.fullmatch(r"K[0-9]{5}", base):
                    audit["quarantined_ko_rows"] += 1
                elif family.startswith("UniRef"):
                    audit["quarantined_uniref_format_rows"] += 1
                else:
                    audit["quarantined_other_rows"] += 1
                continue
            try:
                value = float(fields[1])
            except ValueError:
                raise ValueError("INVALID_GENE_ABUNDANCE") from None
            if not math.isfinite(value) or value < 0:
                raise ValueError("INVALID_GENE_ABUNDANCE")
            if taxon and taxon != "unclassified" and not re.fullmatch(r"[A-Za-z0-9_.; -]+", taxon):
                raise ValueError("INVALID_GENE_TAXON")
            target = strata[family] if taxon else community
            key = taxon if taxon else family
            if key in target:
                raise ValueError("DUPLICATE_GENE_ROW")
            target[key] = value
    if not community or set(strata) - set(community):
        raise ValueError("INCOMPLETE_GENE_OUTPUT")
    namespaces = {family.split("_", 1)[0] for family in community}
    if len(namespaces) != 1:
        raise ValueError("MIXED_GENE_NAMESPACES")
    if math.fsum(community.values()) <= 0:
        raise ValueError("EMPTY_GENE_PROFILE")
    for family, assignments in strata.items():
        total = math.fsum(assignments.values())
        if total > community[family] + max(1e-8, community[family] * 1e-4):
            raise ValueError("STRATIFIED_ABUNDANCE_EXCEEDS_TOTAL")
    audit["community_gene_families"] = len(community)
    audit["stratified_gene_families"] = len(strata)
    return community, strata, {**dict(audit), "namespace": namespaces.pop(),
                              "complete_recognized_profile": audit["quarantined_rows"] == 0}


def reference_sets(catalog, mapping_dir, namespace):
    wanted = {ec for panel in catalog["panels"] for ec in panel.get("ec", [])}
    result = {ec: set() for ec in wanted}
    path = Path(mapping_dir) / f"map_level4ec_{namespace.lower()}.txt.gz"
    audit = {"status": "missing", "covered_ec": [], "missing_ec": sorted(wanted)}
    if not path.is_file():
        return result, audit
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\r\n").split("\t")
            if fields[0] not in wanted:
                continue
            for family in fields[1:]:
                if not FAMILY.fullmatch(family) or not family.startswith(namespace + "_"):
                    raise ValueError("INVALID_UNIREF_MAPPING")
                result[fields[0]].add(family)
    return result, {"status": "available", "file": str(path), "sha256": digest(path),
                    "covered_ec": sorted(ec for ec, families in result.items() if families),
                    "missing_ec": sorted(ec for ec, families in result.items() if not families)}


def panel_result(panel, community, strata, references, input_audit, unit):
    marker_hits = []
    if panel["kind"] == "ec_family":
        keys = panel["ec"]
        reference = set().union(*(references.get(ec, set()) for ec in keys))
        reference_covered = bool(reference)
        covered_ec = [ec for ec in keys if references.get(ec)]
        missing_ec = [ec for ec in keys if not references.get(ec)]
        marker_label = "本地映射覆盖：" + ("、".join("EC " + ec for ec in covered_ec) or "无")
        if missing_ec:
            marker_label += "；未覆盖：" + "、".join("EC " + ec for ec in missing_ec)
        specificity = "EC酶家族注释；专项底物活性未验证"
    else:
        reference_covered = input_audit["namespace"] == "UniRef90"
        reference = set()
        for marker in panel["markers"]:
            reference.update(marker["families"])
            hits = [family for family in marker["families"] if community.get(family, 0) > 0]
            marker_hits.append({"marker": marker["name"], "gene_families": hits,
                                "abundance": math.fsum(community[f] for f in hits) if hits else None, "unit": unit,
                                "specificity": marker.get("specificity", "reference_protein_cluster")})
        marker_label = "；".join(m["name"] for m in panel["markers"])
        specificity = "实验参考蛋白同簇线索；未作本样本靶基因全长比对"
    members = sorted((family for family in reference if community.get(family, 0) > 0),
                     key=lambda family: (-community[family], family))
    if not reference_covered:
        status, result = "reference_unavailable", "未评估：当前参考或UniRef分辨率不覆盖此项目"
    elif members:
        status = "annotation_detected"
        result = f"检出注释支持；家族丰度 {math.fsum(community[f] for f in members):.6g} {unit}"
    elif not input_audit["complete_recognized_profile"]:
        status, result = "not_assessed_incomplete_input", "输入含隔离条目，本次未取得对应注释支持；不作阴性判定"
    else:
        status, result = "no_annotated_support", "当前基因谱未报告对应参考注释，不等同于功能缺失"
    amounts = defaultdict(list)
    for family in members:
        for taxon, value in strata.get(family, {}).items():
            if value > 0:
                amounts[taxon].append(value)
    contributions = [{"taxon": name, "abundance": math.fsum(values), "unit": unit}
                     for name, values in amounts.items()]
    contributions.sort(key=lambda row: (-row["abundance"], row["taxon"]))
    label = "；".join(row["taxon"] + f"（{row['abundance']:.4g} {unit}）" for row in contributions[:3])
    if len(contributions) > 3:
        label += f"；另{len(contributions)-3}项，见结构化报告"
    if not label:
        label = "未提供对应基因的可用分层归属"
    details = {
        "id": panel["id"], "name": panel["name"], "substrate": panel.get("substrate", panel["name"]),
        "pathway": panel["reaction"], "enzyme": panel["enzyme"] + "；" + marker_label,
        "status": status, "result": result, "abundance": math.fsum(community[f] for f in members) if members else None,
        "unit": unit, "matched_gene_family_count": len(members), "matched_gene_families": members,
        "gene_evidence": [{"gene_family": f, "abundance": community[f], "unit": unit} for f in members],
        "contributors": label, "stratified_contributions": contributions,
        "sequence_support": (f"HUMAnN指派{len(members)}个UniRef家族；" + specificity) if members else result,
        "medication_background": "未提供个体用药信息；仅展示序列注释背景",
        "reference_covered": reference_covered, "annotation_level": specificity,
        "reaction_direction": panel["reaction"], "application_evidence": panel["limitation"],
        "references": copy.deepcopy(panel["references"]), "marker_hits": marker_hits,
        "pathway_completeness": "not_assessed", "substrate_specific_activity": "not_tested",
        "intended_use": "研究性功能注释", "generated_by": VERSION,
    }
    if len(marker_hits) > 1 and members:
        # Different reaction steps do not form an additive pathway-abundance score.
        details["abundance"] = None
        details["result"] = "参考标记同簇线索：" + "；".join(
            hit["marker"] + (f" {hit['abundance']:.6g} {unit}" if hit["abundance"] is not None else " 未报告对应同簇标记")
            for hit in marker_hits)
    if marker_hits:
        details["marker_panel_coverage"] = f"{sum(bool(m['gene_families']) for m in marker_hits)}/{len(marker_hits)}"
        details["result"] += "；参考标记组覆盖 " + details["marker_panel_coverage"] + "，不表示完整通路"
    return details


def analyze_profile(sid, path, mapping_dir, unit, *, catalog_path=CATALOG):
    if unit not in {"relative_abundance", "RPK", "CPM"}:
        return envelope(sid, "invalid_input", "UNSUPPORTED_ABUNDANCE_UNIT")
    try:
        catalog = load_catalog(catalog_path)
        community, strata, audit = read_profile(path)
        references, reference_audit = reference_sets(catalog, mapping_dir, audit["namespace"])
        results = [panel_result(panel, community, strata, references, audit, unit) for panel in catalog["panels"]]
        status = "partial" if not audit["complete_recognized_profile"] or reference_audit["status"] != "available" else "completed"
        value = envelope(sid, status, "QUARANTINED_NON_UNIREF_ROWS" if audit.get("quarantined_rows") else
                         "EC_MAPPING_MISSING" if reference_audit["status"] != "available" else "COMPLETED",
                         unit=unit, source_file=str(path), source_sha256=digest(path), input_audit=audit,
                         reference_version=catalog["version"], reference_sha256=digest(catalog_path),
                         reference_audit=reference_audit)
        for panel, result in zip(catalog["panels"], results):
            value[panel["section"]].append(result)
            value["validation"].append({"id": result["id"], "name": result["name"],
                "annotation_evidence": result["sequence_support"],
                "application_evidence": result["application_evidence"], "intended_use": result["intended_use"],
                "status": result["status"], "references": result["references"]})
        value["summary"] = {"panel_count": len(results),
            "supported_panels": sum(r["status"] == "annotation_detected" for r in results),
            "uncovered_panels": sum(not r["reference_covered"] for r in results)}
        return value
    except PermissionError:
        return envelope(sid, "missing_input", "INPUT_NOT_READABLE")
    except FileNotFoundError:
        return envelope(sid, "missing_input", "INPUT_OR_CATALOG_MISSING")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, EOFError):
        return envelope(sid, "invalid_input", "SPECIALIZED_INPUT_OR_REFERENCE_INVALID")


def run_sample(sid, root, mapping_dir, *, force=False):
    sid = sample_name(sid)
    root, mapping_dir = Path(root), Path(mapping_dir)
    target = artifact_path(root, sid)
    with lock(root / "module-work" / sid / "specialized-metabolism.lock"):
        choices = [(root / "profiles/humann" / f"{sid}_genefamilies_relab.tsv", "relative_abundance"),
                   (root / "profiles/humann" / f"{sid}_genefamilies.tsv", "RPK")]
        try:
            source, unit = next((path, unit) for path, unit in choices if path.is_file())
        except StopIteration:
            value = envelope(sid, "missing_input", "GENE_FAMILIES_MISSING")
        else:
            try:
                hashes = {p.name: digest(p) for p in mapping_dir.glob("map_level4ec_uniref*.txt.gz")}
                fingerprint = hashlib.sha256(json.dumps([VERSION, sid, str(source), unit, digest(source), digest(CATALOG), hashes], sort_keys=True).encode()).hexdigest()
                old = load_specialized_inputs(sid, root, include_missing=False).get("specialized_metabolism", {})
                if not force and old.get("status") in {"completed", "partial"} and old.get("fingerprint") == fingerprint:
                    return old
                input_digest = digest(source)
                value = analyze_profile(sid, source, mapping_dir, unit)
                if value.get("source_sha256") and value["source_sha256"] != input_digest:
                    value = envelope(sid, "invalid_input", "SOURCE_CHANGED_DURING_ANALYSIS")
                value["fingerprint"] = fingerprint
            except (OSError, ValueError):
                value = envelope(sid, "invalid_input", "SPECIALIZED_INPUT_OR_REFERENCE_UNREADABLE")
        atomic_json(target, value)
        return value


def load_specialized_inputs(sid, root, *, include_missing=True):
    root = Path(root).resolve()
    path = artifact_path(root, sid)
    try:
        if not path.resolve().is_relative_to(root):
            raise ValueError("PATH_ESCAPE")
        if not path.is_file():
            return {"specialized_metabolism": envelope(sid)} if include_missing else {}
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("OVERSIZED_SPECIALIZED_RESULT")
        value = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if (not isinstance(value, dict) or value.get("sample_id") != sid
                or value.get("specialized_metabolism_schema") != VERSION or value.get("status") not in STATES):
            raise ValueError("INVALID_SPECIALIZED_RESULT")
        for section in ["dietary", "drugs", "validation"]:
            if not isinstance(value.get(section), list) or not all(isinstance(r, dict) for r in value[section]):
                raise ValueError("INVALID_SPECIALIZED_ROWS")
            for row in value[section]:
                abundance = row.get("abundance")
                if abundance is not None and (isinstance(abundance, bool) or not isinstance(abundance, (int, float))
                        or not math.isfinite(abundance) or abundance < 0):
                    raise ValueError("INVALID_SPECIALIZED_ABUNDANCE")
        return {"specialized_metabolism": value}
    except (OSError, ValueError, TypeError):
        return {"specialized_metabolism": envelope(sid, "invalid_input", "SPECIALIZED_ARTIFACT_UNREADABLE_OR_INVALID")}


def merge_specialized_inputs(fresh, saved):
    current, previous = fresh.get("specialized_metabolism"), saved.get("specialized_metabolism")
    if isinstance(previous, dict) and previous.get("generated_by") != VERSION and any(previous.get(k) for k in ["dietary", "drugs", "validation"]):
        return {"specialized_metabolism": previous}
    if isinstance(current, dict) and current.get("status") != "not_run":
        return {"specialized_metabolism": current}
    if isinstance(previous, dict):
        return {"specialized_metabolism": previous}
    return {}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--mapping-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        value = run_sample(args.sample_id, args.output_root, args.mapping_dir, force=args.force)
        print(json.dumps({k: value[k] for k in ["sample_id", "status", "reason_code", "summary", "input_audit"] if k in value}))
        return 0 if value["status"] in {"completed", "partial"} else 2
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "reason_code": "SPECIALIZED_OPERATION_FAILED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
