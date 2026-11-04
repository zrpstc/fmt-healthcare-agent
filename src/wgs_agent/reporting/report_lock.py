"""One per-sample lock for analysis refresh and report publication."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re


def acquire_report_lock(directory, sample_id, *, blocking=False):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", sample_id) or sample_id in {".", ".."}:
        raise ValueError("INVALID_SAMPLE_ID")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / f".{sample_id}.report.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    handle = os.fdopen(fd, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BaseException:
        handle.close()
        raise
    return handle


@contextmanager
def report_lock(directory, sample_id, *, blocking=False):
    handle = acquire_report_lock(directory, sample_id, blocking=blocking)
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
