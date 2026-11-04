"""Refresh canonical report modules without replacing unrelated observations."""
import json
from pathlib import Path

from .report_lock import report_lock


def serialize_analysis(original, updated):
    """Compare to the original file, before any in-memory merge or mutation."""
    if updated == json.loads(original):
        return original
    return json.dumps(updated, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def refresh_module_fields(path, sample_id, modules):
    from wgs_agent.pipeline.strain_virulence import atomic_json
    path = Path(path)
    if not modules:
        return path
    with report_lock(path.parent, sample_id):
        original = path.read_bytes()
        value = json.loads(original)
        if not isinstance(value, dict) or value.get("sample_id") not in (None, sample_id):
            raise ValueError("SAMPLE_MISMATCH")
        updated = {**value, **modules}
        if updated != value:
            if path.read_bytes() != original:
                raise RuntimeError("CONCURRENT_ANALYSIS_UPDATE")
            atomic_json(path, updated)
    return path


def refresh_analysis_inputs(path, sample_id, root=None):
    from wgs_agent.pipeline.strain_virulence import load_chapter4_inputs
    from wgs_agent.pipeline.resistome_mge import load_chapter5_inputs
    from wgs_agent.pipeline.non_bacterial import load_chapter6_inputs, merge_chapter6_inputs
    from wgs_agent.pipeline.functional_annotations import load_functional_inputs, merge_functional_inputs
    from wgs_agent.pipeline.strain_virulence import atomic_json
    if root is None:
        from wgs_fmt_platform.paths import bioinformatics_root
        root = bioinformatics_root()
    path = Path(path)
    with report_lock(path.parent, sample_id):
        original = path.read_bytes()
        value = json.loads(original)
        if not isinstance(value, dict) or value.get("sample_id") not in (None, sample_id):
            raise ValueError("SAMPLE_MISMATCH")
        modules = load_chapter4_inputs(sample_id, root, include_missing=False)
        modules.update(load_chapter5_inputs(sample_id, root, include_missing=False))
        chapter6 = load_chapter6_inputs(sample_id, root)
        modules.update({k: v for k, v in merge_chapter6_inputs(chapter6, value).items()
                        if k in value or isinstance(v, dict) and v.get("complete")})
        functional = load_functional_inputs(sample_id, root, include_missing=False)
        modules.update(merge_functional_inputs(functional, value))
        from wgs_agent.pipeline.specialized_metabolism import load_specialized_inputs, merge_specialized_inputs
        modules.update(merge_specialized_inputs(load_specialized_inputs(sample_id, root, include_missing=False), value))
        from wgs_agent.pipeline.disease_features import analyze_disease_features, merge_disease_features
        modules.update(merge_disease_features(analyze_disease_features(value.get("taxonomy")), value))
        updated = {**value, **modules}
        if updated != value:
            if path.read_bytes() != original:
                raise RuntimeError("CONCURRENT_ANALYSIS_UPDATE")
            atomic_json(path, updated)
    return path
