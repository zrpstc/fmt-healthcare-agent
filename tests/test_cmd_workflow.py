import contextlib
import gzip
import json
import os
from pathlib import Path
import subprocess

import pytest

from wgs_agent.pipeline import cmd_workflow as workflow
from wgs_agent.reporting import cmd
from test_cmd_population import cohort


@pytest.fixture
def automatic(cohort, tmp_path, monkeypatch):
    base, profiles, data = cohort
    monkeypatch.setenv('WGS_HEALTHY_REFERENCE_PROVIDER', 'cmd')
    monkeypatch.setenv('WGS_CMD_AUTO_PROFILE', 'true')
    monkeypatch.setenv('WGS_RESULTS_DIR', str(tmp_path/'results'))
    monkeypatch.setattr(workflow, 'sample_lock', lambda _: contextlib.nullcontext())
    monkeypatch.setattr(workflow, 'require_active', lambda _: None)
    output = tmp_path/'output'
    reads = output/'clean_merged/NEW.dehosted.fastq.gz'
    reads.parent.mkdir(parents=True)
    with gzip.open(reads, 'wb') as f:
        f.write(b'@read1\nACGT\n+\nIIII\n@read2\nAC\n+\nII\n')
    config = {'pipeline': {**cmd.PIPELINE, 'profiler_version': cmd.TARGET_VERSION}, 'script_sha256': 'synthetic'}
    monkeypatch.setattr(workflow, '_configuration', lambda: (Path('/python'), Path('/script'), Path('/database'), {}, config))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_text(f"#{cmd.PIPELINE['database_version']}\n#MetaPhlAn version 3.0.14\n"
                                  'k__Bacteria|s__A\t1\t30\nk__Bacteria|s__B\t2\t70\n')
    monkeypatch.setattr(workflow.subprocess, 'run', run)
    return output, reads, profiles, calls


def test_cmd_workflow_profiles_counts_reads_and_reuses_valid_artifacts(automatic):
    output, _, profiles, calls = automatic
    first = workflow.ensure_cmd_profile('NEW', output_root=output)
    assert first['ready'] and first['state'] == 'available'
    provenance = json.loads((profiles/'NEW/provenance.json').read_text())
    assert provenance['number_reads'] == 2 and provenance['number_bases'] == 6
    assert provenance['depth_source'] == 'dehosted_fastq_record_count'
    assert workflow.get_cmd_status('NEW')['ready']
    second = workflow.ensure_cmd_profile('NEW', output_root=output)
    assert second['reused'] and len(calls) == 1


def test_cmd_workflow_invalidates_changed_reads_and_excludes_identity(automatic):
    output, reads, profiles, calls = automatic
    workflow.ensure_cmd_profile('NEW', output_root=output)
    with gzip.open(reads, 'ab') as f:
        f.write(b'@read3\nAAA\n+\nIII\n')
    result = workflow.ensure_cmd_profile('NEW', output_root=output, metadata={'study_id': 'STUDY', 'subject_id': 'P0'})
    assert result['ready'] and len(calls) == 2 and result['n_subjects'] == 34
    assert json.loads((profiles/'NEW/provenance.json').read_text())['number_reads'] == 3
    assert (profiles/'.history/NEW').is_dir()


def test_auto_profile_default_provider_and_explicit_disable(monkeypatch):
    monkeypatch.delenv('WGS_HEALTHY_REFERENCE_PROVIDER', raising=False)
    monkeypatch.setenv('WGS_CMD_AUTO_PROFILE', 'true')
    assert workflow.enabled()
    monkeypatch.setenv('WGS_CMD_AUTO_PROFILE', 'false')
    assert workflow.ensure_cmd_profile('SAFE')['state'] == 'disabled'
    monkeypatch.setenv('WGS_HEALTHY_REFERENCE_PROVIDER', 'removed-provider')
    assert not workflow.enabled()


def test_fastq_depth_rejects_malformed_records(tmp_path):
    p = tmp_path/'invalid.fastq'
    p.write_bytes(b'@x\nACGT\n+\nII\n')
    with pytest.raises(ValueError):
        workflow._fastq_depth(p)


def test_postfmt_shell_calls_cmd_directly_and_defaults_to_cmd(tmp_path):
    source = (Path(__file__).parents[1]/'runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh').read_text()
    function = source[source.index('prepare_healthy_comparison() {'):source.index('\n}\n', source.index('prepare_healthy_comparison() {'))+3]
    python = tmp_path/'env/bin/python'
    python.parent.mkdir(parents=True)
    log = tmp_path/'invocation.txt'
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$INVOCATION_LOG"\n')
    python.chmod(0o755)
    env = dict(os.environ, WGS_ENV_ROOT=str(python.parent.parent), APP_ROOT=str(tmp_path),
               OUTPUT_ROOT=str(tmp_path/'output'), SAMPLE_ID='TARGET', GROUP_JSON=str(tmp_path/'group.json'),
               METAPHLAN_THREADS='2', ENV_ROOT=str(tmp_path/'tools'), DB_ROOT=str(tmp_path/'db'),
               INVOCATION_LOG=str(log), WGS_HEALTHY_REFERENCE_PROVIDER='')
    subprocess.run(['bash', '-c', function+'\nprepare_healthy_comparison'], env=env, check=True)
    assert log.read_text().splitlines()[:2] == ['-m', 'wgs_agent.pipeline.cmd_workflow']
