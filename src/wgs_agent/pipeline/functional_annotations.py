"""Traceable EC annotations from complete existing HUMAnN UniRef abundances.

EC groups may overlap. Their sums are annotation abundance, not enzyme activity,
complete pathways, metabolite concentrations, or clinical reference scores.
"""
from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

from .resistome_mge import atomic_json, lock, sample_name

VERSION = "humann-ec-report-v1"
TERMS = ("butyr", "acetate", "propionat", "lactat", "succinat", "bile", "cholesterol", "choloyl", "cholic", "cholate",
         "indole", "tryptoph", "histamin", "putrescin", "cadaver",
         "methan", "sulfate", "trimethylamin", "lipid a", "lipopolysaccharide",
         "peptidoglycan", "sialidase", "neuraminidase", "fucosidase", "mucin",
         "superoxide dismutase", "catalase", "peroxidase", "thioredoxin",
         "glutathione", "bacteriocin", "microcin", "lantibiotic", "nisin", "flagellin")
NOTE = ("UniRef→EC 参考映射的功能潜力注释；未证明酶活性、完整代谢通路或宿主表型。"
        "EC 组可共享基因家族，组间丰度不能相加；未建立人群参考评分。仅覆盖本地映射中完整 EC 编号的相关酶，非全部功能基因。")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def artifact_path(root, sid):
    return Path(root) / "profiles/functional_modules" / (sample_name(sid) + ".json")


def envelope(sid, status="not_run", reason="NOT_RUN", **extra):
    return {"functional_annotation_schema": VERSION, "sample_id": sample_name(sid),
            "status": status, "reason_code": reason, "results": [], "scope": NOTE, **extra}


def read_families(path):
    community, strata = {}, defaultdict(dict)
    special = {"UNMAPPED", "READS_UNMAPPED", "UNINTEGRATED", "UNGROUPED"}
    with Path(path).open(encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 2:
                raise ValueError("INVALID_GENE_COLUMNS")
            value = float(fields[1])
            if not math.isfinite(value) or value < 0:
                raise ValueError("INVALID_GENE_ABUNDANCE")
            base, _, taxon = fields[0].partition("|")
            family = base.split(":", 1)[0]
            if family in special:
                continue
            if not re.fullmatch(r"UniRef(?:50|90)_[A-Za-z0-9]+", family):
                raise ValueError("UNSUPPORTED_GENE_NAMESPACE")
            target = strata[family] if taxon else community
            key = taxon if taxon else family
            if key in target:
                raise ValueError("DUPLICATE_GENE_ROW")
            target[key] = value
    if not community or set(strata) - set(community):
        raise ValueError("INCOMPLETE_GENE_OUTPUT")
    if len({family.split("_", 1)[0] for family in community}) != 1:
        raise ValueError("MIXED_GENE_NAMESPACES")
    return community, strata


def annotate(path, names_path, mapping_path, unit):
    community, strata = read_families(path)
    names = {}
    with gzip.open(names_path, "rt", encoding="utf-8") as f:
        for line in f:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) != 2:
                raise ValueError("INVALID_EC_NAMES")
            if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", fields[0]) and (any(term in fields[1].casefold() for term in TERMS) or re.search(r"\bhydrogenase\b", fields[1], re.I)):
                names[fields[0]] = fields[1]
    rows = []
    matched = set()
    mapped = defaultdict(set)
    with gzip.open(mapping_path, "rt", encoding="utf-8") as f:
        for line in f:
            fields = line.rstrip("\r\n").split("\t")
            ec = fields[0]
            if ec not in names:
                continue
            mapped[ec].update(x for x in fields[1:] if community.get(x, 0) > 0)
    for ec, members in sorted(mapped.items()):
        families = sorted(members, key=lambda x: (-community[x], x))
        if not families:
            continue
        matched.update(families)
        contributors = defaultdict(list)
        for family in families:
            for taxon, amount in strata.get(family, {}).items():
                if amount > 0:
                    contributors[taxon].append(amount)
        values = {name: math.fsum(amounts) for name, amounts in contributors.items()}
        ordered = sorted(values, key=lambda name: (-values[name], name))
        rows.append({"id": "EC:" + ec, "name": names[ec], "ec_number": ec,
                "abundance": math.fsum(community[x] for x in families), "unit": unit,
                "detected": True, "detected_genes": families[:5],
                "gene_evidence": [{"gene_family": x, "abundance": community[x], "unit": unit,
                                   "detected": True} for x in families[:5]],
                "supporting_gene_family_count": len(families),
                "contributors": [{"taxon": x, "abundance": values[x], "unit": unit} for x in ordered[:10]],
                "contributors_complete": len(ordered) <= 10,
                "annotation_level": "EC enzyme family; not a complete pathway",
                "data_type": "metagenomic_annotation", "source_file": str(path),
                    "method": "sum of observed UniRef families mapped to this EC; overlapping groups", "scope": NOTE})
    return rows, {"input_gene_families": len(community), "matched_gene_families": len(matched),
                  "annotated_ec_groups": len(rows)}


