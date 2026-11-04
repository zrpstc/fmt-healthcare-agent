from pathlib import Path
import json
import pytest
from wgs_agent.pipeline.resistome_mge import (summarize_sam, atomic_json, artifact_path, envelope, load_chapter5_inputs, merge_chapter5_inputs, run_module, sample_name)
from wgs_agent.reporting.chapter_five import render_resistance


def sam(tmp_path, rows, length=100):
    p=tmp_path/'map.sam'
    p.write_text(f'@SQ\tSN:ref1\tLN:{length}\n'+''.join(rows))
    return p, {'ref1':{'name':'tet-test','gene':'tet-test','length':length,'drug_class':'Tetracycline'}}


def read(pos=1, cigar='100M', size=100, mapq=42, flag=0, nm=0):
    return f'read\t{flag}\tref1\t{pos}\t{mapq}\t{cigar}\t*\t0\t0\t'+('A'*size)+'\t'+('I'*size)+f'\tNM:i:{nm}\n'


def test_union_breadth_depth_and_rpkm(tmp_path):
    p,cat=sam(tmp_path,[read(),read(),read()])
    rows,s=summarize_sam(p,cat,expected_reads=3)
    assert len(rows)==1 and rows[0]['breadth_coverage']==100
    assert rows[0]['coverage']==3 and rows[0]['identity']==100
    assert rows[0]['abundance']==10_000_000 and s['input_reads']==3
    assert rows[0]['host_linked'] is False and rows[0]['mobile_element_linked'] is False


def test_partial_breadth_does_not_pass_due_to_depth(tmp_path):
    p,c=sam(tmp_path,[read(cigar='40M',size=40) for _ in range(10)])
    rows,s=summarize_sam(p,c)
    assert rows==[] and s['candidate_count']==1


def test_deletion_not_counted_as_covered_bases(tmp_path):
    p,c=sam(tmp_path,[read(cigar='30M40D30M',size=60,nm=40)]*3)
    rows,s=summarize_sam(p,c,min_identity=50)
    assert rows==[] and s['candidate_count']==1


@pytest.mark.parametrize('mapq,flag,nm',[(0,0,0),(255,0,0),(42,0x400,0),(42,0,20)])
def test_low_quality_or_ambiguous_reads_cannot_call(tmp_path,mapq,flag,nm):
    p,c=sam(tmp_path,[read(mapq=mapq,flag=flag,nm=nm)]*3)
    assert summarize_sam(p,c)[0]==[]


def test_secondary_alignments_not_double_counted(tmp_path):
    p,c=sam(tmp_path,[read(),read(flag=256),read(),read()])
    rows,s=summarize_sam(p,c,expected_reads=3)
    assert rows[0]['mapped_reads']==3 and s['input_reads']==3


def test_incomplete_or_invalid_sam_is_failure(tmp_path):
    p,c=sam(tmp_path,[read()])
    with pytest.raises(ValueError):summarize_sam(p,c,expected_reads=2)
    p,c=sam(tmp_path,[read(pos=90)])
    with pytest.raises(ValueError):summarize_sam(p,c)


def test_loader_rejects_cross_sample_and_stale_failed_rows(tmp_path):
    p=artifact_path(tmp_path,'resistance','demo')
    atomic_json(p,envelope('resistance','other','completed',genes=[{'gene':'bad','detected':True}]))
    assert load_chapter5_inputs('demo',tmp_path)['resistance']['status']=='invalid_output'
    atomic_json(p,envelope('resistance','demo','failed',genes=[{'gene':'stale','detected':True}]))
    assert load_chapter5_inputs('demo',tmp_path)['resistance']['genes']==[]


def test_legacy_merge_fresh_status_and_unknown_fields(tmp_path):
    fresh=load_chapter5_inputs('demo',tmp_path)
    legacy={'resistance':{'genes':[{'gene':'legacy'}]}}
    assert merge_chapter5_inputs(fresh,legacy)['resistance']==legacy['resistance']
    fresh={'resistance':envelope('resistance','demo','failed')}
    assert merge_chapter5_inputs(fresh,legacy)['resistance']['status']=='failed'
    p=artifact_path(tmp_path,'resistance','demo')
    atomic_json(p,envelope('resistance','demo','completed',genes=[{'gene':'x','detected':True,'unapproved':'never'}]))
    assert 'unapproved' not in load_chapter5_inputs('demo',tmp_path)['resistance']['genes'][0]


def test_input_validation_and_missing_database_states(tmp_path):
    with pytest.raises(ValueError):sample_name('../other')
    v=run_module(tmp_path,'demo',tmp_path/'missing',tmp_path/'db',tmp_path/'bin','resistance')
    assert v['status']=='missing_input'
    (tmp_path/'reads.fastq').write_text('@r\nACGT\n+\nIIII\n')
    v=run_module(tmp_path,'demo',tmp_path/'reads.fastq',tmp_path/'db',tmp_path/'bin','resistance')
    assert v['status']=='missing_database'


