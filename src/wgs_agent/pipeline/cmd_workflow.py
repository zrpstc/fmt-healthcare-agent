"""Prepare a separate MetaPhlAn3/v30 spectrum; report rendering stays offline."""
from __future__ import annotations


from wgs_fmt_platform.paths import bioinformatics_env_root, bioinformatics_database_root, tool_environment
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from wgs_fmt_platform.paths import bioinformatics_root, project_path, runtime_path
from wgs_agent.reporting import cmd
from .mho_workflow import _digest_file, _json_write, _metadata, _publish
from .sample_registry import require_active, sample_lock

VERSION = "cmd-workflow-v1"


def enabled():
    return (os.environ.get("WGS_HEALTHY_REFERENCE_PROVIDER", "").strip().lower() == "cmd"
            and os.environ.get("WGS_CMD_AUTO_PROFILE", "true").strip().lower()
            not in {"0", "false", "no", "off"})


def _state_path(sample_id):
    if not cmd.valid_sample_id(sample_id):
        raise ValueError("invalid sample ID")
    return cmd.profiles_dir() / ".workflow" / f"{sample_id}.json"


def get_cmd_status(sample_id):
    if not enabled():
        return {"state": "disabled", "ready": False, "provider": "cmd"}
    try:
        value = json.loads(_state_path(sample_id).read_bytes())
        if value.get("sample_id") != sample_id or value.get("state") not in {"running", "available", "failed"}:
            raise ValueError("invalid state")
        if value["state"] == "running":
            try:
                os.kill(int(value["pid"]), 0)
            except (OSError, ValueError, TypeError, KeyError):
                return {"state": "failed", "ready": False, "provider": "cmd", "reason": "worker_interrupted"}
        if value["state"] == "available" and not all((cmd.profiles_dir()/sample_id/name).is_file()
                                                        for name in ("profile.tsv", "provenance.json")):
            return {"state": "pending", "ready": False, "provider": "cmd", "reason": "target_missing"}
        return {k: value[k] for k in ("state", "ready", "reason", "n_subjects", "updated_at") if k in value} | {"provider": "cmd"}
    except FileNotFoundError:
        return {"state": "pending", "ready": False, "provider": "cmd"}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"state": "failed", "ready": False, "provider": "cmd", "reason": "workflow_state_unreadable"}


def _configuration():
    env_root = bioinformatics_env_root()
    python = project_path(os.environ.get("WGS_CMD_PYTHON") or env_root/"fmt-tax/bin/python").resolve(strict=True)
    vendor = runtime_path("WGS_CMD_VENDOR_DIR", "runtime", "vendor", "metaphlan-3.0.14").resolve(strict=True)
    script = (vendor/"metaphlan/metaphlan.py").resolve(strict=True)
    tools = project_path(os.environ.get("WGS_CMD_TOOL_BIN") or env_root/"fmt-tax/bin").resolve(strict=True)
    database = project_path(os.environ.get("WGS_CMD_DATABASE") or bioinformatics_database_root()/"metaphlan3_cmd").resolve(strict=True)
    index = cmd.PIPELINE["database_version"]
    required = [database/(index+ext) for ext in (".pkl", ".1.bt2", ".2.bt2", ".3.bt2", ".4.bt2", ".rev.1.bt2", ".rev.2.bt2")]
    if not all(p.is_file() and p.stat().st_size > 0 for p in required):
        raise FileNotFoundError("incomplete cMD database")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(vendor)
    environment = tool_environment(tools, environment)
    v = subprocess.run([str(python), "-m", "metaphlan.metaphlan", "--version"], capture_output=True, text=True,
                       env=environment, check=True, timeout=30)
    match = re.search(r"MetaPhlAn(?: version)?\s+(\d+\.\d+\.\d+)", v.stdout+v.stderr, re.I)
    if not match or match[1] != cmd.TARGET_VERSION:
        raise ValueError("wrong target profiler")
    pipeline = {**cmd.PIPELINE, "profiler_version": match[1]}
    config = {"pipeline": pipeline, "script_sha256": _digest_file(script),
              "database_files": {f.name: [f.stat().st_size, f.stat().st_mtime_ns] for f in required}}
    return python, script, database, environment, config


