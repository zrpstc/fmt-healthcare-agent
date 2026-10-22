from fastapi import Response
from app import main


def test_reports_and_downloads_are_not_cached(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'RESULTS_DIR',tmp_path)
    (tmp_path/'TEST_health_report.md').write_text('报告版本：evidence-report-v2')
    response=Response()
    assert main.reports(response)['count']==1
    assert response.headers['cache-control'].startswith('no-store')
    artifact=main.report_file('TEST','markdown')
    assert artifact.headers['cache-control'].startswith('no-store')


def test_figure_response_is_not_cached(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'RESULTS_DIR',tmp_path)
    (tmp_path/'figures').mkdir()
    (tmp_path/'figures'/'TEST_species.png').write_bytes(b'test')
    assert main.report_figure('TEST','TEST_species.png').headers['cache-control'].startswith('no-store')


def test_three_layer_report_artifacts_are_listed_and_downloadable(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'RESULTS_DIR', tmp_path)
    (tmp_path / 'TEST_health_report.md').write_text('# main')
    (tmp_path / 'TEST_technical_appendix.md').write_text('# technical')
    (tmp_path / 'TEST_interactive_report.json').write_text('{"schema_version":"v1"}')
    artifacts = main._sample_artifacts('TEST')
    assert artifacts['technical']['exists']
    assert artifacts['interactive']['exists']
    assert main.report_file('TEST', 'technical').media_type.startswith('text/markdown')
    assert main.report_file('TEST', 'interactive').media_type == 'application/json'
