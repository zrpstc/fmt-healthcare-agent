"""Single-server runtime paths, independent of the caller's working directory."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def workspace_root() -> Path:
    return project_path(os.environ.get("WGS_WORKSPACE") or "var")


def runtime_path(variable: str, *parts: str) -> Path:
    value = os.environ.get(variable, "").strip()
    return project_path(value) if value else workspace_root().joinpath(*parts)




def knowledge_db_path() -> Path:
    # Both names are retained for existing API and knowledge-tool callers.
    value = os.environ.get("WGS_KNOWLEDGE_DB") or os.environ.get("WGS_KB_SQLITE_PATH")
    return project_path(value) if value else workspace_root() / "knowledge" / "kb.db"


def bioinformatics_root() -> Path:
    return runtime_path("WGS_BIOINFORMATICS_OUTPUT_ROOT", "bioinformatics")


def legacy_output_root() -> Path:
    value = os.environ.get("WGS_LEGACY_PIPELINE_OUTPUT_DIR")
    return project_path(value) if value else bioinformatics_root() / "legacy"


def runner_status_path() -> Path:
    value = os.environ.get("WGS_RUNNER_STATUS")
    return project_path(value) if value else bioinformatics_root() / "status" / "runner_status.tsv"


def resource_root() -> Path:
    """Resolve shared resources from configuration, independently of the checkout."""
    value = os.environ.get("WGS_FMT_RESOURCE_ROOT") or os.environ.get("FMT_ROOT")
    return project_path(value) if value else workspace_root()


def bioinformatics_env_root() -> Path:
    value = os.environ.get("WGS_BIOINFORMATICS_ENV_ROOT") or os.environ.get("ENV_ROOT")
    return project_path(value) if value else resource_root() / "runtime" / "envs"


def bioinformatics_database_root() -> Path:
    value = os.environ.get("WGS_BIOINFORMATICS_DATABASE_ROOT") or os.environ.get("DB_ROOT")
    return project_path(value) if value else resource_root() / "databases"


def fmt_matching_dir() -> Path:
    value = os.environ.get("WGS_FMT_MATCHING_DIR") or os.environ.get("WGS_FMT_MATCHING_DATA_ROOT")
    return project_path(value) if value else resource_root() / "data" / "fmt-matching"


def tool_environment(tool_bin: str | Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """Scope executable and shared-library lookup to one configured tool environment."""
    environment = dict(os.environ if base is None else base)
    directory = project_path(tool_bin)
    for key, first in (("PATH", directory), ("LD_LIBRARY_PATH", directory.parent / "lib")):
        if key == "LD_LIBRARY_PATH" and not first.is_dir():
            continue
        entries = [str(first), *environment.get(key, "").split(os.pathsep)]
        environment[key] = os.pathsep.join(dict.fromkeys(entry for entry in entries if entry))
    return environment
