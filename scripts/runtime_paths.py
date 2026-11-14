#!/usr/bin/env python3
"""Expose configured runtime paths to shell entry points without exporting credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wgs_fmt_platform.paths import (
    bioinformatics_database_root, bioinformatics_env_root, bioinformatics_root,
    fmt_matching_dir, project_path, resource_root, runtime_path, workspace_root,
)


def configured_paths() -> dict[str, str]:
    resources = resource_root()
    matching = fmt_matching_dir()
    values = {
        "WGS_WORKSPACE": workspace_root(),
        "WGS_FMT_RESOURCE_ROOT": resources,
        "WGS_ENV_ROOT": project_path(os.environ.get("WGS_ENV_ROOT") or ROOT / ".venv"),
        "WGS_BIOINFORMATICS_ENV_ROOT": bioinformatics_env_root(),
        "WGS_BIOINFORMATICS_DATABASE_ROOT": bioinformatics_database_root(),
        "WGS_BIOINFORMATICS_OUTPUT_ROOT": bioinformatics_root(),
        "WGS_RESULTS_DIR": runtime_path("WGS_RESULTS_DIR", "results"),
        "WGS_FMT_MATCHING_DIR": matching,
        "WGS_FMT_MATCHING_DATA_ROOT": matching,
        "WGS_FMT_TRIPLET_MODEL_DIR": project_path(os.environ.get("WGS_FMT_TRIPLET_MODEL_DIR") or resources / "model-training/fmt-triplet-v1"),
        "WGS_FMT_BASELINE_SPECIES": project_path(os.environ.get("WGS_FMT_BASELINE_SPECIES") or matching / "species_abundance_train.csv"),
        "WGS_FMT_MATCH_FILE": project_path(os.environ.get("WGS_FMT_MATCH_FILE") or matching / "match.xlsx"),
        "WGS_CMD_SOURCE_DIR": runtime_path("WGS_CMD_SOURCE_DIR", "reference-sources", "cmd"),
        "WGS_CHAPTER5_DATABASE_ROOT": project_path(os.environ.get("WGS_CHAPTER5_DATABASE_ROOT") or bioinformatics_database_root() / "resistome_mge"),
    }
    result = {key: str(value) for key, value in values.items()}
    result.update(FMT_ROOT=result["WGS_FMT_RESOURCE_ROOT"], ENV_ROOT=result["WGS_BIOINFORMATICS_ENV_ROOT"], DB_ROOT=result["WGS_BIOINFORMATICS_DATABASE_ROOT"])
    return result


def shell_environment() -> dict[str, str]:
    values = configured_paths()
    for name in (
        "WGS_CHAPTER4_ENABLED", "WGS_CHAPTER4_PYTHON", "WGS_CHAPTER5_ENABLED", "WGS_CHAPTER5_PYTHON",
        "WGS_CHAPTER6_ENABLED", "WGS_CHAPTER6_PYTHON", "WGS_FUNCTIONAL_ANNOTATIONS_ENABLED",
        "WGS_FUNCTIONAL_PYTHON", "WGS_HEALTHY_REFERENCE_PROVIDER", "WGS_CMD_PYTHON", "WGS_CMD_THREADS",
        "WGS_CMD_AUTO_PROFILE", "WGS_CMD_REFERENCE_DIR", "WGS_CMD_PROFILES_DIR", "WGS_CMD_VENDOR_DIR",
        "WGS_CMD_TOOL_BIN", "WGS_CMD_DATABASE",
        "WGS_SPECIALIZED_METABOLISM_ENABLED", "THREADS", "METAPHLAN_THREADS", "HUMANN_MEMORY_USE",
        "METAPHLAN_INDEX", "HUMANN_METAPHLAN_INDEX",
    ):
        if name in os.environ:
            value = os.environ[name]
            values[name] = str(project_path(value)) if name.endswith("_PYTHON") and value else value
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--shell", action="store_true")
    group.add_argument("--get", choices=sorted(configured_paths()))
    args = parser.parse_args()
    if args.shell:
        print("\n".join(f"export {name}={shlex.quote(value)}" for name, value in shell_environment().items()))
    elif args.get:
        print(configured_paths()[args.get])
    else:
        print(json.dumps(configured_paths()))


if __name__ == "__main__":
    main()
