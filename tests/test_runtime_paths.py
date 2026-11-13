import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from wgs_fmt_platform import paths


@pytest.fixture
def clean_paths(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("WGS_", "FMT_")) or name in {"ENV_ROOT", "DB_ROOT"}:
            monkeypatch.delenv(name)


def test_relocated_workspace_drives_resources_without_parent_directory(clean_paths, monkeypatch, tmp_path):
    workspace = tmp_path / "data drive" / "var"
    monkeypatch.setenv("WGS_WORKSPACE", str(workspace))
    monkeypatch.chdir(tmp_path)
    assert paths.resource_root() == workspace
    assert paths.bioinformatics_env_root() == workspace / "runtime/envs"
    assert paths.bioinformatics_database_root() == workspace / "databases"
    assert paths.fmt_matching_dir() == workspace / "data/fmt-matching"


def test_canonical_paths_override_legacy_aliases_and_resolve_against_project(clean_paths, monkeypatch, tmp_path):
    monkeypatch.setenv("FMT_ROOT", str(tmp_path / "legacy"))
    monkeypatch.setenv("ENV_ROOT", str(tmp_path / "legacy-envs"))
    monkeypatch.setenv("DB_ROOT", str(tmp_path / "legacy-db"))
    monkeypatch.setenv("WGS_FMT_RESOURCE_ROOT", "configured/resources")
    monkeypatch.setenv("WGS_BIOINFORMATICS_ENV_ROOT", "configured/envs")
    monkeypatch.setenv("WGS_BIOINFORMATICS_DATABASE_ROOT", "configured/db")
    monkeypatch.chdir(tmp_path)
    assert paths.resource_root() == paths.PROJECT_ROOT / "configured/resources"
    assert paths.bioinformatics_env_root() == paths.PROJECT_ROOT / "configured/envs"
    assert paths.bioinformatics_database_root() == paths.PROJECT_ROOT / "configured/db"


def test_tool_environment_finds_relocated_libraries_without_global_changes(clean_paths, tmp_path):
    prefix = tmp_path / "relocated tool"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib").mkdir()
    original = {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/existing/lib"}
    environment = paths.tool_environment(prefix / "bin", original)
    assert environment["PATH"].split(os.pathsep) == [str(prefix / "bin"), "/usr/bin"]
    assert environment["LD_LIBRARY_PATH"].split(os.pathsep) == [str(prefix / "lib"), "/existing/lib"]
    assert original == {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/existing/lib"}


def test_shell_entrypoint_loads_dotenv_from_any_directory_and_preserves_overrides(clean_paths, tmp_path):
    root = tmp_path / "app checkout"
    for relative in ("scripts/runtime_paths.py", "runtime/scripts/runtime_paths.sh", "src/wgs_fmt_platform/paths.py"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.PROJECT_ROOT / relative, target)
    (root / 'src/wgs_fmt_platform/__init__.py').write_text('')
    workspace = tmp_path / "configured data" / "var"
    database = tmp_path / "configured databases"
    (root / ".env").write_text(
        f'WGS_WORKSPACE="{workspace}"\nWGS_FMT_RESOURCE_ROOT="${{WGS_WORKSPACE}}"\n'
        f'WGS_BIOINFORMATICS_DATABASE_ROOT="{database}"\n'
        'WGS_HEALTHY_REFERENCE_PROVIDER=cmd\nWGS_CLAIM_API_TOKEN=synthetic-test-placeholder\n'
    )
    environment = {**os.environ, "WGS_ENV_ROOT": str(Path(sys.executable).parent.parent)}
    command = ['bash', '-c', 'APP_ROOT="$1"; source "$APP_ROOT/runtime/scripts/runtime_paths.sh"; printf "%s\\n" "$FMT_ROOT" "$ENV_ROOT" "$DB_ROOT" "$WGS_HEALTHY_REFERENCE_PROVIDER"', 'bash', str(root)]
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(workspace), str(workspace / "runtime/envs"), str(database), "cmd"]
    explicit = tmp_path / "explicit override"
    result = subprocess.run(command, cwd=tmp_path, env={**environment, "WGS_WORKSPACE": str(explicit)}, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines()[0] == str(explicit)
    result = subprocess.run([sys.executable, str(root / "scripts/runtime_paths.py"), "--shell"], cwd=tmp_path, env=environment, capture_output=True, text=True, check=True)
    assert "WGS_CLAIM_API_TOKEN" not in result.stdout
    assert "synthetic-test-placeholder" not in result.stdout


def test_runtime_check_detects_loader_failure_before_processing(clean_paths, tmp_path):
    root = tmp_path / 'app'
    for relative in ('scripts/runtime_paths.py', 'runtime/scripts/runtime_paths.sh', 'src/wgs_fmt_platform/paths.py', 'deploy/check-bioinformatics-runtime.sh', 'runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh'):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.PROJECT_ROOT / relative, target)
    (root / 'src/wgs_fmt_platform/__init__.py').write_text('')
    resources = tmp_path / 'moved resources'
    for name in ('fastp', 'kneaddata', 'metaphlan', 'pigz'):
        target = resources / 'runtime/envs/fmt-tax/bin' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#!/bin/sh\nexit 0\n')
        target.chmod(0o755)
    for name in ('humann', 'humann_renorm_table', 'glpsol'):
        target = resources / 'runtime/envs/fmt-func/bin' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#!/bin/sh\nexit 127\n' if name == 'glpsol' else '#!/bin/sh\nexit 0\n')
        target.chmod(0o755)
    (root / '.env').write_text(f'WGS_WORKSPACE="{resources}"\n')
    environment = {**os.environ, 'WGS_ENV_ROOT': str(Path(sys.executable).parent.parent)}
    command = ['bash', str(root / 'deploy/check-bioinformatics-runtime.sh'), '--allow-missing-databases']
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'GLPK_RUNTIME' in result.stderr
    glpsol = resources / 'runtime/envs/fmt-func/bin/glpsol'
    glpsol.write_text('#!/bin/sh\ncase "$LD_LIBRARY_PATH" in "$0"*) exit 1;; */fmt-func/lib*) exit 0;; *) exit 1;; esac\n')
    result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_packaged_database_restores_links_under_configured_root(clean_paths, tmp_path):
    database = tmp_path / 'configured databases'
    source = database / 'humann3'
    source.mkdir(parents=True)
    (source / 'payload').write_text('archive-test-data')
    (source / 'alias').symlink_to('payload')
    os.link(source / 'payload', source / 'hardlink')
    script = (paths.PROJECT_ROOT / 'deploy/package-bioinformatics-runtime.sh').read_text()
    command = next(line.strip().split('|', 1)[0].strip() for line in script.splitlines() if 'tar -C "$DB_ROOT"' in line)
    archive = tmp_path / 'database.tar'
    with archive.open('wb') as stream:
        subprocess.run(['bash', '-c', command], env={**os.environ, 'DB_ROOT': str(database), 'relative': 'databases/humann3'}, stdout=stream, stderr=subprocess.PIPE, check=True)
    target = tmp_path / 'restored elsewhere'
    target.mkdir()
    with archive.open('rb') as stream:
        subprocess.run(['tar', '-C', str(target), '--strip-components=1', '-xf', '-'], stdin=stream, capture_output=True, check=True)
    assert (target / 'humann3/payload').read_text() == 'archive-test-data'
    assert (target / 'humann3/alias').read_text() == 'archive-test-data'
    assert (target / 'humann3/hardlink').read_text() == 'archive-test-data'
