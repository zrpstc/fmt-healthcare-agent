"""Refresh only chapter 5 of saved reports, without model calls or other sections."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile


def refresh(report_path, root, *, pdf=True):
    from wgs_agent.pipeline.resistome_mge import load_chapter5_inputs, lock
    from wgs_agent.reporting.document import build_document
    from wgs_agent.reporting.chapter_five import render_chapter
    report_path=Path(report_path).resolve()
    original=report_path.read_bytes()
    document=json.loads(original)
    sid=document['sample_id']
    modules=load_chapter5_inputs(sid,root,include_missing=False)
    if len(modules)!=2 or any(x.get('status')!='completed' for x in modules.values()):
        raise ValueError('CHAPTER5_NOT_COMPLETED')
    output=report_path.parent
    paths={'report':report_path,'markdown':output/(sid+'_health_report.md'),'evidence':output/(sid+'_report_evidence.json')}
    if pdf:paths['pdf']=output/(sid+'_health_report.pdf')
    with lock(output/('.'+sid+'.report.lock')):
        originals={key:path.read_bytes() if path.exists() else None for key,path in paths.items()}
        if originals['report']!=original:raise RuntimeError('CONCURRENT_REPORT_UPDATE')
        old_sections=copy.deepcopy([s for s in document['sections'] if s['id']!='resistance'])
        fresh=build_document(sid,{},{},{},{},{},{},{},{},context={'health_inputs':modules})
        new_section=next(s for s in fresh['sections'] if s['id']=='resistance')
        old_section=next(s for s in document['sections'] if s['id']=='resistance')
        old_ids={key for t in old_section['topics'] for key in t.get('evidence_ids',[])}
        evidence={key:row for key,row in document['evidence'].items() if key not in old_ids}
        fresh_evidence={key:row for key,row in fresh['evidence'].items() if row.get('gene')}
        for key,row in fresh_evidence.items():
            if key in evidence:raise ValueError('EVIDENCE_ID_COLLISION')
            evidence[key]=row
        document['evidence']=evidence
        document['sections']=[new_section if s['id']=='resistance' else s for s in document['sections']]
        document.setdefault('template_inputs',{}).update(modules)
        document.setdefault('audit',{})['chapter5_refresh']={'updated_at':datetime.now(timezone.utc).isoformat(),'scope':'chapter5_only','model_calls':False}
        if old_sections!=[s for s in document['sections'] if s['id']!='resistance']:
            raise RuntimeError('OTHER_SECTION_CHANGED')
        markdown=(originals['markdown'] or b'').decode('utf-8')
        pattern=re.compile(r'^##\s+5[ .、].*?$(?:\n|$).*?(?=^##\s+6[ .、]|\Z)',re.M|re.S)
        matches=list(pattern.finditer(markdown))
        if len(matches)!=1:raise ValueError('CHAPTER5_MARKDOWN_BOUNDARY_MISSING')
        chapter='\n\n'.join(render_chapter(document))+'\n\n'
        match=matches[0]
        markdown=markdown[:match.start()]+chapter+markdown[match.end():]
        values={'report':json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8'),'markdown':markdown.encode('utf-8')}
        if originals['evidence'] is not None:
            manifest=json.loads(originals['evidence']);manifest['evidence']=evidence
            # Retain unrelated topic maps and replace only resistance topic IDs.
            topic_ids={t['id']:t.get('evidence_ids',[]) for t in new_section['topics']}
            for key,value in manifest.items():
                if isinstance(value,dict) and any(str(k).startswith('resistance.') for k in value):
                    for tid,ids in topic_ids.items():value[tid]=ids
            values['evidence']=json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        backup=output/('.chapter5-backup-'+sid+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(mode=0o700)
        for key,data in originals.items():
            if data is not None:
                f=backup/paths[key].name;f.write_bytes(data);os.chmod(f,0o600)
        staged={}
        try:
            for key,value in values.items():
                with tempfile.NamedTemporaryFile(mode='wb',prefix='.chapter5-',suffix=paths[key].suffix,dir=output,delete=False) as f:
                    f.write(value);staged[key]=Path(f.name)
                os.chmod(staged[key],0o600)
            if pdf:
                from wgs_agent.tools.report_maker import _generate_fpdf_report
                with tempfile.NamedTemporaryFile(prefix='.chapter5-',suffix='.pdf',dir=output,delete=False) as f:staged['pdf']=Path(f.name)
                _generate_fpdf_report(markdown,sid,str(staged['pdf']))
                os.chmod(staged['pdf'],0o600)
            for key,path in paths.items():
                current=path.read_bytes() if path.exists() else None
                if current!=originals[key]:raise RuntimeError('CONCURRENT_REPORT_UPDATE')
            for key,temp in staged.items():os.replace(temp,paths[key])
        finally:
            for temp in staged.values():temp.unlink(missing_ok=True)
    return {'sample_id':sid,'updated':[str(paths[k]) for k in staged], 'backup':str(backup), 'other_sections_unchanged':True,'summary':{k:v.get('summary',{}) for k,v in modules.items()}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report-path',type=Path,required=True)
    p.add_argument('--output-root',type=Path,required=True)
    p.add_argument('--no-pdf',action='store_true')
    args=p.parse_args()
    from wgs_fmt_platform.paths import PROJECT_ROOT
    if not args.report_path.resolve().is_relative_to(PROJECT_ROOT):raise ValueError('REPORT_OUTSIDE_PROJECT')
    print(json.dumps(refresh(args.report_path,args.output_root,pdf=not args.no_pdf)))


if __name__=='__main__':main()