class Body:
    def __init__(self,value):
        self.inputs={'resistance':value,'mobile_elements':value}
        self.qc_failed=False
        self.out=[]
        self.tables=[]
    def emit(self,headers,rows,missing='',**kwargs):
        self.tables.append((headers,rows))
        self.out.append(str(rows) if rows else missing)


def test_report_distinguishes_not_run_from_completed_negative():
    b=Body(envelope('resistance','demo'))
    assert render_resistance(b,1) and '尚未运行' in ''.join(b.out)
    assert '未检出达标' not in ''.join(b.out)
    b=Body(envelope('resistance','demo','completed',summary={'input_reads':10,'reference_count':20}))
    render_resistance(b,1)
    assert '未检出达标' in ''.join(b.out) and '20' in ''.join(b.out)


def test_qc_failure_and_legacy_fallback():
    b=Body(envelope('resistance','demo','completed'))
    b.qc_failed=True
    render_resistance(b,1)
    assert '质控未通过' in ''.join(b.out)
    assert render_resistance(Body({'genes':[]}),1) is False


def test_real_bowtie_positive_negative_and_cache(tmp_path):
    import random,hashlib
    tax=Path(__file__).resolve().parents[1]/'var/runtime/envs/fmt-tax/bin'
    if not (tax/'bowtie2').exists():
        pytest.skip('Bowtie2 not installed in this checkout')
    rng=random.Random(17)
    seq=''.join(rng.choices('ACGT',k=300))
    db=tmp_path/'db'/'resistance';db.mkdir(parents=True)
    fasta=db/'references.fna';fasta.write_text('>ref1\n'+seq+'\n')
    atomic_json(db/'catalog.json',{'ref1':{'name':'control-ARG','gene':'control-ARG','length':300}})
    manifest={'database':'synthetic_control','version':'1','scope':'test_only','sha256':hashlib.sha256(fasta.read_bytes()).hexdigest(),'catalog_sha256':hashlib.sha256((db/'catalog.json').read_bytes()).hexdigest()}
    atomic_json(db/'manifest.json',manifest)
    positive=tmp_path/'positive.fastq'
    reads=[seq[i:i+150] for i in (0,50,100,150) for _ in range(3)]
    positive.write_text(''.join(f'@r{i}\n{s}\n+\n'+('I'*len(s))+'\n' for i,s in enumerate(reads)))
    v=run_module(tmp_path,'positive',positive,tmp_path/'db',tax,'resistance',threads=1)
    assert v['status']=='completed' and len(v['genes'])==1
    assert v['genes'][0]['breadth_coverage']==100 and v['genes'][0]['mapped_reads']==12
    target=artifact_path(tmp_path,'resistance','positive');mtime=target.stat().st_mtime_ns
    assert run_module(tmp_path,'positive',positive,tmp_path/'db',tax,'resistance',threads=1)['status']=='completed'
    assert target.stat().st_mtime_ns==mtime
    negative=tmp_path/'negative.fastq';seqs=[''.join(rng.choices('ACGT',k=150)) for _ in range(5)]
    negative.write_text(''.join(f'@n{i}\n{s}\n+\n'+('I'*150)+'\n' for i,s in enumerate(seqs)))
    v=run_module(tmp_path,'negative',negative,tmp_path/'db',tax,'resistance',threads=1)
    assert v['status']=='completed' and v['genes']==[] and v['summary']['input_reads']==5
    (db/'catalog.json').write_text('{}')
    v=run_module(tmp_path,'positive',positive,tmp_path/'db',tax,'resistance',threads=1)
    assert v['status']=='failed' and v['genes']==[]


def test_actual_report_renderer_has_mge_table_and_correct_headers():
    from wgs_agent.reporting.document import build_document
    from wgs_agent.reporting.word_template import render_body
    rows=[{'name':'IS-control','detected':True,'element_type':'is','mapped_reads':3,'breadth_coverage':100.,'identity':100.,'abundance':7.0}]
    amr=envelope('resistance','demo','completed',summary={'input_reads':10,'reference_count':20})
    mge=envelope('mobile_elements','demo','completed',results=rows,summary={'input_reads':10,'reference_count':30})
    doc=build_document('demo',{},{},{},{},{},{},{},{},context={'health_inputs':{'resistance':amr,'mobile_elements':mge}})
    from wgs_agent.reporting.document import render_markdown
    markdown=render_markdown(doc)
    section=markdown.split('## 5 耐药组与可移动遗传元件')[1].split('## 6')[0]
    assert 'IS-control' in section and '元件类别' in section and '丰度 RPKM' in section
    assert '未检出达标获得性耐药基因' in section and '物理连锁未评估' in section
    assert '不能确定' not in section or '宿主' in section
