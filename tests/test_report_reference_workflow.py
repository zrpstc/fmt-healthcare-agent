"""cMD report publication, stale-result removal and rollback contracts."""
import copy
import hashlib
import json

import pytest

from wgs_agent.reporting import reference
from test_cmd_population import cohort, document, refresh


def test_old_tables_and_fmt_training_data_cannot_become_controls(cohort, tmp_path, monkeypatch):
    _, _, data = cohort
    old = tmp_path/'obsolete.csv'
    old.write_text('species,p5,p95\nJan25 species,0,1\n')
    monkeypatch.setenv('WGS_SPECIES_REFERENCE_FILE', str(old))
    monkeypatch.setenv('WGS_FMT_MATCHING_DIR', str(tmp_path/'fmt-training'))
    monkeypatch.setenv('WGS_CMD_REFERENCE_DIR', str(tmp_path/'missing'))
    data['species']['species_list'][0].update(p5=0, p95=1, status='high')
    result = refresh(data)
    assert result['healthy_comparison']['audit']['reason'] == 'reference_missing'
    assert result['healthy_comparison']['species'] == []
    assert result['species']['species_list'][0]['status'] == 'unknown'
    assert result['matching'] == data['matching']


def prepare_generator(monkeypatch):
    from wgs_agent.reporting import inputs, knowledge_graph
    from wgs_agent.tools import detailed_report
    monkeypatch.setattr(inputs, 'load_existing_report_inputs', lambda _: {})
    monkeypatch.setattr(detailed_report, 'resolve_report_model', lambda: None)
    monkeypatch.setattr(detailed_report, 'load_gene_family_evidence', lambda _: {})
    async def no_enrichment(_):
        return None
    monkeypatch.setattr(knowledge_graph, 'enrich_document', no_enrichment)


@pytest.mark.asyncio
async def test_regeneration_publishes_cmd_to_analysis_markdown_pdf_and_evidence(cohort, tmp_path, monkeypatch):
    from wgs_agent.tools.domain_tools import ReportGeneratorTool
    prepare_generator(monkeypatch)
    data = copy.deepcopy(cohort[2])
    path = tmp_path/'TARGET_analysis.json'
    path.write_text(json.dumps(data))
    params = {'sample_id': 'TARGET', 'analysis_json_path': str(path)}
    result = await ReportGeneratorTool().invoke(params)
    assert not result.is_error, result.content
    saved = json.loads(path.read_text())
    assert saved['healthy_comparison']['audit']['provider'] == 'cmd'
    assert saved['species'] == data['species']
    doc = json.loads((tmp_path/'TARGET_report.json').read_text())
    evidence = json.loads((tmp_path/'TARGET_report_evidence.json').read_text())
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert doc['audit']['analysis_sha256'] == evidence['context']['analysis_sha256'] == expected
    assert any(r.get('kind') == 'healthy_species' for r in doc['evidence'].values())
    text = (tmp_path/'TARGET_health_report.md').read_text()
    assert '多重比较基线' in text and 'P5的95%CI' in text and '研究间批次' in text
    assert (tmp_path/'TARGET_health_report.pdf').read_bytes().startswith(b'%PDF-')
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    assert not (await ReportGeneratorTool().invoke(params)).is_error
    assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['renderer', 'concurrent_analysis'])
async def test_failed_generation_preserves_previous_artifacts(cohort, tmp_path, monkeypatch, failure):
    from wgs_agent.tools import report_maker
    from wgs_agent.tools.domain_tools import ReportGeneratorTool
    prepare_generator(monkeypatch)
    path = tmp_path/'TARGET_analysis.json'
    path.write_text(json.dumps(cohort[2]))
    original = path.read_bytes()
    suffixes = ('health_report.md', 'health_report.pdf', 'report.json', 'report_evidence.json')
    for suffix in suffixes:
        (tmp_path/f'TARGET_{suffix}').write_text('previous')
    renderer = report_maker._generate_fpdf_report
    def fail_or_update(*args):
        if failure == 'renderer':
            raise RuntimeError('synthetic PDF failure')
        path.write_text('{"sample_id":"TARGET","concurrent":true}')
        renderer(*args)
    monkeypatch.setattr(report_maker, '_generate_fpdf_report', fail_or_update)
    response = await ReportGeneratorTool().invoke({'sample_id': 'TARGET', 'analysis_json_path': str(path)})
    assert response.is_error
    assert path.read_bytes() == original if failure == 'renderer' else json.loads(path.read_text())['concurrent']
    for suffix in suffixes:
        assert (tmp_path/f'TARGET_{suffix}').read_text() == 'previous'
