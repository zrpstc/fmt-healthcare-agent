import json
from pathlib import Path
import pytest

from wgs_agent.pipeline.non_bacterial import (read_marker_profile, read_vsc,
    load_chapter6_inputs, main, classify)
from wgs_agent.reporting.chapter_six import render_other_microbes

HEADER = '#mpa_test\n#clade_name\tNCBI_tax_id\trelative_abundance\n'
VSC_HEADER = 'M-Group/Cluster\tgenomeName\tlen\tbreadth_of_coverage\tdepth_of_coverage_mean\tdepth_of_coverage_median\tM-Group-Type [k|u]\tFirst Genome in Cluster\n'


def profile(tmp_path, rows):
    path = tmp_path / 'profile.tsv'
    path.write_text(HEADER + rows)
    return path


def test_marker_lineage_and_original_denominator(tmp_path):
    path = profile(tmp_path,
        'k__Bacteria|s__Example_bacterium\t2|3\t96\n'
        'k__Archaea|p__Euryarchaeota|s__Methanobrevibacter_smithii\t2157|4|5\t2\n'
        'k__Eukaryota|p__Ascomycota|s__Candida_albicans\t2759|6|7\t1\n'
        'k__Eukaryota|p__Apicomplexa|s__Example_protist\t2759|8|9\t1\n')
    result = read_marker_profile(path)
    assert result['archaea']['records'][0]['abundance'] == 2
    assert result['fungi']['records'][0]['abundance'] == 1
    assert len(result['fungi']['records']) == 1
    assert classify('k__Eukaryota|s__Unknown_eukaryote') is None


def test_absent_assay_is_not_negative(tmp_path):
    assert read_marker_profile(tmp_path / 'absent')['archaea']['status'] == 'not_analyzed'
    path = profile(tmp_path, 'k__Bacteria|s__Example_bacterium\t2|3\t100\n')
    result = read_marker_profile(path)
    assert result['archaea']['status'] == 'not_detected'
    assert result['archaea']['detected_species'] == 0
    assert result['archaea']['records'] == []


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', '101'])
def test_invalid_profile_cannot_become_negative(tmp_path, value):
    path = profile(tmp_path, f'k__Archaea|s__Example\t2|3\t{value}\n')
    assert read_marker_profile(path)['archaea']['status'] == 'invalid_input'


def test_duplicate_species_is_invalid(tmp_path):
    path = profile(tmp_path, 'k__Archaea|s__Example\t2|3\t1\n' * 2)
    assert read_marker_profile(path)['archaea']['records'] == []


def test_vsc_requires_completed_assay_and_does_not_invent_dna_or_hosts(tmp_path):
    path = tmp_path / 'vsc.tsv'
    path.write_text(VSC_HEADER + 'M1\tVDB1\t1000\t0.9\t2\t1\tkVSG\tExample_phage\n')
    assert read_vsc(path)['status'] == 'not_analyzed'
    result = read_vsc(path, completed=True)
    assert result['status'] == 'detected'
    row = result['records'][0]
    assert row['breadth_of_coverage'] == .9
    assert row['dna_confirmed'] is False
    assert 'abundance' not in row and 'host' not in row
    assert result['genome_type_unresolved_clusters'] == 1


def test_header_only_and_invalid_vsc_are_distinct(tmp_path):
    path = tmp_path / 'vsc.tsv'
    path.write_text(VSC_HEADER)
    assert read_vsc(path, completed=True)['status'] == 'not_detected'
    path.write_text('')
    assert read_vsc(path, completed=True)['status'] == 'invalid_input'
    path.write_text(VSC_HEADER + 'M1\tVDB1\t1000\t1.5\t2\t1\tuVSG\t-\n')
    assert read_vsc(path, completed=True)['status'] == 'invalid_input'


def test_viral_dna_annotation_and_threshold(tmp_path):
    path = tmp_path / 'vsc.tsv'
    path.write_text(VSC_HEADER.rstrip('\n') + '\tgenome_type\n' +
        'M1\tVDB1\t1000\t0.9\t2\t1\tkVSG\tReference\tdsDNA\n' +
        'M2\tVDB2\t1000\t0.9\t2\t1\tkVSG\tReference\tssRNA\n' +
        'M3\tVDB3\t1000\t0.5\t2\t1\tuVSG\t-\tDNA\n')
    result = read_vsc(path, completed=True)
    assert result['detected_clusters'] == 1
    assert result['dna_confirmed_clusters'] == 1


