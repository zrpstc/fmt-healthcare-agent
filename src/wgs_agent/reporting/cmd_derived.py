"""Versioned offline consumer-reference assets; no runtime reference-distance fit."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

import numpy as np

VERSION = "cmd-consumer-derived-v1"
SUMMARY = "consumer_derived.json"
DISTANCES = "consumer_distances.npy"
_CACHE = OrderedDict()


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def prepare_derived_reference(base, output, *, block_size=64):
    """Copy a vetted cMD bundle to a NEW immutable bundle with G10 distributions.

    All reference/reference distances are computed offline in float32 row blocks.
    The .npy matrix supports plotting and exact self-exclusion using cached
    distances; runtime never recomputes a reference/reference distance. Every
    reference person's typicality is their median distance to OTHER people in the
    same configured stratum. First and top-five abundance distributions use the
    same independently closed profiles and retain per-person identities.
    """
    from . import cmd
    from .population_reference import stratum, DEFAULT_AGE_BANDS
    from scipy.spatial.distance import cdist

    base, output = Path(base).resolve(), Path(output).resolve()
    if output.exists() or output == base:
        raise ValueError("derived output must be a new directory")
    if not isinstance(block_size, int) or block_size < 1:
        raise ValueError("invalid block size")
    started = time.monotonic()
    manifest, labels, features, matrix, hashes = cmd.load_bundle(base)
    values = matrix.values_array
    if len(labels) < 30:
        raise ValueError("insufficient reference subjects")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cmd-consumer-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for name in ("metadata.tsv", "species_abundance.tsv"):
            shutil.copyfile(base / name, stage / name)
        n = len(labels)
        reused_distances = False
        if manifest.get('consumer_derived', {}).get('schema_version') == VERSION:
            previous, _ = load_derived(base, manifest, hashes)
            if previous['ids'] != list(matrix.ids):
                raise ValueError('derived_reference_identity_mismatch')
            shutil.copyfile(base / DISTANCES, stage / DISTANCES)
            distances = np.load(stage / DISTANCES, mmap_mode='r', allow_pickle=False)
            reused_distances = True
        else:
            distances = np.lib.format.open_memmap(stage / DISTANCES, mode="w+", dtype=np.float32, shape=(n, n))
            for start in range(0, n, block_size):
                stop = min(start + block_size, n)
                distances[start:stop] = cdist(values[start:stop], values, metric="braycurtis").astype(np.float32)
            distances.flush()
        fields = manifest.get("stratify_by", [])
        bounds = manifest.get("age_band_boundaries", list(DEFAULT_AGE_BANDS))
        groups = {}
        for i, label in enumerate(labels):
            key = json.dumps(list(stratum(label, fields, bounds)), ensure_ascii=False)
            groups.setdefault(key, []).append(i)
        strata = {}
        for key, indices in groups.items():
            if len(indices) < 30:
                continue
            medians = []
            for index in indices:
                others = [j for j in indices if j != index]
                medians.append(float(np.median(distances[index, others])))
            ordered = np.sort(values[indices], axis=1)
            strata[key] = {"ids": [matrix.ids[i] for i in indices], "typicality": medians,
                           "first_dominant_share": ordered[:, -1].tolist(),
                           "top5_share": ordered[:, -5:].sum(axis=1).tolist()}
        from .consumer_key_taxa import load_panel, category_matches
        panel = load_panel()
        category_values = {}
        for category in panel['categories']:
            columns = [i for i, feature in enumerate(features) if category_matches(feature, category)]
            category_values[category['id']] = values[:, columns].sum(axis=1).tolist() if columns else [0.0] * n
        payload = {"schema_version": VERSION, "source_sha256": {k: hashes[k] for k in ("metadata.tsv", "species_abundance.tsv")},
                   "ids": list(matrix.ids), "n_subjects": n, "n_features": len(features),
                   "distance_dtype": "float32", "distance_metric": "Bray-Curtis",
                   "typicality_method": "leave_one_person_out_median_within_stratum",
                   "strata": strata,
                   'key_taxa': {'schema_version': 'consumer-key-taxa-reference-v1', 'panel_version': panel['schema_version'],
                                'panel_sha256': panel['sha256'], 'ids': list(matrix.ids), 'categories': category_values},
                   'reused_verified_distances': reused_distances,
                   "build_seconds": round(time.monotonic() - started, 3)}
        (stage / SUMMARY).write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        manifest = {**manifest, "files": {**manifest["files"], SUMMARY: sha256(stage / SUMMARY), DISTANCES: sha256(stage / DISTANCES)},
                    "consumer_derived": {"schema_version": VERSION, "summary": SUMMARY, "distances": DISTANCES,
                                         "source_manifest_sha256": hashes["manifest.json"], "build_seconds": payload["build_seconds"]}}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        del distances
        cmd.load_bundle(stage)
        load_derived(stage, manifest, hashes)
        for path in stage.iterdir():
            path.chmod(0o440)
        stage.rename(output)
    return {"status": "built", "output": str(output), "version": VERSION,
            "n_subjects": n, "build_seconds": payload["build_seconds"],
            "manifest_sha256": sha256(output / "manifest.json"), "files": manifest["files"]}


def load_derived(base, manifest, source_hashes):
    """SHA-validate optional assets independently; absence never selects a fallback."""
    base = Path(base)
    if manifest.get("consumer_derived", {}).get("schema_version") != VERSION:
        raise ValueError("derived_reference_missing")
    expected = {name: manifest.get("files", {}).get(name) for name in (SUMMARY, DISTANCES)}
    if any(not value or sha256(base / name) != value for name, value in expected.items()):
        raise ValueError("derived_reference_sha_mismatch")
    key = (str(base.resolve()), *expected.values())
    if key not in _CACHE:
        payload = json.loads((base / SUMMARY).read_text())
        distances = np.load(base / DISTANCES, mmap_mode="r", allow_pickle=False)
        n = len(payload.get("ids", []))
        if (payload.get("schema_version") != VERSION or n < 30 or len(set(payload["ids"])) != n
                or distances.shape != (n, n) or distances.dtype != np.dtype("float32")
                or any(payload.get("source_sha256", {}).get(name) != source_hashes[name]
                       for name in ("metadata.tsv", "species_abundance.tsv"))):
            raise ValueError("derived_reference_invalid")
        payload["_asset_sha256"] = expected[SUMMARY]
        _CACHE[key] = (payload, distances)
        if len(_CACHE) > 2:
            _CACHE.popitem(last=False)
    return _CACHE[key]


def target_distance_vector(target, matrix, selected, *, block_size=64):
    """Compute ONE sample/reference vector, including reference-absent species."""
    from .population_reference import normalize
    target, _ = normalize(target)
    positions = set(matrix.features)
    vector = np.array([target.get(key, 0) for key in matrix.features], dtype=np.float64)
    extra = sum(value for key, value in target.items() if key not in positions)
    values = matrix.selected(selected)
    result = np.empty(len(selected), dtype=np.float64)
    for start in range(0, len(selected), block_size):
        block = values[start:start + block_size]
        result[start:start + len(block)] = (np.abs(block - vector).sum(axis=1) + extra) / (block.sum(axis=1) + 100)
    return result


def typicality_comparison(target, matrix, selected, derived, *, reference_version=""):
    """Map target median distance to the vetted leave-one-out distribution.

    Self-exclusion/stratum selection is inherited from population.compare. For
    a self-excluded subset, recompute medians from OFFLINE cached distances only;
    neither pairwise distances nor a large float64 matrix are computed at runtime.
    Returns the public comparison plus the shared target distance vector.
    """
    from .population_reference import comparison
    payload, distances = derived
    if len(selected) < 30 or len(set(selected)) != len(selected):
        raise ValueError("insufficient_reference_subjects")
    indices = {sid: i for i, sid in enumerate(payload["ids"])}
    if any(sid not in indices for sid in selected):
        raise ValueError("derived_reference_selection_mismatch")
    group = next((r for r in payload["strata"].values() if set(selected).issubset(r["ids"])), None)
    if group is None:
        raise ValueError("derived_reference_stratum_missing")
    if set(selected) == set(group["ids"]):
        reference_values = group["typicality"]
    else:
        positions = [indices[sid] for sid in selected]
        reference_values = [float(np.median(distances[index, [j for j in positions if j != index]])) for index in positions]
    vector = target_distance_vector(target, matrix, selected)
    median = float(np.median(vector))
    result = {"status": "available", "median_distance": median,
              **comparison(median, reference_values), "n_reference": len(selected),
              "reference_version": reference_version, "derived_version": VERSION,
              "derived_sha256": payload.get("_asset_sha256"),
              "tier": None}
    # comparison.status is statistical, while availability is explicit separately.
    result["comparison_status"] = result["status"]
    result["status"] = "available"
    return result, vector
