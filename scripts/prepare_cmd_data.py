"""Prepare all cMD reference data below WGS_CMD_DATA_ROOT; safe to rerun at every start.

Steps (each skipped when its output already exists; outputs are published atomically):

1. download the official ExperimentHub catalog;
2. export the cMD 3.18.0 (Bioconductor 3.22) sample metadata with ``export_cmd_metadata.R``;
3. unpack the verified source package (resource list and version);
4. build the larger healthy reference (antibiotics policy ``no_or_unrecorded``);
5. build the cohort-model bundle (gut age, enterotype, health index, disease references);
6. build the MR disease-risk reference (named after the MR weights hash, so new
   weights in ``knowledge_base/disease_mr`` are picked up at the next start).

``deploy/start.sh`` launches this in the background; it holds ``prepare.lock`` so
concurrent starts never run it twice, and records progress in
``prepare-state.json`` (shown by ``deploy/status.sh``).  Needs network access to
bioconductor.org / experimenthub.bioconductor.org and ``Rscript`` on PATH
(base R only; set ``WGS_CMD_R_LIBRARY`` for a private R library).
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from wgs_fmt_platform import cmd_data  # noqa: E402


class StepFailure(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    with os.fdopen(fd, "w") as handle:
        json.dump({**value, "updated_at": _now()}, handle, ensure_ascii=False, indent=2)
    os.replace(name, path)


def step_catalog(paths: dict, fetch=None) -> None:
    target = paths["catalog"]
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        if fetch is not None:
            fetch(cmd_data.CATALOG_URL, partial)
        else:
            with urllib.request.urlopen(cmd_data.CATALOG_URL, timeout=300) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
        connection = sqlite3.connect(f"file:{partial}?mode=ro", uri=True)
        try:
            count = connection.execute(
                "select count(*) from resources where title like '%.relative_abundance'").fetchone()[0]
        finally:
            connection.close()
        if not count:
            raise StepFailure("CATALOG_INVALID", "catalog has no cMD relative_abundance resources")
        os.replace(partial, target)
    except StepFailure:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise StepFailure("CATALOG_DOWNLOAD_FAILED", str(exc)) from exc
    finally:
        partial.unlink(missing_ok=True)


def step_metadata(paths: dict, run=subprocess.run) -> None:
    if paths["metadata"].is_file() and paths["archive"].is_file():
        return
    rscript = shutil.which("Rscript")
    if not rscript:
        raise StepFailure("RSCRIPT_MISSING", "Rscript not found on PATH")
    env = dict(os.environ)
    if env.get("WGS_CMD_R_LIBRARY"):
        env["R_LIBS_USER"] = env["WGS_CMD_R_LIBRARY"]
    result = run([rscript, str(ROOT / "scripts/export_cmd_metadata.R"), "--output-dir", str(paths["metadata_dir"]),
                  "--bioc-release", cmd_data.BIOC_RELEASE], env=env, check=False)
    if result.returncode or not paths["metadata"].is_file():
        raise StepFailure("METADATA_EXPORT_FAILED", "export_cmd_metadata.R failed; see log")


def step_package(paths: dict) -> None:
    description = paths["package"] / "DESCRIPTION"
    if description.is_file():
        return
    if not paths["archive"].is_file():
        raise StepFailure("SOURCE_ARCHIVE_MISSING")
    parent = paths["package"].parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".unpack-", dir=parent) as temporary:
        with tarfile.open(paths["archive"], "r:gz") as archive:
            members = [m for m in archive.getmembers() if m.name.startswith("curatedMetagenomicData/")]
            archive.extractall(temporary, members=members, filter="data")
        unpacked = Path(temporary) / "curatedMetagenomicData"
        version = next((line.split(":", 1)[1].strip() for line in (unpacked / "DESCRIPTION").read_text().splitlines()
                        if line.startswith("Version:")), "")
        if version != cmd_data.CMD_VERSION:
            raise StepFailure("SOURCE_VERSION_MISMATCH", version)
        if not (unpacked / "inst/extdata/metadata.csv").is_file():
            raise StepFailure("SOURCE_PACKAGE_INCOMPLETE")
        os.replace(unpacked, paths["package"])


def _r_library():
    value = os.environ.get("WGS_CMD_R_LIBRARY", "").strip()
    return Path(value) if value else None


def step_healthy(paths: dict) -> None:
    if cmd_data.ready(paths["healthy"]):
        return
    import prepare_cmd_reference as reference
    try:
        result = reference.build(paths["package"], paths["metadata"], paths["catalog"], paths["cache"], paths["healthy"],
                                 _r_library(), antibiotics_policy=cmd_data.ANTIBIOTICS_POLICY)
    except subprocess.CalledProcessError as exc:
        raise StepFailure("MATRIX_EXPORT_FAILED", str(exc)) from exc
    print(json.dumps({"healthy_reference": result}, ensure_ascii=False), flush=True)


def step_cohort(paths: dict) -> None:
    if cmd_data.ready(paths["cohort"]):
        return
    import prepare_cmd_cohort_models as cohort
    try:
        result = cohort.build(paths["package"], paths["metadata"], paths["catalog"], paths["cache"], paths["cohort"],
                              _r_library(), antibiotics_policy=cmd_data.ANTIBIOTICS_POLICY)
    except subprocess.CalledProcessError as exc:
        raise StepFailure("MATRIX_EXPORT_FAILED", str(exc)) from exc
    print(json.dumps({"cohort_models": result}, ensure_ascii=False), flush=True)


def step_disease_risk(paths: dict) -> None:
    if cmd_data.ready(paths["disease_risk"]):
        return
    import prepare_cmd_disease_risk as risk
    try:
        result = risk.build(paths["package"], paths["metadata"], paths["catalog"], paths["cache"], paths["disease_risk"],
                            _r_library(), antibiotics_policy=cmd_data.ANTIBIOTICS_POLICY)
    except subprocess.CalledProcessError as exc:
        raise StepFailure("MATRIX_EXPORT_FAILED", str(exc)) from exc
    print(json.dumps({"disease_risk": result}, ensure_ascii=False), flush=True)


STEPS = (("catalog", step_catalog), ("metadata", step_metadata), ("package", step_package),
         ("healthy", step_healthy), ("cohort", step_cohort), ("disease_risk", step_disease_risk))


def prepare(root: Path, *, steps=STEPS, log: str | None = None) -> dict:
    paths = cmd_data.layout(root)
    try:
        paths["base"].mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"state": "failed", "error": "DATA_ROOT_NOT_WRITABLE", "message": str(exc)}
    handle = os.open(paths["lock"], os.O_RDWR | os.O_CREAT, 0o640)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "already_running"}
        state = {"state": "running", "root": str(root), "log": log, "completed": []}
        for name, function in steps:
            state["step"] = name
            _write_state(paths["state"], state)
            print(json.dumps({"step": name, "at": _now()}), flush=True)
            try:
                function(paths)
            except StepFailure as exc:
                state.update(state="failed", error=exc.code, message=str(exc))
                _write_state(paths["state"], state)
                return state
            except Exception as exc:  # noqa: BLE001 - recorded for the operator, retried at next start
                traceback.print_exc()
                state.update(state="failed", error=name.upper() + "_FAILED", message=f"{type(exc).__name__}: {exc}")
                _write_state(paths["state"], state)
                return state
            state["completed"].append(name)
        state.update(state="ready", step=None, error=None, message=None,
                     healthy=str(paths["healthy"]), cohort=str(paths["cohort"]),
                     disease_risk=str(paths["disease_risk"]))
        _write_state(paths["state"], state)
        return state
    finally:
        os.close(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, help="defaults to WGS_CMD_DATA_ROOT (read from .env)")
    parser.add_argument("--log", help="log file path recorded in the state file")
    args = parser.parse_args()
    if args.data_root is None:
        from wgs_fmt_platform import paths as _paths  # noqa: F401  loads the project .env
        root = cmd_data.data_root()
    else:
        root = args.data_root.expanduser().resolve()
    if root is None:
        print(json.dumps({"state": "disabled", "reason": "WGS_CMD_DATA_ROOT not set"}))
        return 0
    result = prepare(root, log=args.log)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["state"] in {"ready", "already_running"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
