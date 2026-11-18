"""Layout of automatically prepared cMD reference data below ``WGS_CMD_DATA_ROOT``.

Only one setting is needed: the parent directory for new databases, e.g.
``WGS_CMD_DATA_ROOT=/storage/fmt-databases``.  ``deploy/start.sh`` then prepares
everything below ``<root>/cmd`` in the background (``scripts/prepare_cmd_data.py``):

    <root>/cmd/catalog/experimenthub.sqlite3       official ExperimentHub catalog
    <root>/cmd/metadata-bioc3.22/                  cMD 3.18.0 sample metadata snapshot
    <root>/cmd/metadata-bioc3.22/package/curatedMetagenomicData   unpacked source
    <root>/cmd/cache/                              downloaded/exported abundance matrices
    <root>/cmd/healthy-cmd3.18.0-no_or_unrecorded/ healthy reference bundle
    <root>/cmd/cohort-models-v1-cmd3.18.0/         cohort-model bundle
    <root>/cmd/prepare-state.json, prepare.lock, logs/

A bundle is used only once its ``manifest.json`` exists (bundles are published
atomically).  Until then the previous locations remain in effect, so reports keep
working while preparation runs.  An explicit ``WGS_CMD_REFERENCE_DIR`` or
``WGS_CMD_COHORT_DIR`` always takes precedence.

Standard library only: imported by the deploy runtime before the app environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

BIOC_RELEASE = "3.22"
CMD_VERSION = "3.18.0"
ANTIBIOTICS_POLICY = "no_or_unrecorded"
COHORT_MODEL_VERSION = "cohort-models-v1"
CATALOG_URL = "https://experimenthub.bioconductor.org/metadata/experimenthub.sqlite3"


def data_root(env: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    value = str(env.get("WGS_CMD_DATA_ROOT") or "").strip()
    return Path(value).expanduser().resolve() if value else None


def layout(root: Path) -> dict[str, Path]:
    base = Path(root) / "cmd"
    metadata = base / f"metadata-bioc{BIOC_RELEASE}"
    return {
        "base": base,
        "catalog": base / "catalog" / "experimenthub.sqlite3",
        "metadata_dir": metadata,
        "metadata": metadata / "sample_metadata.tsv",
        "archive": metadata / "source" / f"curatedMetagenomicData_{CMD_VERSION}.tar.gz",
        "package": metadata / "package" / "curatedMetagenomicData",
        "cache": base / "cache",
        "healthy": base / f"healthy-cmd{CMD_VERSION}-{ANTIBIOTICS_POLICY}",
        "cohort": base / f"{COHORT_MODEL_VERSION}-cmd{CMD_VERSION}",
        "state": base / "prepare-state.json",
        "lock": base / "prepare.lock",
        "logs": base / "logs",
    }


def ready(path: Path) -> bool:
    try:
        return (Path(path) / "manifest.json").is_file()
    except OSError:
        return False


def prepared_dir(kind: str, env: Mapping[str, str] | None = None) -> Path | None:
    """The prepared ``healthy`` or ``cohort`` bundle below the data root, if complete."""
    root = data_root(env)
    if root is None:
        return None
    path = layout(root)[kind]
    return path if ready(path) else None


def summary(env: Mapping[str, str] | None = None) -> dict:
    """Read-only status for ``deploy/status.sh``."""
    root = data_root(env)
    if root is None:
        return {"state": "disabled"}
    paths = layout(root)
    result = {"state": "pending", "root": str(root),
              "healthy_ready": ready(paths["healthy"]), "cohort_ready": ready(paths["cohort"])}
    try:
        recorded = json.loads(paths["state"].read_text())
        if isinstance(recorded, dict):
            result.update({k: recorded[k] for k in ("state", "step", "error", "updated_at", "log") if k in recorded})
    except (OSError, ValueError):
        pass
    if result["state"] == "running" and not _locked(paths["lock"]):
        result["state"] = "interrupted"  # process ended without recording; the next start resumes
    if result["healthy_ready"] and result["cohort_ready"]:
        result["state"] = "ready"
    return result


def _locked(path: Path) -> bool:
    import fcntl
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
