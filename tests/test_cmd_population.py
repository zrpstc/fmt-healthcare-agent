"""Synthetic controls exercise strict cMD contracts, uncertainty and provenance."""
import copy
import csv
from dataclasses import FrozenInstanceError, replace
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from wgs_agent.reporting import cmd, population_reference as population, reference
from wgs_agent.reporting.document import build_document, render_markdown
from wgs_agent.reporting.overview import select_findings
from test_cmd_reference import bundle, target


def rewrite_manifest(base, **changes):
    p = base / 'manifest.json'
    manifest = json.loads(p.read_text())
    manifest.update(changes)
    manifest['files'] = {name: cmd.digest((base/name).read_bytes()) for name in ('metadata.tsv', 'species_abundance.tsv')}
    p.write_text(json.dumps(manifest))
    return manifest


def rewrite_labels(base, change):
    p = base / 'metadata.tsv'
    with p.open() as f:
        rows = list(csv.DictReader(f, delimiter='\t'))
    for i, row in enumerate(rows):
        change(i, row)
    with p.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter='\t')
        writer.writeheader()
        writer.writerows(rows)
    rewrite_manifest(base)


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    base = bundle(tmp_path)
    def enrich(i, row):
        row.update(sample_id=f'D{i}', study_id='STUDY', country='CHN', sex='female', age='40',
                   number_reads=str(100_000+i*1000), number_bases=str(15_000_000+i*150_000))
    rewrite_labels(base, enrich)
    (base/'species_abundance.tsv').write_text('sample_id\ts__A\ts__B\ts__Rare\n' + ''.join(
        f'D{i}\t{20+i}\t{80-i}\t0\n' for i in range(35)))
    rewrite_manifest(base)
    profiles = target(tmp_path, 'TARGET')
    folder = profiles/'TARGET'
    raw = (f"#{cmd.PIPELINE['database_version']}\n#MetaPhlAn version 3.0.14\n"
           'k__Bacteria|s__A\t1\t30\nk__Bacteria|s__B\t2\t70\n').encode()
    (folder/'profile.tsv').write_bytes(raw)
    provenance = json.loads((folder/'provenance.json').read_text())
    provenance.update(profile_sha256=cmd.digest(raw), number_reads=1_000_000, number_bases=150_000_000)
    (folder/'provenance.json').write_text(json.dumps(provenance))
    monkeypatch.setenv('WGS_CMD_REFERENCE_DIR', str(base))
    monkeypatch.setenv('WGS_CMD_PROFILES_DIR', str(profiles))
    monkeypatch.delenv('WGS_HEALTHY_REFERENCE_PROVIDER', raising=False)
    data = {'sample_id': 'TARGET', 'species': {'species_list': [{'species': 'Jan25 species', 'abundance': 99}]},
            'metadata': {'country': 'CHN', 'sex': 'female', 'age': 40}, 'matching': {'preserve': True}}
    return base, profiles, data


def refresh(data):
    return reference.refresh_reference_comparisons(data, {})


def document(data):
    return build_document(data['sample_id'], data.get('species', {}), data.get('compare', {}), {}, {}, {}, {}, {}, {},
                          context={**data.get('metadata', {}), 'health_inputs': data})


def test_bootstrap_reproducible_and_matches_empirical_resampling():
    values = np.arange(35, dtype=float)
    first = population.comparison(12, values)
    assert first == population.comparison(12, list(reversed(values)))
    rng = np.random.default_rng(93)
    resampled = rng.choice(values, (30_000, len(values)), replace=True)
    for p, key in ((.05, 'p5_ci95'), (.95, 'p95_ci95')):
        exact = np.quantile(np.quantile(resampled, p, axis=1, method='linear'), [.025, .975])
        assert first[key] == pytest.approx(exact, abs=1.1)
    percentiles = 100 * ((resampled < 12).sum(axis=1) + .5*(resampled == 12).sum(axis=1))/35
    assert first['percentile_ci95'] == pytest.approx(np.quantile(percentiles, [.025, .975]), abs=3)
    assert first['bootstrap_iterations'] == 1000


