"""Read-only G11 enzyme-marker evidence from existing, validated gene families.

No bioinformatics executable, job, annotation artifact or production file is
created. Reuse chapter 12's strict recognized-UniRef parser and local EC mapping.
Quarantined rows cannot contribute, and missing markers cannot support absence.
"""
from __future__ import annotations

import math
from pathlib import Path
import re


def existing_enzyme_markers(sample_id, *, root=None, mapping_dir=None):
    from wgs_agent.pipeline.specialized_metabolism import read_profile, reference_sets, digest
    from wgs_fmt_platform.paths import bioinformatics_root, bioinformatics_database_root

    missing = {"status": "unavailable", "reason": "existing_marker_input_unavailable", "results": []}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(sample_id)):
        return missing
    root = Path(root) if root is not None else bioinformatics_root()
    mapping_dir = Path(mapping_dir) if mapping_dir is not None else bioinformatics_database_root() / "humann3/utility_mapping"
    source = root / "profiles/humann" / f"{sample_id}_genefamilies_relab.tsv"
    unit = "relative_abundance"
    if not source.is_file():
        source = root / "profiles/humann" / f"{sample_id}_genefamilies.tsv"
        unit = "RPK"
    if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
        return missing
    try:
        before = digest(source)
        community, strata, input_audit = read_profile(source)
        references, mapping_audit = reference_sets(
            {"panels": [{"ec": ["2.8.3.8", "2.7.2.7"]}]}, mapping_dir, input_audit["namespace"])
        if mapping_audit["status"] != "available":
            return {**missing, "reason": "existing_ec_mapping_unavailable"}
        rows = []
        for ec, families in sorted(references.items()):
            hits = sorted(f for f in families if community.get(f, 0) > 0)
            contributions = {}
            for family in hits:
                for taxon, value in strata.get(family, {}).items():
                    if value > 0:
                        contributions.setdefault(taxon, []).append(value)
            if not hits:
                continue
            values = {taxon: math.fsum(amounts) for taxon, amounts in contributions.items()}
            rows.append({"id": "EC:" + ec, "ec_number": ec, "unit": unit,
                         "abundance": math.fsum(community[f] for f in hits),
                         "contributors": [{"taxon": taxon, "abundance": value, "unit": unit}
                                          for taxon, value in sorted(values.items(), key=lambda r: (-r[1], r[0]))],
                         "contributors_complete": input_audit["complete_recognized_profile"],
                         "gene_families": hits, "evidence_type": "enzyme_marker",
                         "annotation_level": "EC family support, not pathway completeness or enzyme activity"})
        if digest(source) != before:
            return {**missing, "reason": "existing_marker_input_changed"}
        return {"status": "available", "results": rows, "source_file": str(source),
                "source_sha256": before, "mapping_audit": mapping_audit,
                "input_audit": input_audit, "method": "read_only_existing_UniRef_to_EC_marker_lookup",
                "limitations": ["Quarantined rows excluded; missing markers are not functional negatives.",
                                "Marker evidence is never added to pathway abundance or share denominators."]}
    except (OSError, ValueError, TypeError, KeyError):
        return {**missing, "reason": "existing_marker_input_invalid"}
