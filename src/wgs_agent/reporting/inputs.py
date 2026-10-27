"""Read existing sample artifacts without running a pipeline or inventing measurements."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def diversity_metrics(records: list[dict], *, complete: bool) -> dict:
    """Compute alpha diversity only for an explicitly complete, valid species profile."""
    values = [finite(row.get("abundance")) for row in records]
    if not complete or not values or any(v is None or v < 0 for v in values):
        return {}
    positive = [v for v in values if v > 0]
    total = math.fsum(positive)
    if not total:
        return {}
    probabilities = [v / total for v in positive]
    richness = len(probabilities)
    shannon = -math.fsum(p * math.log(p) for p in probabilities)
    return {
        "richness": richness,
        "shannon": shannon,
        "simpson": 1 - math.fsum(p * p for p in probabilities),
        "evenness": shannon / math.log(richness) if richness > 1 else None,
        "definition": "Shannon: natural logarithm; Simpson: 1-sum(p^2); Pielou: H/ln(S)",
        "scope": "complete_input_species_profile",
        "method": "relative-abundance-alpha-v1",
    }


def load_existing_report_inputs(sample_id: str, root: Path | None = None) -> dict:
    """Only canonical filenames below the configured bioinformatics root are read."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", sample_id) or sample_id in {".", ".."}:
        raise ValueError("invalid report sample ID")
    if root is None:
        from wgs_fmt_platform.paths import bioinformatics_root

        root = bioinformatics_root()
    root = Path(root).resolve()
    result: dict[str, Any] = {}
    profile = root / "profiles/metaphlan" / f"{sample_id}_profile.tsv"
    ranks = {"p": "phylum", "c": "class", "o": "order", "f": "family", "g": "genus", "s": "species"}
    if profile.is_file() and profile.resolve().is_relative_to(root):
        taxonomy = {rank: [] for rank in ranks.values()}
        pipeline = {"profiler": "MetaPhlAn"}
        invalid = False
        with profile.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("#mpa_"):
                    pipeline["database_version"] = line[1:].strip()
                version = re.match(r"#\s*MetaPhlAn(?: version)?\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", line, re.I)
                if version:
                    pipeline["profiler_version"] = version.group(1)
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.rstrip("\n").split("\t")
                leaf = fields[0].rsplit("|", 1)[-1]
                if len(leaf) < 3 or leaf[0] not in ranks or leaf[1:3] != "__":
                    continue
                value = finite(fields[2]) if len(fields) > 2 else None
                if value is None or value < 0:
                    invalid = True
                    continue
                taxonomy[ranks[leaf[0]]].append(
                    {
                        "name": leaf[3:].replace("_", " "),
                        "abundance": value,
                        "taxon_id": fields[1].rsplit("|", 1)[-1],
                        "lineage": fields[0],
                        "unit": "%",
                        "source_file": str(profile),
                    }
                )
        complete = bool(taxonomy["species"]) and not invalid
        result["taxonomy"] = {
            "ranks": taxonomy,
            "complete": complete,
            "unit": "%",
            "source_file": str(profile),
            "method": "MetaPhlAn taxonomic profile",
            "pipeline": pipeline,
        }
        result["diversity"] = diversity_metrics(taxonomy["species"], complete=complete)
    pathway_file = root / "profiles/humann" / f"{sample_id}_pathabundance_relab.tsv"
    if pathway_file.is_file() and pathway_file.resolve().is_relative_to(root):
        from .functional_metrics import read_humann_pathways
        result["pathways"] = read_humann_pathways(pathway_file)
    return result
