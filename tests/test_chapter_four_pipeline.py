import bz2
import gzip
import json
import pickle
from pathlib import Path
import unittest
import tempfile
from wgs_agent.pipeline.strain_virulence import AnalysisError, artifact_path, atomic_json, envelope, fasta_catalog, fingerprint_fastq, load_chapter4_inputs, merge_chapter4_inputs, summarize_consensus, summarize_vf_sam
from wgs_agent.reporting.chapter_four import refresh_analysis_modules, status_message

def fastq(path, sequence='ACGT'):
    path.write_text('@read\n' + sequence + '\n+\n' + 'I' * len(sequence) + '\n')
    return path

def sam(path, lines, length=10):
    path.write_text('@HD\tVN:1.6\n@SQ\tSN:vf_1\tLN:' + str(length) + '\n' + '\n'.join(lines) + '\n')
    return path

def aln(name='q1', *, flag=0, pos=1, mapq=40, cigar='10M', seq='ACGTACGTAC', nm=0):
    return f"{name}\t{flag}\tvf_1\t{pos}\t{mapq}\t{cigar}\t*\t0\t0\t{seq}\t{'I' * len(seq)}\tNM:i:{nm}"
CATALOG = {'vf_1': {'gene': 'SYNTHETIC_VF', 'aliases': ['SYNTHETIC_VF'], 'length': 10}}

