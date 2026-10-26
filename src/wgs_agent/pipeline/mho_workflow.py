"""Automatic, resumable preparation of the independent MHOmicrobiome branch."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
from datetime import UTC, datetime
import uuid

from wgs_fmt_platform.paths import PROJECT_ROOT, bioinformatics_root, project_path, runtime_path
from wgs_agent.reporting import mho
from .sample_registry import require_active, sample_lock

VERSION = "mho-workflow-v1"
IDENTITY_FIELDS = ("subject_id", "study_id", "source_runs", "run_ids", "NCBI_accession",
                   "age", "sex", "country", "qc_status")


def enabled() -> bool:
    return (os.environ.get("WGS_HEALTHY_REFERENCE_PROVIDER", "").strip().lower() == "mho"
            and os.environ.get("WGS_MHO_AUTO_PROFILE", "true").strip().lower()
            not in {"0", "false", "no", "off"})


def _json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".publish-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o640)
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _state_path(sample_id: str) -> Path:
    if not mho.valid_sample_id(sample_id):
        raise ValueError("invalid sample ID")
    return mho.profiles_dir() / ".workflow" / f"{sample_id}.json"


def get_mho_status(sample_id: str) -> dict:
    if not enabled():
        return {"state": "disabled", "ready": False}
    try:
        value = json.loads(_state_path(sample_id).read_bytes())
        if not isinstance(value, dict) or value.get("sample_id") != sample_id:
            raise ValueError("invalid state")
        state = value.get("state")
        if state not in {"running", "available", "failed"}:
            raise ValueError("invalid state")
        if state == "running":
            try:
                os.kill(int(value["pid"]), 0)
            except (OSError, ValueError, TypeError, KeyError):
                return {"state": "failed", "ready": False, "reason": "worker_interrupted"}
        if state == "available" and not all((mho.profiles_dir() / sample_id / name).is_file()
                                            for name in ("profile.tsv", "provenance.json")):
            return {"state": "pending", "ready": False, "reason": "target_missing"}
        return {"state": state, "ready": state == "available",
                "reason": value.get("reason"), "n_subjects": value.get("n_subjects"),
                "updated_at": value.get("updated_at")}
    except FileNotFoundError:
        return {"state": "pending", "ready": False}
    except (OSError, ValueError, TypeError):
        return {"state": "failed", "ready": False, "reason": "workflow_state_unreadable"}


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata(sample_id: str, group_json: Path | None, supplied: dict | None) -> dict:
    result = {}
    if group_json is not None:
        group = json.loads(group_json.read_bytes())
        if not isinstance(group, dict) or group.get("sample_id") != sample_id:
            raise ValueError("group sample ID mismatch")
        result.update({key: group[key] for key in IDENTITY_FIELDS if key in group})
        if group.get("project") and group["project"] != "USER_UPLOAD":
            result.setdefault("study_id", group["project"])
        result.setdefault("source_runs", ",".join(str(run.get("run_accession", ""))
                          for run in group.get("runs", []) if isinstance(run, dict)))
    analysis = runtime_path("WGS_RESULTS_DIR", "results") / f"{sample_id}_analysis.json"
    if analysis.is_file():
        data = json.loads(analysis.read_bytes())
        if not isinstance(data, dict) or data.get("sample_id") not in {None, "", sample_id}:
            raise ValueError("analysis sample ID mismatch")
        fields = data.get("metadata") or {}
        if not isinstance(fields, dict):
            raise ValueError("invalid analysis metadata")
        result.update({key: fields[key] for key in IDENTITY_FIELDS if key in fields})
    if supplied:
        result.update({key: supplied[key] for key in IDENTITY_FIELDS if key in supplied})
    return result


def _configuration() -> tuple[dict, Path, Path, Path]:
    env_root = runtime_path("ENV_ROOT", "runtime", "envs")
    executable = project_path(os.environ.get("WGS_MHO_METAPHLAN") or env_root / "mho-tax/bin/metaphlan").resolve(strict=True)
    tool_bin = project_path(os.environ.get("WGS_MHO_TOOL_BIN") or env_root / "fmt-tax/bin").resolve(strict=True)
    db_root = runtime_path("DB_ROOT", "databases")
    database = project_path(os.environ.get("WGS_MHO_DATABASE") or db_root / "metaphlan4").resolve(strict=True)
    pkl = database / (mho.PIPELINE["database_version"] + ".pkl")
    db_stat, exe_stat = pkl.stat(), executable.stat()
    config = {"pipeline": mho.PIPELINE, "normalization": mho.NORMALIZATION,
              "executable": str(executable), "executable_size": exe_stat.st_size,
              "executable_mtime_ns": exe_stat.st_mtime_ns, "database": str(database),
              "database_pkl_size": db_stat.st_size, "database_pkl_mtime_ns": db_stat.st_mtime_ns}
    return config, executable, tool_bin, database


def _verify_version(executable: Path, tool_bin: Path) -> bool:
    environment = dict(os.environ)
    environment["PATH"] = str(tool_bin) + os.pathsep + environment.get("PATH", "")
    result = subprocess.run([str(executable), "--version"], capture_output=True, text=True,
                            check=True, env=environment, timeout=60)
    match = re.search(r"MetaPhlAn(?: version)?\s+(\d+\.\d+\.\d+)", result.stdout + result.stderr, re.I)
    return bool(match and match[1] == mho.PIPELINE["profiler_version"])


def _compatible(folder: Path, sample_id: str, reads: Path, reads_stat, input_sha: str, config: dict) -> bool:
    try:
        raw = (folder / "profile.tsv").read_bytes()
        provenance = json.loads((folder / "provenance.json").read_bytes())
        _, pipeline = mho.read_target(raw)
        if (provenance.get("sample_id") != sample_id
                or provenance.get("pipeline") != mho.PIPELINE
                or provenance.get("normalization") != mho.NORMALIZATION
                or provenance.get("profile_sha256") != mho.digest(raw)
                or pipeline.get("database_version") != mho.PIPELINE["database_version"]
                or any(mho.PIPELINE.get(key) != value for key, value in pipeline.items())):
            return False
        if provenance.get("workflow_version") == VERSION:
            return provenance.get("input_sha256") == input_sha and provenance.get("analysis_configuration") == config
        # Adopt a manually prepared profile only when its recorded input identity
        # still agrees; subsequent invocations use the content digest.
        return (Path(provenance.get("reads", "")).resolve() == reads
                and provenance.get("reads_bytes") == reads_stat.st_size
                and provenance.get("reads_mtime_ns") == reads_stat.st_mtime_ns
                and provenance.get("executable") == config["executable"]
                and provenance.get("database_dir") == config["database"])
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _profile(args):
    spec = importlib.util.spec_from_file_location("_mho_preparation", PROJECT_ROOT / "scripts/mho_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.profile(args)


def _publish(source: Path, destination: Path) -> None:
    if destination.is_symlink():
        raise ValueError("unexpected target symlink")
    if not destination.exists():
        source.rename(destination)
        return
    archive = destination.parent / ".history" / destination.name
    archive.mkdir(parents=True, exist_ok=True, mode=0o750)
    # Linux atomic directory exchange keeps the previous complete profile
    # visible to concurrent report readers until the new one is published.
    libc = ctypes.CDLL(None, use_errno=True)
    exchange = getattr(libc, "renameat2", None)
    if exchange is None:
        raise OSError("atomic directory exchange unavailable")
    exchange.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if exchange(-100, os.fsencode(source), -100, os.fsencode(destination), 2) != 0:
        raise OSError(ctypes.get_errno(), "atomic directory exchange failed")
    source.rename(archive / uuid.uuid4().hex)


def ensure_mho_profile(sample_id: str, *, output_root: Path | None = None,
                       group_json: Path | None = None, metadata: dict | None = None,
                       threads: int | None = None) -> dict:
    if not mho.valid_sample_id(sample_id):
        raise ValueError("invalid sample ID")
    if not enabled():
        return {"state": "disabled", "ready": False}
    try:
        with sample_lock(sample_id):
            require_active(sample_id)
            return _ensure_locked(sample_id, output_root, group_json, metadata, threads)
    except (OSError, ValueError, RuntimeError):
        return {"state": "failed", "ready": False, "reason": "workflow_unavailable"}


def _ensure_locked(sample_id, output_root, group_json, metadata, threads):
    state_path = _state_path(sample_id)
    state = {"sample_id": sample_id, "workflow_version": VERSION, "state": "running", "pid": os.getpid()}
    def save(**updates):
        state.update(updates, updated_at=datetime.now(UTC).isoformat())
        _json_write(state_path, state)
        return dict(state)
    save()
    try:
        values = _metadata(sample_id, group_json, metadata)
        if str(values.get("qc_status", "")).lower() in {"failed", "fail", "不通过", "未通过"}:
            return save(state="failed", ready=False, reason="target_qc_failed")
        # Check the shared reference before spending resources on target profiling.
        mho.load_bundle(mho.reference_dir())
        output_root = Path(output_root) if output_root is not None else bioinformatics_root()
        reads = (output_root / "clean_merged" / f"{sample_id}.dehosted.fastq.gz").resolve(strict=True)
        before = reads.stat()
        input_sha = _digest_file(reads)
        after = reads.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return save(state="failed", ready=False, reason="input_changed")
        threads = max(1, int(threads or os.environ.get("WGS_MHO_THREADS", "4")))
        config, executable, tool_bin, database = _configuration()
        if not _verify_version(executable, tool_bin):
            return save(state="failed", ready=False, reason="incompatible_pipeline")
        folder = mho.profiles_dir() / sample_id
        reused = _compatible(folder, sample_id, reads, before, input_sha, config)
        updates = {"workflow_version": VERSION, "input_sha256": input_sha,
                   "analysis_configuration": config, "comparison_metadata": values}
        if not reused:
            folder.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            with tempfile.TemporaryDirectory(prefix=".auto-mho-", dir=folder.parent) as temporary:
                args = argparse.Namespace(sample_id=sample_id, reads=reads, metaphlan=executable,
                    tool_bin=tool_bin, database=database, profiles_dir=Path(temporary),
                    threads=threads, source_runs=str(values.get("source_runs", "")))
                _profile(args)
                final_stat = reads.stat()
                if (before.st_size, before.st_mtime_ns) != (final_stat.st_size, final_stat.st_mtime_ns):
                    return save(state="failed", ready=False, reason="input_changed")
                candidate = Path(temporary) / sample_id
                provenance = json.loads((candidate / "provenance.json").read_bytes())
                provenance.update(updates)
                _json_write(candidate / "provenance.json", provenance)
                _publish(candidate, folder)
        else:
            provenance = json.loads((folder / "provenance.json").read_bytes())
            if any(provenance.get(key) != value for key, value in updates.items()):
                provenance.update(updates)
                _json_write(folder / "provenance.json", provenance)
        comparison = mho.compare(sample_id, values)
        _json_write(folder / "comparison.json", comparison)
        audit = comparison["audit"]
        available = audit["status"] == "available"
        return save(state="available" if available else "failed", ready=available,
                    reason=audit.get("reason"), n_subjects=audit.get("n_subjects"),
                    reused=reused, input_sha256=input_sha,
                    reference_version=audit.get("version"))
    except FileNotFoundError:
        return save(state="failed", ready=False, reason="preparation_input_missing")
    except PermissionError:
        return save(state="failed", ready=False, reason="preparation_permission_denied")
    except subprocess.SubprocessError:
        return save(state="failed", ready=False, reason="profiling_failed")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return save(state="failed", ready=False, reason="preparation_validation_failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ensure", "backfill"])
    parser.add_argument("--sample-id")
    parser.add_argument("--output-root", type=Path, default=bioinformatics_root())
    parser.add_argument("--group-json", type=Path)
    parser.add_argument("--threads", type=int)
    args = parser.parse_args()
    if args.command == "ensure" and not args.sample_id:
        parser.error("ensure requires --sample-id")
    samples = [args.sample_id] if args.sample_id else [
        p.name.removesuffix(".dehosted.fastq.gz")
        for p in sorted((args.output_root / "clean_merged").glob("*.dehosted.fastq.gz"))]
    failed = False
    for sample_id in samples:
        result = ensure_mho_profile(sample_id, output_root=args.output_root,
                    group_json=args.group_json, threads=args.threads)
        failed |= result["state"] not in {"available", "disabled"}
        # Fixed status only; subprocess output and exception text stay in local files.
        print(json.dumps({"state": result["state"], "ready": result.get("ready", False)}))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