def test_borderline_never_high_or_low_and_zero_semantics():
    values = list(range(1, 36))
    row = population.comparison(population.quantile(values, .05), values)
    assert row['status'] == 'borderline' and not population.abnormal(row)
    row = population.comparison(0, values)
    assert row['status'] == 'not_detected' and population.abnormal(row)
    sparse = population.comparison(0, [0, 0] + list(range(1, 34)))
    assert sparse['p5'] > 0 and sparse['status'] == 'not_detected'
    assert sparse['uncertainty_status'] == 'borderline' and not population.abnormal(sparse)
    assert population.comparison(100, values)['status'] == 'high'


def test_outlier_baseline_leave_one_out_and_large_approximation():
    values = np.column_stack((np.arange(35), 100-np.arange(35)))
    summary = population.outlier_baseline(values, np.array([100, 0]))
    assert summary['method'] == 'leave_one_subject_out'
    assert summary['target_outside_count'] == 2 and summary['target_percentile'] > 80
    manual = []
    for i in range(35):
        lo, hi = np.quantile(np.delete(values, i, axis=0), [.05, .95], axis=0)
        manual.append(int(((values[i] < lo) | (values[i] > hi)).sum()))
    assert summary['reference_counts'] == manual
    assert population.outlier_baseline(np.tile(values, (10, 1)), [100, 0])['method'].startswith('full_cohort')


def test_population_audit_depth_studies_and_report(cohort):
    base, _, data = cohort
    rewrite_labels(base, lambda i, row: row.update(study_id='study1' if i < 18 else 'study2'))
    result = refresh(data)
    comparison = result['healthy_comparison']
    assert comparison['audit']['status'] == 'available'
    batch = comparison['audit']['study_batch']
    assert batch['n_studies'] == 2
    assert [r['n_subjects'] for r in batch['studies']] == [18, 17]
    assert len(batch['shannon_median_range']) == 2
    depth = comparison['audit']['sequencing_depth']
    assert depth['target']['number_reads'] == 1_000_000
    assert len(depth['warnings']) == 2
    text = render_markdown(document(result))
    for expected in ('bootstrap 1000', '多重比较基线', '丰富度可能不可比', '研究间批次', 'study1', 'P5的95%CI'):
        assert expected in text


@pytest.mark.parametrize('field', ['country', 'sex', 'age_band'])
def test_stratum_below_thirty_never_pools(cohort, field):
    base, _, data = cohort
    rewrite_labels(base, lambda i, row: row.update(country='CHN' if i < 20 else 'USA',
        sex='female' if i < 20 else 'male', age='40' if i < 20 else '65'))
    rewrite_manifest(base, stratify_by=[field], age_band_boundaries=[18, 30, 50, 70])
    comparison = refresh(data)['healthy_comparison']
    assert comparison['audit']['reason'] == 'insufficient_subjects'
    assert comparison['audit']['n_subjects'] == 20 and not comparison['species']


@pytest.mark.parametrize('missing', [None, '', 'unknown', 'UNKNOWN ', 'NA', 'nan', 'none', 'N/A'])
def test_matching_missing_values_share_one_definition(cohort, missing):
    base, _, data = cohort
    rewrite_manifest(base, stratify_by=['country'])
    data['metadata']['country'] = missing
    assert refresh(data)['healthy_comparison']['audit']['reason'] == 'missing_matching_metadata'


def test_age_boundaries_are_validated_and_inclusive_at_lower_edge(cohort):
    base, _, data = cohort
    assert population.age_band(30, [18, 30, 60]) == '30-<60'
    assert population.age_band(60, [18, 30, 60]) == '60+'
    for boundaries in ([30, 60], [18, 18, 60], [18, float('nan'), 60]):
        rewrite_manifest(base, stratify_by=['age_band'], age_band_boundaries=boundaries)
        assert refresh(data)['healthy_comparison']['audit']['reason'] == 'invalid_reference'


