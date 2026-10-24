"""Bind the reviewed read-only GraphRAG skill through the running workspace API."""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from wgs_agent.tools.litkg_graphrag import GRAPHRAG_SKILL_INSTRUCTIONS


def enable(base_url: str, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir,0o700)
    with httpx.Client(base_url=base_url, timeout=15) as client:
        def get(path):
            response=client.get(path)
            response.raise_for_status()
            return response.json()
        tools=get('/tools')
        if 'litkg_graph_rag' not in {row['name'] for row in tools}:
            raise SystemExit('New GraphRAG tool is not loaded. Restart the production API first.')
        skills=get('/skills')
        agents=get('/agents?include_subagents=true')
        backup=backup_dir/f'catalog-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.json'
        backup.write_text(json.dumps({'agents':agents,'skills':skills},ensure_ascii=False,indent=2))
        os.chmod(backup,0o600)
        skill={'id':'litkg-graphrag','name':'LitKG 图谱检索','description':'只读检索原生实体、关系路径与原文事实。',
            'category':'知识检索','tool_names':['litkg_graph_rag'],'risk_level':'read','enabled':True,
            'instructions':GRAPHRAG_SKILL_INSTRUCTIONS}
        response=client.put('/skills/litkg-graphrag',json=skill) if any(row['id']==skill['id'] for row in skills) else client.post('/skills',json=skill)
        response.raise_for_status()
        for agent in agents:
            if agent['id'] not in {'fmt-researcher','evidence-curator'}:
                continue
            agent['skill_ids']=list(dict.fromkeys([*agent.get('skill_ids',[]),skill['id']]))
            response=client.put('/agents/'+agent['id'],json=agent)
            response.raise_for_status()
            assert skill['id'] in response.json()['skill_ids']
        print('GraphRAG read-only skill bound to primary and evidence subagent. Backup:',backup)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--api-base-url',default='http://127.0.0.1:8503/api')
    parser.add_argument('--backup-dir',type=Path,default=Path(__file__).resolve().parents[1]/'tmp/graphrag-20261024/catalog-backup')
    args=parser.parse_args()
    enable(args.api_base_url,args.backup_dir)