class ChapterFourPipelineTests(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tmp_path = Path(self.temporary.name)

    def test_real_fastq_validation_rejects_truncation_and_empty_input(self):
        tmp_path = self.tmp_path
        good = fastq(tmp_path / 'ok.fastq')
        assert fingerprint_fastq(good)['reads'] == 1
        gzip_path = tmp_path / 'ok.fastq.gz'
        with gzip.open(gzip_path, 'wb') as handle:
            handle.write(good.read_bytes())
        assert fingerprint_fastq(gzip_path) == fingerprint_fastq(good)
        good.write_text('@read\nACGT\n+\nII\n')
        with self.assertRaisesRegex(AnalysisError, 'INVALID_FASTQ'):
            fingerprint_fastq(good)
        good.write_text('')
        with self.assertRaisesRegex(AnalysisError, 'EMPTY_FASTQ'):
            fingerprint_fastq(good)

    def test_reference_aliases_are_collapsed_not_counted_as_separate_genes(self):
        tmp_path = self.tmp_path
        path = tmp_path / 'refs.fna'
        path.write_text('>VFG000001 first\nACGTACGTAC\n>VFG000002 second\nACGTACGTAC\n')
        catalog = fasta_catalog(path)
        assert len(catalog) == 1
        assert catalog['vf_1']['aliases'] == ['VFG000001', 'VFG000002']

    def test_screening_counts_unique_primary_reads_and_excludes_ambiguous_and_secondary(self):
        tmp_path = self.tmp_path
        path = sam(tmp_path / 'test.sam', [aln('a'), aln('b'), aln('c'), aln('secondary', flag=256), aln('ambiguous', mapq=0)])
        result = summarize_vf_sam(path, CATALOG, expected_reads=4)
        assert result['markers'][0]['read_count'] == 3
        assert result['markers'][0]['breadth'] == 100
        assert result['markers'][0]['sequence_link_supported'] is False
        assert result['summary']['rejected_mappings'] == 1

    def test_deletions_never_inflate_gene_breadth(self):
        tmp_path = self.tmp_path
        path = sam(tmp_path / 'test.sam', [aln(cigar='4M2D4M', seq='ACGTACGT', nm=2)])
        result = summarize_vf_sam(path, CATALOG, min_reads=1, min_breadth=90, min_identity=70)
        assert result['markers'] == []
        assert result['candidates'][0]['breadth'] == 80

    def test_truncated_sam_is_failure_not_a_negative_result(self):
        tmp_path = self.tmp_path
        path = sam(tmp_path / 'test.sam', [aln()])
        with self.assertRaisesRegex(AnalysisError, 'SAM_READ_COUNT_MISMATCH'):
            summarize_vf_sam(path, CATALOG, expected_reads=3)

    def test_unknown_reference_is_rejected(self):
        tmp_path = self.tmp_path
        path = sam(tmp_path / 'test.sam', [aln()])
        path.write_text(path.read_text().replace('SN:vf_1', 'SN:unknown'))
        with self.assertRaisesRegex(AnalysisError, 'SAM_REFERENCE_MISMATCH'):
            summarize_vf_sam(path, CATALOG)

    def test_no_hit_is_recorded_only_after_complete_input_processing(self):
        tmp_path = self.tmp_path
        unmapped = 'q\t4\t*\t0\t0\t*\t*\t0\t0\tACGT\tIIII'
        result = summarize_vf_sam(sam(tmp_path / 'test.sam', [unmapped]), CATALOG, expected_reads=1)
        assert result['markers'] == []
        assert result['summary']['processed_reads'] == 1

    def test_loader_rejects_cross_sample_result_and_outside_root_symlinks(self):
        tmp_path = self.tmp_path
        path = artifact_path(tmp_path, 'virulence', 'sample')
        atomic_json(path, envelope('virulence', 'other', 'completed', markers=[{'gene': 'wrong'}]))
        assert load_chapter4_inputs('sample', tmp_path)['virulence']['status'] == 'invalid_result'
        outside = tmp_path.parent / (tmp_path.name + '-outside.json')
        atomic_json(outside, envelope('virulence', 'sample', 'completed'))
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest('Host does not permit creating test symlinks')
        assert load_chapter4_inputs('sample', tmp_path)['virulence']['status'] == 'invalid_result'

    def test_failed_rerun_does_not_reuse_old_positive_or_secret_fields(self):
        tmp_path = self.tmp_path
        value = envelope('virulence', 'sample', 'failed', 'TOOL_EXIT_NONZERO', markers=[{'gene': 'old'}])
        value['password'] = 'synthetic-auth-value'
        atomic_json(artifact_path(tmp_path, 'virulence', 'sample'), value)
        current = load_chapter4_inputs('sample', tmp_path)
        assert current['virulence']['markers'] == []
        assert 'password' not in current['virulence']
        assert merge_chapter4_inputs(current, {'virulence': {'markers': [{'gene': 'old'}]}})['virulence']['status'] == 'failed'

    def test_legacy_explicit_optional_results_remain_supported(self):
        previous = {'virulence': {'markers': [{'gene': 'SYNTHETIC_LEGACY'}]}}
        current = {'virulence': envelope('virulence', 'sample')}
        assert merge_chapter4_inputs(current, previous)['virulence'] == previous['virulence']

    def test_existing_analysis_is_refreshed_without_changing_other_modules(self):
        tmp_path = self.tmp_path
        root = tmp_path / 'bio'
        path = tmp_path / 'sample_analysis.json'
        original = {'sample_id': 'sample', 'species': {'data': [1]}, 'custom': {'keep': True}}
        atomic_json(path, original)
        artifact = envelope('virulence', 'sample', 'completed', 'COMPLETED', markers=[{'gene': 'SYNTHETIC_NEW'}])
        atomic_json(artifact_path(root, 'virulence', 'sample'), artifact)
        refresh_analysis_modules(path, 'sample', root)
        actual = json.loads(path.read_text())
        assert actual['custom'] == original['custom'] and actual['species'] == original['species']
        assert actual['virulence']['markers'][0]['gene'] == 'SYNTHETIC_NEW'

    def test_consensus_support_is_not_fabricated_as_named_strain(self):
        tmp_path = self.tmp_path
        db = tmp_path / 'markers.pkl'
        metadata = {'markers': {'m1': {'clade': 't__SGB1'}, 'm2': {'clade': 't__SGB1'}}, 'taxonomy': {'k__Bacteria|s__Example_species|t__SGB1': (1, 1)}}
        with bz2.open(db, 'wb') as handle:
            pickle.dump(metadata, handle)
        path = tmp_path / 'consensus.json.bz2'
        with bz2.open(path, 'wt') as handle:
            json.dump({'database_name': 'markers', 'consensus_markers': [{'name': 'm1', 'sequence': 'ACGT*--N'}, {'name': 'm2', 'sequence': 'AACCTT'}]}, handle)
        result = summarize_consensus(path, db, min_markers=2)
        assert result['strains'][0]['species'] == 'Example species'
        assert result['strains'][0]['callable_bases'] == 10
        assert result['summary']['reference_comparison_performed'] is False
        assert '未进行参考菌株命名' in result['strains'][0]['result']
        assert summarize_consensus(path, db, min_markers=3)['strains'] == []

    def test_report_distinguishes_unavailable_failed_and_completed_no_hit(self):
        assert '未执行' in status_message(envelope('virulence', 'sample'), 'virulence')
        assert '数据库' in status_message(envelope('virulence', 'sample', 'missing_database'), 'virulence')
        assert '运行失败' in status_message(envelope('virulence', 'sample', 'failed'), 'virulence')
        nohit = status_message(envelope('virulence', 'sample', 'completed'), 'virulence')
        assert '已完成' in nohit and '预设' in nohit

    def test_complete_report_consumes_fresh_modules_and_preserves_host_evidence_boundary(self):
        from wgs_agent.reporting.document import build_document, render_markdown
        modules = {'virulence': envelope('virulence', 'sample', 'completed', markers=[{'gene': 'SYNTHETIC_REAL_RESULT', 'detected': True, 'host': 'UNPROVEN_HOST'}]), 'strains': envelope('strains', 'sample', 'completed', strains=[{'species': 'SYNTHETIC_SPECIES', 'analysis_level': 'marker', 'result': 'consensus', 'confidence': 'supported'}])}
        doc = build_document(sample_id='sample', species={}, compare={}, enterotype={}, pathways={}, metabolites={}, drugs={}, diseases={}, knowledge={}, context={'health_inputs': modules})
        markdown = render_markdown(doc)
        assert 'SYNTHETIC_REAL_RESULT' in markdown and 'SYNTHETIC_SPECIES' in markdown
        assert 'UNPROVEN_HOST' not in markdown

    def test_successful_screening_is_reused_but_changed_inputs_force_recalculation(self):
        from unittest.mock import patch
        from wgs_agent.pipeline.strain_virulence import run_module
        root = self.tmp_path / 'outputs'
        tools = self.tmp_path / 'tools'
        tools.mkdir()
        for name in ['bowtie2', 'bowtie2-build']:
            executable = tools / name
            executable.write_text('synthetic tool placeholder')
            executable.chmod(493)
        reads = self.tmp_path / 'reads.fastq'
        reads.write_text(''.join(('@r' + str(i) + '\nACGTACGTAC\n+\nIIIIIIIIII\n' for i in range(3))))
        reference = self.tmp_path / 'core.fna'
        reference.write_text('>VFG000001\nACGTACGTAC\n')
        settings = {'root': root, 'sid': 'sample', 'reads': reads, 'db_root': self.tmp_path, 'env_bin': tools, 'threads': 1}

        def tool_output(command, log_dir, label, env, **kwargs):
            if label == 'vfdb-map':
                sam(Path(command[-1]), [aln('r' + str(i)) for i in range(3)])
        with patch('wgs_agent.pipeline.strain_virulence.execute', side_effect=tool_output) as execute:
            first = run_module('virulence', settings, vfdb=reference)
            assert first['status'] == 'completed' and len(first['markers']) == 1
            assert execute.call_count == 2
            second = run_module('virulence', settings, vfdb=reference)
            assert second['input_fingerprint'] == first['input_fingerprint']
            assert execute.call_count == 2
            reads.write_text(reads.read_text().replace('@r0', '@changed'))
            third = run_module('virulence', settings, vfdb=reference)
            assert third['status'] == 'completed'
            assert third['input_fingerprint'] != first['input_fingerprint']
            assert execute.call_count == 4
            reference.write_text('>VFG000001\nTGCATGCATG\n')
            fourth = run_module('virulence', settings, vfdb=reference)
            assert fourth['input_fingerprint'] != third['input_fingerprint']
            assert execute.call_count == 6
        with patch('wgs_agent.pipeline.strain_virulence.execute', side_effect=AnalysisError('failed', 'TOOL_EXIT_NONZERO')):
            failed = run_module('virulence', settings, vfdb=reference, force=True)
        assert failed['status'] == 'failed' and failed['markers'] == []
        assert load_chapter4_inputs('sample', root)['virulence']['markers'] == []

    def test_concurrent_job_does_not_overwrite_running_result(self):
        from wgs_agent.pipeline.strain_virulence import lock_file, run_module
        root = self.tmp_path / 'output'
        path = artifact_path(root, 'virulence', 'sample')
        original = envelope('virulence', 'sample', 'running', 'RUNNING')
        atomic_json(path, original)
        settings = {'root': root, 'sid': 'sample'}
        with lock_file(root / 'chapter4/sample/virulence/.lock'):
            result = run_module('virulence', settings)
        assert result['status'] == 'running'
        assert json.loads(path.read_text()) == original

    def test_consensus_from_another_database_is_rejected(self):
        path = self.tmp_path / 'consensus.json.bz2'
        with bz2.open(path, 'wt') as handle:
            json.dump({'database_name': 'wrong', 'consensus_markers': []}, handle)
        with self.assertRaisesRegex(AnalysisError, 'CONSENSUS_DATABASE_MISMATCH'):
            summarize_consensus(path, self.tmp_path / 'intended.pkl')

    def test_numeric_configuration_fields_cannot_enter_result_summaries(self):
        artifact = envelope('virulence', 'sample', 'completed', summary={'processed_reads': 7, 'password': 123456})
        atomic_json(artifact_path(self.tmp_path, 'virulence', 'sample'), artifact)
        loaded = load_chapter4_inputs('sample', self.tmp_path)['virulence']
        assert loaded['summary'] == {'processed_reads': 7}

    def test_invalid_thresholds_produce_failed_state_not_negative(self):
        from wgs_agent.pipeline.strain_virulence import run_module
        root = self.tmp_path / 'output'
        reads = fastq(self.tmp_path / 'reads.fastq')
        reference = self.tmp_path / 'core.fna'
        reference.write_text('>VFG000001\nACGT\n')
        result = run_module('virulence', {'root': root, 'sid': 'sample', 'reads': reads, 'db_root': self.tmp_path, 'env_bin': self.tmp_path, 'threads': 1}, vfdb=reference, min_breadth=float('nan'))
        assert result['status'] == 'failed' and result['markers'] == []

    def test_unicode_fasta_descriptions_do_not_corrupt_nucleotide_parsing(self):
        path = self.tmp_path / 'references.fna.gz'
        with gzip.open(path, 'wb') as handle:
            handle.write('>VFG000001 official β description\nACGTACGTAC\n'.encode('utf-8'))
        result = fasta_catalog(path)
        assert result['vf_1']['length'] == 10
        assert result['vf_1']['gene'] == 'VFG000001'
        with gzip.open(path, 'wb') as handle:
            handle.write('>VFG000001\nACGTβ\n'.encode('utf-8'))
        with self.assertRaisesRegex(AnalysisError, 'VFDB_NOT_READABLE'):
            fasta_catalog(path)
if __name__ == '__main__':
    unittest.main()