def test_numeric_study_and_subject_ids_exclude_self(cohort):
    base, _, data = cohort
    rewrite_labels(base, lambda i, row: row.update(subject_id=str(i), study_id='7'))
    data['metadata'].update(subject_id=0, study_id=7)
    audit = refresh(data)['healthy_comparison']['audit']
    assert audit['n_subjects'] == 34 and audit['exclusions']['self'] == 1


def test_hash_cache_reuses_parse_and_invalidates_modified_content(cohort, monkeypatch):
    base, _, _ = cohort
    population.clear_bundle_cache()
    calls = []
    original = population._parse_bundle
    def parse(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(population, '_parse_bundle', parse)
    first = cmd.load_bundle(base)
    second = cmd.load_bundle(base)
    assert len(calls) == 1 and first[3] is second[3]
    assert not first[3].values_array.flags.writeable
    first[0]['cohort_id'] = 'mutated'
    assert cmd.load_bundle(base)[0]['cohort_id'] != 'mutated'
    rewrite_manifest(base, cohort_version='changed')
    cmd.load_bundle(base)
    assert len(calls) == 2
    with (base/'metadata.tsv').open('a') as f:
        f.write('corrupt\n')
    with pytest.raises(ValueError):
        cmd.load_bundle(base)


@pytest.mark.parametrize('provider', ['', 'cmd'])
def test_optional_provider_and_unconfigured_reference_no_high_low(tmp_path, monkeypatch, provider):
    monkeypatch.setenv('WGS_HEALTHY_REFERENCE_PROVIDER', provider)
    monkeypatch.setenv('WGS_CMD_REFERENCE_DIR', str(tmp_path/'absent'))
    data = {'sample_id': 'TARGET', 'species': {'species_list': [{'species': 'A', 'abundance': 1}]}}
    result = refresh(data)
    assert result['healthy_comparison']['audit']['reason'] == 'reference_missing'
    assert not result['healthy_comparison']['species']
    assert '未建立健康对照' in render_markdown(document(result))


def test_unsupported_provider_is_explicit_and_logged(cohort, monkeypatch, caplog):
    monkeypatch.setenv('WGS_HEALTHY_REFERENCE_PROVIDER', 'removed-provider')
    result = refresh(cohort[2])
    assert result['healthy_comparison']['audit']['reason'] == 'unsupported_provider'
    assert 'only cmd is supported' in caplog.text
    assert not result['healthy_comparison']['species']


@pytest.mark.parametrize('old_provider', ['mho', 'healthy-reference-v1'])
def test_historical_provider_results_are_ignored_on_regeneration(cohort, old_provider):
    base, _, data = cohort
    data['healthy_comparison'] = {'audit': {'provider': old_provider}, 'species': [{'p5': 9, 'p95': 10, 'status': 'high'}]}
    data['species']['species_list'][0].update(p5=1, p95=2, percentile=100, status='high', generated_by=old_provider)
    data['species'].update(n_high=1, n_unknown=0)
    data['compare'] = {'comparison': copy.deepcopy(data['species']['species_list']), 'n_abnormal': 1}
    data['diversity'] = {'shannon': 1, 'longitudinal': [{'value': 2}], 'reference_comparisons': [{'status': 'low'}]}
    original = copy.deepcopy(data)
    result = refresh(data)
    assert data == original and result['matching'] == data['matching']
    assert result['healthy_comparison']['audit']['provider'] == 'cmd'
    assert result['healthy_comparison']['species'] != data['healthy_comparison']['species']
    for key, field in (('species', 'species_list'), ('compare', 'comparison')):
        row = result[key][field][0]
        assert row['abundance'] == 99 and row['status'] == 'unknown'
        assert 'p5' not in row and 'percentile' not in row
    assert result['diversity']['reference_comparisons'] == []
    assert result['species']['n_high'] == 0 and result['species']['n_unknown'] == 1
    assert result['diversity']['longitudinal'] == data['diversity']['longitudinal']
    rewrite_manifest(base, minimum_subjects=99)
    assert not refresh(result)['healthy_comparison']['species']


def test_not_detected_and_borderline_agree_in_counts_overview_and_tables(cohort):
    _, profiles, data = cohort
    folder = profiles/'TARGET'
    raw = (f"#{cmd.PIPELINE['database_version']}\n#MetaPhlAn version 3.0.14\n"
           'k__Bacteria|s__B\t2\t100\n').encode()
    (folder/'profile.tsv').write_bytes(raw)
    p = json.loads((folder/'provenance.json').read_text())
    p['profile_sha256'] = cmd.digest(raw)
    (folder/'provenance.json').write_text(json.dumps(p))
    result = refresh(data)
    comparison = result['healthy_comparison']
    a = next(r for r in comparison['species'] if r['species'] == 'a')
    assert a['status'] == 'not_detected' and population.abnormal(a)
    assert comparison['n_abnormal'] == sum(population.abnormal(r) for r in comparison['species'])
    doc = document(result)
    evidence = next(r for r in doc['evidence'].values() if r.get('kind') == 'healthy_species' and r.get('species') == 'a')
    assert evidence['status'] == 'not_detected' and evidence['comparison'] == 'below'
    assert any(r['evidence_id'] == next(k for k, v in doc['evidence'].items() if v is evidence) for r in select_findings(doc))
    assert '未检出' in evidence['reference_text']


def test_exact_target_minor_and_reference_pipeline_validation(cohort):
    base, profiles, data = cohort
    p = profiles/'TARGET/provenance.json'
    value = json.loads(p.read_text())
    value['pipeline']['profiler_version'] = '3.0.15'
    p.write_text(json.dumps(value))
    assert refresh(data)['healthy_comparison']['audit']['reason'] == 'incompatible_pipeline'
    rewrite_manifest(base, pipeline={**cmd.PIPELINE, 'profiler_version': '3.0.14'})
    assert refresh(data)['healthy_comparison']['audit']['reason'] == 'invalid_reference'


def test_provider_spec_is_immutable_and_extensible_without_implementing_cmd4():
    with pytest.raises(FrozenInstanceError):
        cmd.SPEC.version = 'changed'
    with pytest.raises(TypeError):
        cmd.SPEC.pipeline['profiler_version'] = '4'
    future = replace(cmd.SPEC, version='future-cmd4-schema', pipeline={'profiler': 'MetaPhlAn', 'profiler_version': '4'})
    assert future.pipeline['profiler_version'] == '4' and cmd.SPEC.pipeline['profiler_version'] == '3'
    with pytest.raises(ValueError):
        replace(cmd.SPEC, minimum_subjects=29)


def test_builder_cli_parameters_are_forwarded(monkeypatch):
    path = Path(__file__).parents[1]/'scripts/prepare_cmd_reference.py'
    spec = importlib.util.spec_from_file_location('cmd_builder_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module, 'build', lambda *args, **kwargs: calls.append(kwargs) or {})
    monkeypatch.setattr('sys.argv', [str(path), '--package-dir', 'pkg', '--metadata', 'meta', '--catalog', 'catalog',
        '--source-dir', 'source', '--output', 'output', '--stratify-by', 'country', 'sex', 'age_band',
        '--age-band-boundaries', '18', '30', '60'])
    module.main()
    assert calls == [{'stratify_by': ['country', 'sex', 'age_band'], 'age_band_boundaries': [18., 30., 60.],
                      'antibiotics_policy': 'no'}]


def test_stratum_and_depth_manifest_summary_round_trip(cohort):
    base, _, _ = cohort
    manifest, labels, *_ = cmd.load_bundle(base)
    changes = {'stratify_by': ['country', 'age_band'], 'age_band_boundaries': [18, 30, 60],
               'stratum_subject_counts': population.stratum_counts(labels, ['country', 'age_band'], [18, 30, 60]),
               'depth_distribution': population.depth_distribution(labels)}
    rewrite_manifest(base, **changes)
    assert cmd.load_bundle(base)[0]['depth_distribution']['number_reads']['n_reference'] == 35
    rewrite_manifest(base, stratum_subject_counts={'wrong': 99})
    with pytest.raises(ValueError):
        cmd.load_bundle(base)


def test_target_depth_is_recorded_without_reference_depth_and_legacy_header_is_used(cohort):
    base, profiles, data = cohort
    rewrite_labels(base, lambda i, row: (row.pop('number_reads'), row.pop('number_bases')))
    audit = refresh(data)['healthy_comparison']['audit']
    assert audit['sequencing_depth']['reference'] == {}
    assert audit['sequencing_depth']['target']['number_reads'] == 1_000_000
    folder = profiles/'TARGET'
    raw = b'#123456 reads processed\n' + (folder/'profile.tsv').read_bytes()
    (folder/'profile.tsv').write_bytes(raw)
    provenance = json.loads((folder/'provenance.json').read_text())
    provenance.pop('number_reads')
    provenance.pop('number_bases')
    provenance['profile_sha256'] = cmd.digest(raw)
    (folder/'provenance.json').write_text(json.dumps(provenance))
    assert refresh(data)['healthy_comparison']['audit']['sequencing_depth']['target']['number_reads'] == 123456


@pytest.mark.asyncio
async def test_comparison_tool_uses_only_cmd_and_retains_uncertainty(cohort, tmp_path, monkeypatch):
    from wgs_agent.tools.domain_tools import CompareReferenceTool, JSON_KEY
    root = tmp_path/'tool-results'
    root.mkdir()
    (root/'TARGET_analysis.json').write_text(json.dumps({'sample_id': 'TARGET',
        'metadata': {'subject_id': 'P0', 'study_id': 'STUDY'}}))
    monkeypatch.setenv('WGS_RESULTS_DIR', str(root))
    result = await CompareReferenceTool().invoke({'sample_id': 'TARGET'})
    assert not result.is_error
    payload = json.loads(result.content.split(JSON_KEY)[1])
    assert payload['reference']['provider'] == 'cmd' and payload['reference']['n_subjects'] == 34
    assert 'p5_ci95' in payload['comparison'][0]
    assert payload['outlier_baseline']['target_percentile'] >= 0
    assert payload['n_abnormal'] == sum(population.abnormal(r) for r in payload['comparison'])


@pytest.mark.asyncio
async def test_comparison_tool_unavailable_is_not_zero_abnormal(cohort, tmp_path, monkeypatch):
    from wgs_agent.tools.domain_tools import CompareReferenceTool, JSON_KEY
    monkeypatch.setenv('WGS_RESULTS_DIR', str(tmp_path/'tool-results'))
    monkeypatch.setenv('WGS_CMD_REFERENCE_DIR', str(tmp_path/'missing'))
    result = await CompareReferenceTool().invoke({'sample_id': 'TARGET'})
    assert not result.is_error and '未建立健康对照' in result.content
    payload = json.loads(result.content.split(JSON_KEY)[1])
    assert payload['n_abnormal'] is None and not payload['comparison']


@pytest.mark.asyncio
async def test_comparison_tool_validates_sample_id_before_reading_metadata(cohort, monkeypatch):
    from wgs_agent.pipeline import cmd_workflow
    from wgs_agent.tools.domain_tools import CompareReferenceTool, JSON_KEY
    def forbidden(*args):
        raise AssertionError('metadata must not be read for an invalid sample ID')
    monkeypatch.setattr(cmd_workflow, '_metadata', forbidden)
    result = await CompareReferenceTool().invoke({'sample_id': '../invalid'})
    assert not result.is_error
    assert json.loads(result.content.split(JSON_KEY)[1])['reference']['reason'] == 'invalid_target'
