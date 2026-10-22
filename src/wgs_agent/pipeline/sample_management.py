"""Permanently remove one sample's owned files, preserving shared resources."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
import fcntl
import os
import re
from pathlib import Path
import shutil

from .sample_registry import SampleBusyError, is_deleted, read_record, sample_lock, validate_id, write_record
from .upload_workflow import UploadWorkflowSettings, _pid_alive, get_workflow_status


RESULT_SUFFIXES = (
    "_analysis.json", "_knowledge.json", "_health_report.md", "_health_report.pdf",
    "_report.json", "_report_evidence.json", "_fmt_tsne.png", "_enterotype_tsne.png",
    "_report_species.png", "_report_pathways.png", "_report_diseases.png", "_report_matching.png",
)


def _targets(sample_id: str, settings: UploadWorkflowSettings, results_dir: Path):
    """Exact filenames only: deleting p2 must never match p2_other's outputs."""
    candidates = [
        (settings.upload_root, sample_id),
        (settings.job_root, f"groups/{sample_id}.json"),
        (settings.job_root, f"launcher-logs/{sample_id}.log"),
        (settings.output_root, f"qc/{sample_id}"),
        (settings.output_root, f"work/{sample_id}"),
        (settings.output_root, f"clean_merged/{sample_id}.dehosted.fastq.gz"),
        (settings.output_root, f"logs/{sample_id}.log"),
        (settings.output_root, f"profiles/metaphlan/{sample_id}_profile.tsv"),
        (settings.output_root, f"profiles/metaphlan_humann_vJun23/{sample_id}_profile.tsv"),
        (settings.output_root, f"status/done/{sample_id}.done"),
        (settings.output_root, f"status/failed/{sample_id}.failed"),
    ]
    for suffix in ("pathabundance", "genefamilies", "pathcoverage"):
        for ending in (".tsv", "_relab.tsv"):
            candidates.append((settings.output_root, f"profiles/humann/{sample_id}_{suffix}{ending}"))
    for suffix in RESULT_SUFFIXES:
        candidates.append((results_dir, f"{sample_id}{suffix}"))
        if suffix.endswith(".png"):
            candidates.append((results_dir, f"figures/{sample_id}{suffix}"))
    # Match a fixed catalog topic after the exact sample ID. A p2_other graph
    # cannot become p2's deletion target even though their IDs share a prefix.
    from wgs_agent.reporting.catalog import SECTIONS

    topics = "|".join(re.escape(f"{s.id}_{t.id}") for s in SECTIONS for t in s.topics)
    graph_name = re.compile(re.escape(sample_id) + rf"_(?:{topics})_kg_[0-9a-f]{{12}}\.png")
    if results_dir.is_dir():
        for path in sorted(results_dir.iterdir()):
            if graph_name.fullmatch(path.name):
                candidates.append((results_dir, path.name))
    # Retain the job until the last file is removed, so a partial failure can be
    # retried using the original job record and running-process checks.
    candidates.append((settings.job_root, f"jobs/{sample_id}.json"))
    seen = set()
    targets = []
    for root, relative in candidates:
        root = root.resolve()
        path = root / relative
        # Parents may not redirect deletion into another sample or filesystem.
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError("样本文件路径越出配置目录，已停止删除。")
        if path in seen:
            continue
        seen.add(path)
        targets.append((root, path))
    return targets


def _remove_path(root: Path, path: Path) -> bool:
    if not path.parent.resolve().is_relative_to(root):
        raise ValueError("样本文件路径越出配置目录，已停止删除。")
    if path.is_symlink():
        path.unlink()  # Delete the link itself, never its target.
        return True
    if not path.exists():
        return False
    if not path.resolve().is_relative_to(root) or os.path.ismount(path):
        raise ValueError("样本文件路径无效，已停止删除。")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def delete_sample_files(sample_id: str, results_dir: Path) -> dict:
    validate_id(sample_id)
    settings = UploadWorkflowSettings.from_env()
    with sample_lock(sample_id), ExitStack() as stack:
        if is_deleted(sample_id):
            return {"status": "deleted", "sample_id": sample_id, "removed_paths": 0}
        workflow = get_workflow_status(sample_id, settings=settings, include_log=False)
        stored = workflow.get("settings", {})
        for key in ("workspace", "upload_root", "job_root", "output_root"):
            if stored.get(key) and Path(stored[key]).resolve() != getattr(settings, key).resolve():
                raise SampleBusyError("样本原存储目录与当前配置不一致，已停止删除，请先核对存储配置。")
        runner_lock = settings.output_root / f"status/locks/{sample_id}.lock"
        if workflow["state"] == "running" or _pid_alive(workflow.get("pid")) or runner_lock.exists():
            raise SampleBusyError("样本分析仍在运行或持有任务锁，不能删除；请等待任务结束。")
        # Also respect report generators invoked outside the workspace API.
        report_lock = results_dir / f".{sample_id}.report.lock"
        if report_lock.is_symlink():
            raise ValueError("报告锁路径无效，已停止删除。")
        if report_lock.exists():
            handle = stack.enter_context(report_lock.open("r+"))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SampleBusyError("该样本正在生成报告，暂不能删除。") from exc
        targets = _targets(sample_id, settings, results_dir)
        previous = read_record(sample_id)
        write_record(sample_id, {**previous, "deletion_status": "deleting"})
        removed = 0
        try:
            for root, path in targets:
                removed += _remove_path(root, path)
            if report_lock.exists():
                report_lock.unlink()
        except (OSError, ValueError):
            write_record(sample_id, {**previous, "deletion_status": "failed"})
            raise
        # Keep only an ID tombstone: legacy shared indices must not resurrect a
        # deleted sample, and its name/notes must not remain in the registry.
        write_record(sample_id, {
            "deletion_status": "deleted", "deleted_at": datetime.now(UTC).isoformat(),
        })
        return {"status": "deleted", "sample_id": sample_id, "removed_paths": removed}