def run_sample(sid, root, mapping_dir, *, force=False):
    sid = sample_name(sid)
    root, mapping_dir = Path(root), Path(mapping_dir)
    output = artifact_path(root, sid)
    with lock(root / "module-work" / sid / "functional-annotations.lock"):
        try:
            paths = [(root / "profiles/humann" / f"{sid}_genefamilies_relab.tsv", "relative_abundance"),
                     (root / "profiles/humann" / f"{sid}_genefamilies.tsv", "RPK")]
            available = [(p, unit) for p, unit in paths if p.is_file()]
            if not available:
                value = envelope(sid, "missing_input", "GENE_FAMILIES_MISSING")
            else:
                path, unit = available[0]
                names = mapping_dir / "map_ec_name.txt.gz"
                with path.open(encoding="utf-8-sig") as f:
                    namespace = next(("50" if "UniRef50_" in line else "90" for line in f
                                      if not line.startswith("#") and "UniRef" in line), None)
                mapping = mapping_dir / f"map_level4ec_uniref{namespace}.txt.gz"
                if namespace is None:
                    raise ValueError("UNSUPPORTED_GENE_NAMESPACE")
                if not names.is_file() or not mapping.is_file():
                    value = envelope(sid, "missing_database", "EC_MAPPING_MISSING")
                else:
                    hashes = {"input": sha256(path), "ec_names": sha256(names), "uniref_ec": sha256(mapping)}
                    fingerprint = hashlib.sha256(json.dumps([VERSION, sid, unit, hashes], sort_keys=True).encode()).hexdigest()
                    old = load_functional_inputs(sid, root, include_missing=False).get("functional_modules", {})
                    if not force and old.get("status") == "completed" and old.get("fingerprint") == fingerprint:
                        return old
                    rows, summary = annotate(path, names, mapping, unit)
                    value = envelope(sid, "completed", "COMPLETED", results=rows, summary=summary, unit=unit,
                                     fingerprint=fingerprint, source_sha256=hashes,
                                     source_files=[str(path), str(names), str(mapping)], method=NOTE)
        except PermissionError:
            value = envelope(sid, "missing_input", "INPUT_NOT_READABLE")
        except (OSError, ValueError, EOFError):
            value = envelope(sid, "invalid_input", "ANNOTATION_INPUT_INVALID")
        atomic_json(output, value)
        return value


def load_functional_inputs(sid, root, *, include_missing=True):
    root = Path(root).resolve()
    path = artifact_path(root, sid)
    try:
        if not path.resolve().is_relative_to(root):
            raise ValueError("PATH_ESCAPE")
        if not path.is_file():
            return {"functional_modules": envelope(sid)} if include_missing else {}
        if path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("OVERSIZED_ANNOTATION")
        value = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict) or value.get("sample_id") != sid or value.get("functional_annotation_schema") != VERSION or not isinstance(value.get("results"), list):
            raise ValueError("INVALID_ANNOTATION")
        states = {"not_run", "completed", "missing_input", "missing_database", "invalid_input"}
        if value.get("status") not in states:
            raise ValueError("INVALID_STATE")
        rows = []
        for row in value["results"] if value["status"] == "completed" else []:
            if not isinstance(row, dict) or not re.fullmatch(r"EC:\d+\.\d+\.\d+\.\d+", str(row.get("id", ""))):
                raise ValueError("INVALID_EC_RESULT")
            if not isinstance(row.get("abundance"), (int, float)) or not math.isfinite(row["abundance"]) or row["abundance"] <= 0:
                raise ValueError("INVALID_EC_ABUNDANCE")
            fields = {"id", "name", "ec_number", "abundance", "unit", "detected", "detected_genes",
                      "gene_evidence", "supporting_gene_family_count", "contributors", "contributors_complete",
                      "annotation_level", "data_type", "source_file", "method", "scope"}
            safe = {k: v for k, v in row.items() if k in fields}
            rows.append(safe)
        fields = {"functional_annotation_schema", "sample_id", "status", "reason_code", "summary", "unit",
                  "fingerprint", "source_sha256", "source_files", "method", "scope"}
        result = {k: v for k, v in value.items() if k in fields}
        result["results"] = rows
        return {"functional_modules": result}
    except (OSError, ValueError, TypeError):
        return {"functional_modules": envelope(sid, "invalid_input", "ANNOTATION_UNREADABLE_OR_INVALID")}


def merge_functional_inputs(fresh, saved):
    current, previous = fresh.get("functional_modules"), saved.get("functional_modules")
    if isinstance(current, dict) and current.get("status") != "not_run":
        return {"functional_modules": current}
    if isinstance(previous, (dict, list)):
        return {"functional_modules": previous}
    return {"functional_modules": current} if current is not None else {}


def main():
    import argparse
    from wgs_fmt_platform.paths import PROJECT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mapping-dir", type=Path, default=PROJECT_ROOT / "fmt-databases/humann3/utility_mapping")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        value = run_sample(args.sample_id, args.output_root, args.mapping_dir, force=args.force)
        print(json.dumps({k: value[k] for k in ("status", "reason_code", "summary") if k in value}))
        return 0 if value["status"] == "completed" else 2
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "reason_code": "ANNOTATION_OPERATION_FAILED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
