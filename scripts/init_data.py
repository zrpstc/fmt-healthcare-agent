#!/usr/bin/env python3
"""Create local runtime directories and empty database schemas; start no services."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wgs_fmt_platform.paths import (  # noqa: E402
    PROJECT_ROOT,
    bioinformatics_root,
    knowledge_db_path,
    runtime_path,
    workspace_root,
)


def init_data() -> None:
    root = workspace_root()
    if root in {Path("/"), Path.home().resolve(), PROJECT_ROOT}:
        raise ValueError("WGS_WORKSPACE must be a dedicated runtime data directory")
    # Never connect to an external database as part of local data preparation.
    database_url = os.environ.get("WGS_DATABASE_URL", "")
    external_database = bool(database_url and not database_url.startswith("sqlite:"))
    os.umask(0o077)
    # Reference databases are provisioned through the configured resource paths.
    # Do not mkdir the legacy databases location, which may be an obsolete symlink.
    for directory in [
        root,
        *(
            root / name
            for name in (
                "logs",
                "run",
                "traces",
                "artifacts",
                "model-registry",
                "models",
                "model-training",
                "fmt",
                "cache",
            )
        ),
        runtime_path("WGS_RESULTS_DIR", "results"),
        runtime_path("WGS_UPLOAD_ROOT", "uploads"),
        runtime_path("WGS_UPLOAD_JOB_ROOT", "upload-jobs"),
        runtime_path("WGS_AGENT_CONFIG_DIR", "agent-config"),
        runtime_path("WGS_AGENT_AUDIT_DIR", "agent-audit"),
        runtime_path("WGS_AGENT_SANDBOX_ROOT", "sandboxes"),
        runtime_path("WGS_SANDBOX_WORKSPACE", "workspaces", "default"),
        runtime_path("WGS_REFERENCE_DIR", "reference"),
        runtime_path("WGS_KB_DIR", "knowledge", "documents"),
        runtime_path("WGS_KB_INDEX_DIR", "knowledge", "index"),
        bioinformatics_root() / "status",
    ]:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    if external_database:
        print("External conversation database skipped; initialize it separately.")
    else:
        from wgs_fmt_platform.infrastructure.database import create_schema

        create_schema()
    db = knowledge_db_path()
    db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(db) as connection:
        connection.executescript(
            (PROJECT_ROOT / "knowledge_base/schema.sql").read_text(encoding="utf-8")
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
            ("1.0.0", "Single-server local schema"),
        )
    print(f"Local data initialized: {root}")
    print("Existing records are preserved; no legacy data imported and no services started.")


if __name__ == "__main__":
    init_data()
