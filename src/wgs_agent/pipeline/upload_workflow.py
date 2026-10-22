"""Upload-to-analysis bridge for the Streamlit application.

Uploaded FASTQ files are stored outside the source tree, validated, described by
the same group JSON contract as the batch runner, and processed by the existing
resumable worker in a detached process.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from wgs_fmt_platform.paths import PROJECT_ROOT, bioinformatics_root, project_path, runtime_path, workspace_root
from .sample_registry import is_deleted, require_active, sample_lock


_SAMPLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class UploadWorkflowSettings:
    workspace: Path
    upload_root: Path
    job_root: Path
    output_root: Path
    worker: Path
    threads: int = 4

    @classmethod
    def from_env(cls) -> "UploadWorkflowSettings":
        workspace = workspace_root()
        return cls(
            workspace=workspace,
            upload_root=runtime_path("WGS_UPLOAD_ROOT", "uploads"),
            job_root=runtime_path("WGS_UPLOAD_JOB_ROOT", "upload-jobs"),
            output_root=bioinformatics_root(),
            worker=project_path(os.environ.get("WGS_BIOINFORMATICS_WORKER") or PROJECT_ROOT / "runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh"),
            threads=max(1, int(os.environ.get("WGS_UPLOAD_THREADS", "4"))),
        )


def validate_sample_id(sample_id: str) -> str:
    value = str(sample_id or "").strip()
    if not _SAMPLE_RE.fullmatch(value):
        raise ValueError("样本 ID 仅允许字母、数字、点、下划线和短横线，长度不超过 80。")
    return value


def _suffix(filename: str) -> str:
    lowered = Path(filename).name.lower()
    for suffix in _FASTQ_SUFFIXES:
        if lowered.endswith(suffix):
            return ".fastq.gz" if suffix.endswith(".gz") else ".fastq"
    raise ValueError(f"不支持的测序文件格式: {Path(filename).name}")


def _copy_upload(source: BinaryIO, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        source.seek(0)
    except (AttributeError, OSError):
        pass
    with temporary.open("wb") as handle:
        while True:
            chunk = source.read(8 * 1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    if size == 0:
        temporary.unlink(missing_ok=True)
        raise ValueError("上传文件为空。")
    temporary.replace(destination)
    return {"path": str(destination), "bytes": size, "sha256": digest.hexdigest()}


def _validate_fastq(path: Path) -> None:
    opener = gzip.open if path.name.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            record = [handle.readline().rstrip("\r\n") for _ in range(4)]
    except (OSError, EOFError) as exc:
        raise ValueError(f"无法读取 FASTQ 文件 {path.name}: {exc}") from exc
    if not record[0].startswith("@") or not record[2].startswith("+") or not record[1]:
        raise ValueError(f"文件 {path.name} 不是有效的 FASTQ（首条记录格式错误）。")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        # Finished detached workers may remain as zombies until their parent
        # reaps them; they cannot write more outputs and must not block deletion.
        try:
            state = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            pass
        return True
    except (OSError, ValueError, TypeError):
        return False


def submit_uploaded_sample(
    sample_id: str,
    layout: str,
    read1: BinaryIO,
    read1_name: str,
    read2: BinaryIO | None = None,
    read2_name: str | None = None,
    *,
    settings: UploadWorkflowSettings | None = None,
) -> dict[str, Any]:
    settings = settings or UploadWorkflowSettings.from_env()
    sample_id = validate_sample_id(sample_id)
    with sample_lock(sample_id, workspace=settings.workspace):
        require_active(sample_id, workspace=settings.workspace)
        return _submit_uploaded_sample(sample_id, layout, read1, read1_name, read2, read2_name, settings=settings)


def _submit_uploaded_sample(
    sample_id: str,
    layout: str,
    read1: BinaryIO,
    read1_name: str,
    read2: BinaryIO | None = None,
    read2_name: str | None = None,
    *,
    settings: UploadWorkflowSettings | None = None,
) -> dict[str, Any]:
    """Persist an upload and launch the existing resumable full pipeline."""
    settings = settings or UploadWorkflowSettings.from_env()
    sample_id = validate_sample_id(sample_id)
    layout = str(layout).lower()
    if layout not in {"single", "paired"}:
        raise ValueError("测序布局必须为 single 或 paired。")
    if layout == "paired" and (read2 is None or not read2_name):
        raise ValueError("双端测序必须同时上传 R1 和 R2。")
    if not settings.worker.is_file():
        raise RuntimeError(f"分析 worker 不存在: {settings.worker}")

    current = get_workflow_status(sample_id, settings=settings)
    if current["state"] in {"running", "complete"}:
        raise RuntimeError(f"样本 {sample_id} 已处于 {current['state']} 状态，不能重复提交。")

    sample_dir = settings.upload_root / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    r1_path = sample_dir / f"{sample_id}_R1{_suffix(read1_name)}"
    copied = [_copy_upload(read1, r1_path)]
    r2_path: Path | None = None
    try:
        _validate_fastq(r1_path)
        if layout == "paired" and read2 is not None and read2_name:
            r2_path = sample_dir / f"{sample_id}_R2{_suffix(read2_name)}"
            copied.append(_copy_upload(read2, r2_path))
            _validate_fastq(r2_path)
            if copied[0]["sha256"] == copied[1]["sha256"]:
                raise ValueError("R1 与 R2 内容完全相同，请检查所选文件。")
    except Exception:
        for item in copied:
            Path(item["path"]).unlink(missing_ok=True)
        raise

    run: dict[str, Any] = {
        "run_accession": sample_id,
        "layout": layout,
        "bytes": sum(item["bytes"] for item in copied),
    }
    if layout == "paired":
        run.update({"r1": str(r1_path), "r2": str(r2_path)})
    else:
        run["single"] = str(r1_path)
    group = {
        "sample_id": sample_id,
        "project": "USER_UPLOAD",
        "sample_accession": sample_id,
        "subject_id": sample_id,
        "timepoint": "uploaded",
        "timepoint_value": "",
        "timepoint_class": "unknown",
        "numeric_time": "",
        "disease": "",
        "host_status": "",
        "study_title": "User uploaded metagenome",
        "layouts": [layout],
        "run_count": 1,
        "total_bytes": run["bytes"],
        "runs": [run],
    }
    group_path = settings.job_root / "groups" / f"{sample_id}.json"
    _atomic_json(group_path, group)

    log_path = settings.job_root / "launcher-logs" / f"{sample_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "bash", str(settings.worker), "--group-json", str(group_path),
        "--threads", str(settings.threads), "--output-root", str(settings.output_root),
    ]
    env = os.environ.copy()
    env["OUTPUT_ROOT"] = str(settings.output_root)
    with log_path.open("ab", buffering=0) as log_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(settings.workspace),
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    job = {
        "sample_id": sample_id,
        "state": "running",
        "submitted_at": _utc_now(),
        "pid": process.pid,
        "layout": layout,
        "files": copied,
        "group_file": str(group_path),
        "launcher_log": str(log_path),
        "settings": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(settings).items()},
    }
    _atomic_json(settings.job_root / "jobs" / f"{sample_id}.json", job)
    return get_workflow_status(sample_id, settings=settings)


def list_uploaded_workflows(
    *, settings: UploadWorkflowSettings | None = None
) -> dict[str, dict[str, Any]]:
    """Include uploads in the sample index before analysis results exist."""
    settings = settings or UploadWorkflowSettings.from_env()
    jobs_dir = settings.job_root / "jobs"
    try:
        paths = list(jobs_dir.glob("*.json"))
    except OSError:
        return {}
    workflows: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            sample_id = validate_sample_id(path.stem)
            if is_deleted(sample_id, workspace=settings.workspace):
                continue
            status = get_workflow_status(sample_id, settings=settings, include_log=False)
        except (OSError, ValueError):
            continue
        if status["state"] != "not_submitted":
            workflows[sample_id] = status
    return workflows


def get_workflow_status(
    sample_id: str, *, settings: UploadWorkflowSettings | None = None,
    include_log: bool = True,
) -> dict[str, Any]:
    settings = settings or UploadWorkflowSettings.from_env()
    sample_id = validate_sample_id(sample_id)
    job_path = settings.job_root / "jobs" / f"{sample_id}.json"
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if not isinstance(job, dict):
            raise ValueError("Invalid upload job record")
    except (OSError, ValueError):
        job = {"sample_id": sample_id, "state": "not_submitted", "pid": None}

    output = settings.output_root
    done = output / "status/done" / f"{sample_id}.done"
    failed = output / "status/failed" / f"{sample_id}.failed"
    artifacts = {
        "uploaded": bool(job.get("files")),
        "quality_control": (output / "qc" / sample_id).is_dir(),
        "dehosted": (output / "clean_merged" / f"{sample_id}.dehosted.fastq.gz").is_file(),
        "taxonomy": (output / "profiles/metaphlan" / f"{sample_id}_profile.tsv").is_file(),
        "functions": (output / "profiles/humann" / f"{sample_id}_pathabundance_relab.tsv").is_file(),
    }
    if done.is_file():
        state = "complete"
    elif failed.is_file():
        state = "failed"
    elif _pid_alive(job.get("pid")):
        state = "running"
    elif job.get("state") == "running":
        state = "failed"
    else:
        state = job.get("state", "not_submitted")
    progress = 0
    for key, value in (("uploaded", 5), ("quality_control", 25), ("taxonomy", 55), ("functions", 90)):
        if artifacts[key]:
            progress = max(progress, value)
    if state == "complete":
        progress = 100
    pipeline_log = output / "logs" / f"{sample_id}.log"
    log_tail = ""
    if include_log:
        try:
            log_tail = "\n".join(pipeline_log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
        except OSError:
            pass
    return {**job, "state": state, "progress": progress, "artifacts": artifacts, "log_tail": log_tail}
