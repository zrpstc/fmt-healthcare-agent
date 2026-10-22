"""Sample labels, deletion state and cross-process mutation locks."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import tempfile

from wgs_fmt_platform.paths import project_path, workspace_root


class SampleBusyError(RuntimeError):
    pass


class SampleDeletedError(RuntimeError):
    pass


def validate_id(sample_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sample_id):
        raise ValueError("样本 ID 格式不合法。")
    return sample_id


def registry_root(workspace: Path | None = None) -> Path:
    configured = os.environ.get("WGS_SAMPLE_REGISTRY_DIR", "").strip()
    return project_path(configured) if configured else (workspace or workspace_root()) / "sample-registry"


def read_record(sample_id: str, *, workspace: Path | None = None) -> dict:
    path = registry_root(workspace) / "records" / f"{validate_id(sample_id)}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or data.get("sample_id") != sample_id:
        raise ValueError("样本管理记录损坏，请检查服务日志。")
    return data


def records() -> dict[str, dict]:
    directory = registry_root() / "records"
    return {p.stem: read_record(p.stem) for p in directory.glob("*.json")}


def write_record(sample_id: str, data: dict, *, workspace: Path | None = None) -> None:
    directory = registry_root(workspace) / "records"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump({**data, "sample_id": validate_id(sample_id)}, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / f"{sample_id}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def is_deleted(sample_id: str, *, workspace: Path | None = None) -> bool:
    return read_record(sample_id, workspace=workspace).get("deletion_status") == "deleted"


def require_active(sample_id: str, *, workspace: Path | None = None) -> None:
    state = read_record(sample_id, workspace=workspace).get("deletion_status")
    if state == "deleted":
        raise SampleDeletedError("该样本已永久删除；再次上传请使用新的样本 ID。")
    if state in {"deleting", "failed"}:
        raise SampleBusyError("该样本删除尚未完成，请在样本页面重试删除。")


@contextmanager
def sample_lock(sample_id: str, *, workspace: Path | None = None):
    import fcntl

    directory = registry_root(workspace) / "locks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / f"{validate_id(sample_id)}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SampleBusyError("该样本正在上传、生成报告或删除，请稍后重试。") from exc
        yield


def update_metadata(sample_id: str, name: str | None, notes: str | None) -> dict:
    with sample_lock(sample_id):
        require_active(sample_id)
        data = read_record(sample_id)
        data.update(
            name=(name.strip() or sample_id) if name is not None else data.get("name") or sample_id,
            notes=notes.strip() if notes is not None else data.get("notes", ""),
            updated_at=datetime.now(UTC).isoformat(),
        )
        write_record(sample_id, data)
        return {**data, "sample_id": sample_id}