def test_completion_marker_is_bound_to_sample_and_content(tmp_path):
    directory = tmp_path / 'profiles/viruses'
    directory.mkdir(parents=True)
    path = directory / 'sample_vsc.tsv'
    path.write_text(VSC_HEADER)
    main(['--sample-id', 'sample', '--output-root', str(tmp_path), '--complete-vsc'])
    assert load_chapter6_inputs('sample', tmp_path)['dna_viruses']['status'] == 'not_detected'
    path.write_text(VSC_HEADER + 'M1\tVDB1\t1000\t0.9\t2\t1\tuVSG\t-\n')
    assert load_chapter6_inputs('sample', tmp_path)['dna_viruses']['status'] == 'not_analyzed'


def test_sample_and_symlink_escape_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_chapter6_inputs('../other', tmp_path)
    elsewhere = tmp_path.parent / (tmp_path.name + '_outside')
    elsewhere.mkdir()
    (tmp_path / 'profiles').symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError):
        load_chapter6_inputs('sample', tmp_path)


class Body:
    def __init__(self, inputs, qc_failed=False):
        self.inputs, self.qc_failed, self.out, self.tables = inputs, qc_failed, [], []
    def emit(self, headers, rows, note):
        self.tables.append((headers, rows))


def test_report_shows_completed_negative_and_qc_gate(tmp_path):
    result = read_marker_profile(profile(tmp_path, 'k__Bacteria|s__Example\t2|3\t100\n'))
    body = Body(result)
    assert render_other_microbes(body, 'unused', 'archaea')
    assert '未检出' in str(body.tables) and '0' in str(body.tables)
    body = Body(result, qc_failed=True)
    render_other_microbes(body, 'unused', 'archaea')
    assert '质控未通过' in str(body.tables)
    assert '未检出' not in str(body.tables)


def test_legacy_modules_are_preserved():
    assert not render_other_microbes(Body({'archaea': {'records': []}}), 'unused', 'archaea')


def test_full_report_receives_chapter_six_tables(tmp_path):
    from wgs_agent.reporting.document import build_document, render_markdown
    inputs = read_marker_profile(profile(tmp_path, 'k__Bacteria|s__Example\t2|3\t100\n'))
    vsc = tmp_path / 'vsc.tsv'
    vsc.write_text(VSC_HEADER + 'M1\tVDB1\t1000\t0.95\t2\t1\tuVSG\t-\n')
    inputs['dna_viruses'] = read_vsc(vsc, completed=True)
    doc = build_document('sample', {}, {}, {}, {}, {}, {}, {}, {}, context={'health_inputs': inputs})
    md = render_markdown(doc)
    assert '本参考库与阈值内未检出' in md
    assert '95.00%' in md and '平均覆盖深度' in md
    assert '不能据此确认为 DNA 病毒' in md


def test_fresh_evidence_precedes_stale_generated_inputs():
    from wgs_agent.pipeline.non_bacterial import merge_chapter6_inputs
    fresh = {'archaea': {'chapter_six_schema': 1, 'complete': True, 'records': []}}
    stale = {'archaea': {'chapter_six_schema': 1, 'complete': True, 'records': [{'name': 'old'}]}}
    assert merge_chapter6_inputs(fresh, stale) == fresh
    unavailable = {'archaea': {'chapter_six_schema': 1, 'complete': False}}
    supplied = {'archaea': {'records': [{'name': 'supplied'}]}}
    assert merge_chapter6_inputs(unavailable, supplied) == supplied
    assert merge_chapter6_inputs(unavailable, stale) == unavailable


def test_incomplete_vsc_cache_requires_recomputation(tmp_path, monkeypatch):
    from wgs_agent.pipeline.non_bacterial import ensure_viral_output
    directory = tmp_path / 'profiles/viruses'
    directory.mkdir(parents=True)
    (directory / 'sample_vsc.tsv').write_text(VSC_HEADER)
    # A plausible but unmarked result cannot bypass the missing FASTQ check.
    assert ensure_viral_output('sample', tmp_path, '/missing/metaphlan', '/db', 'index') is False
