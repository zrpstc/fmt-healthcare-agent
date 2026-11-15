"""Concentration reference, bound to the exact validated cohort in the saved report."""
from __future__ import annotations
import hashlib
import json


def validated_selection(document):
    """Validate cohort, target identity, stratum and self-exclusion once."""
    population = document.get("template_inputs", {}).get("healthy_comparison") or {}
    audit = population.get("audit", {})
    if audit.get("status") != "available":
        return None
    try:
        from .cmd import load_bundle, reference_dir
        from .population_reference import stratum, _runs, present, comparison, DEFAULT_AGE_BANDS, BOOTSTRAP_SEED, BOOTSTRAP_ITERATIONS
        import numpy as np
        manifest, labels, features, matrix, hashes = load_bundle(reference_dir())
        if hashes != audit.get("file_sha256"):
            return None
        provenance = audit.get("target_provenance") or {}
        metadata = {**provenance.get("comparison_metadata", {}), **document.get("metadata", {})}
        matching = manifest.get("stratify_by", [])
        boundaries = manifest.get("age_band_boundaries", list(DEFAULT_AGE_BANDS))
        target_stratum = stratum(metadata, matching, boundaries)
        if any(not value for value in target_stratum):
            return None
        runs = set().union(*(_runs(metadata.get(k)) for k in ("source_runs", "run_ids", "NCBI_accession")), _runs(provenance.get("source_runs")))
        selected = []
        for label in labels:
            same = (present(metadata.get("subject_id")) and str(metadata["subject_id"]).strip() == str(label["subject_id"]).strip()
                    and (not present(metadata.get("study_id")) or str(metadata["study_id"]).strip() == str(label["study_id"]).strip()))
            if (label["sample_id"] == document["sample_id"] or label.get("original_sample_id") == document["sample_id"]
                    or same or runs & _runs(label["source_runs"])):
                continue
            if stratum(label, matching, boundaries) == target_stratum:
                selected.append(label["sample_id"])
        if len(selected) != audit.get("n_subjects") or len(selected) < manifest.get("minimum_subjects", 30):
            return None
        signature = "sha256:" + hashlib.sha256(json.dumps({"files": hashes, "selected": sorted(selected),
                    "target": audit["target_profile_sha256"], "normalization": audit["normalization"],
                    "bootstrap": [BOOTSTRAP_SEED, BOOTSTRAP_ITERATIONS]}, sort_keys=True).encode()).hexdigest()
        species = population.get("species", [])
        if not species or any(r.get("reference_version") != signature for r in species):
            return None
        return {'manifest': manifest, 'labels': labels, 'features': features, 'matrix': matrix,
                'hashes': hashes, 'selected': selected, 'reference_version': signature,
                'species': species, 'population': population}
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None

def concentration(document):
    cached = document.get('consumer', {}).get('concentration_reference')
    if cached:
        return cached
    context = validated_selection(document)
    if context is None:
        return None
    import numpy as np
    from .population_reference import comparison
    target = sorted((float(r['abundance']) for r in context['species']), reverse=True)
    values = np.sort(context['matrix'].selected(context['selected']), axis=1)
    result = {'basis': 'independent_reference_profile', 'n_subjects': len(context['selected']),
              'reference_version': context['reference_version'],
              'top1': {'value': target[0], **comparison(target[0], values[:, -1])},
              'top5': {'value': sum(target[:5]), **comparison(sum(target[:5]), values[:, -5:].sum(axis=1))}}
    document.setdefault('consumer', {})['concentration_reference'] = result
    return result


def key_taxa_reference(document, panel=None):
    """G14 category distributions use the exact validated, self-excluded cohort.

    No runtime reference-matrix category fit, no fallback from a missing or stale
    panel asset. Shared comparison supplies bootstrap and boundary uncertainty.
    """
    from .consumer_key_taxa import load_panel, category_totals
    from .cmd import reference_dir
    from .cmd_derived import load_derived
    from .population_reference import comparison
    import math
    panel = panel or load_panel()
    context = validated_selection(document)
    if context is None:
        return None
    try:
        payload, _ = load_derived(reference_dir(), context['manifest'], context['hashes'])
        asset = payload.get('key_taxa', {})
        if (asset.get('schema_version') != 'consumer-key-taxa-reference-v1'
                or asset.get('panel_sha256') != panel['sha256']
                or asset.get('panel_version') != panel['schema_version']
                or asset.get('ids') != payload['ids']):
            return None
        positions = {sid:i for i,sid in enumerate(asset['ids'])}
        selected = [positions[sid] for sid in context['selected']]
        target = category_totals({row['species']: float(row['abundance']) for row in context['species']}, panel)
        result = {}
        for category in panel['categories']:
            ident = category['id']; values = asset['categories'][ident]
            if len(values) != len(asset['ids']) or any(not isinstance(value,(int,float)) or not math.isfinite(value) or not 0 <= value <= 100.000001 for value in values):
                return None
            distribution = [values[i] for i in selected]
            result[ident] = {'value': target[ident], **comparison(target[ident], distribution),
                             'n_reference': len(selected), 'reference_version': context['reference_version'],
                             'panel_sha256': panel['sha256'], 'derived_sha256': payload['_asset_sha256'],
                             'basis': 'independent_reference_profile'}
        return result
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None