def ensure_cmd_profile(sample_id, *, output_root=None, group_json=None, metadata=None, threads=None):
    if not cmd.valid_sample_id(sample_id):
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
    state = {"sample_id": sample_id, "provider": "cmd", "workflow_version": VERSION,
             "state": "running", "pid": os.getpid(), "ready": False}
    def save(**updates):
        state.update(updates, updated_at=datetime.now(UTC).isoformat())
        _json_write(_state_path(sample_id), state)
        return dict(state)
    save()
    try:
        values = _metadata(sample_id, group_json, metadata)
        if str(values.get("qc_status", "")).lower() in {"failed", "fail", "不通过", "未通过"}:
            return save(state="failed", reason="target_qc_failed")
        cmd.load_bundle(cmd.reference_dir())
        root = Path(output_root) if output_root is not None else bioinformatics_root()
        reads = (root/"clean_merged"/f"{sample_id}.dehosted.fastq.gz").resolve(strict=True)
        before = reads.stat()
        input_sha = _digest_file(reads)
        checked = reads.stat()
        if (before.st_size, before.st_mtime_ns) != (checked.st_size, checked.st_mtime_ns):
            return save(state="failed", reason="input_changed")
        python, script, database, env, config = _configuration()
        folder = cmd.profiles_dir()/sample_id
        reused = False
        try:
            old = json.loads((folder/"provenance.json").read_bytes())
            reused = (old.get("sample_id") == sample_id and old.get("workflow_version") == VERSION
                      and old.get("input_sha256") == input_sha
                      and old.get("analysis_configuration") == config
                      and old.get("normalization") == cmd.NORMALIZATION
                      and old.get("profile_sha256") == _digest_file(folder/"profile.tsv"))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        updates = {"workflow_version": VERSION, "sample_id": sample_id, "pipeline": config["pipeline"],
                   "normalization": cmd.NORMALIZATION, "input_sha256": input_sha,
                   "reads": str(reads), "reads_bytes": before.st_size,
                   "reads_mtime_ns": before.st_mtime_ns, "comparison_metadata": values,
                   "source_runs": str(values.get("source_runs", "")), "analysis_configuration": config}
        if not reused:
            folder.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            with tempfile.TemporaryDirectory(prefix=".cmd-profile-", dir=folder.parent) as temp:
                candidate = Path(temp)/sample_id
                candidate.mkdir(mode=0o750)
                args = [str(python), "-m", "metaphlan.metaphlan", str(reads), "--input_type", "fastq",
                        "--bowtie2db", str(database), "--index", cmd.PIPELINE["database_version"],
                        "--bowtie2out", str(candidate/"alignment.bowtie2.bz2"),
                        "--nproc", str(max(1, int(threads or os.environ.get("WGS_CMD_THREADS", "4")))),
                        "-o", str(candidate/"profile.tsv")]
                with (candidate/"run.log").open("wb") as log:
                    subprocess.run(args, env=env, stdout=log, stderr=log, check=True)
                after = reads.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    return save(state="failed", reason="input_changed")
                raw = (candidate/"profile.tsv").read_bytes()
                _, header = cmd.read_target(raw)
                if header.get("database_version") != cmd.PIPELINE["database_version"]:
                    raise ValueError("incompatible target database")
                _json_write(candidate/"provenance.json", {**updates, "profile_sha256": cmd.digest(raw)})
                _publish(candidate, folder)
        else:
            _json_write(folder/"provenance.json", {**old, **updates})
        comparison = cmd.compare(sample_id, values)
        _json_write(folder/"comparison.json", comparison)
        audit = comparison["audit"]
        ready = audit.get("status") == "available"
        return save(state="available" if ready else "failed", ready=ready,
                    reason=audit.get("reason"), n_subjects=audit.get("n_subjects"), reused=reused,
                    reference_version=audit.get("version"))
    except PermissionError:
        return save(state="failed", reason="preparation_permission_denied")
    except FileNotFoundError:
        return save(state="failed", reason="preparation_input_missing")
    except subprocess.SubprocessError:
        return save(state="failed", reason="profiling_failed")
    except (OSError, ValueError, TypeError, KeyError):
        return save(state="failed", reason="preparation_validation_failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--group-json", type=Path)
    parser.add_argument("--threads", type=int)
    args = parser.parse_args()
    result = ensure_cmd_profile(args.sample_id, output_root=args.output_root,
                                group_json=args.group_json, threads=args.threads)
    print(json.dumps(result))
    raise SystemExit(0 if result["state"] in {"available", "disabled"} else 1)


if __name__ == "__main__":
    main()
