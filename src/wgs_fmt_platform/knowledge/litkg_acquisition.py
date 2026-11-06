"""Complete KB acquisition. Query relevance, review policy and output budgets live elsewhere."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import tempfile
import time
import weakref
from pathlib import Path
import httpx

class KnowledgeAcquisitionError(RuntimeError):
    pass

def snapshot_path(config):
    from wgs_fmt_platform.paths import workspace_root
    url = httpx.URL(config.base_url)
    # Do not persist an authenticated URL or a digest derived from credentials.
    identity = json.dumps([url.scheme, url.host, url.port, url.path, config.knowledge_base_id])
    key = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return workspace_root() / 'cache' / 'knowledge_snapshots' / f'kb-{config.knowledge_base_id}-{key}.json'

def snapshot_summary(snapshot):
    return {key: snapshot[key] for key in ('schema', 'knowledge_base_id', 'acquisition_scope',
            'complete', 'acquired_at', 'counts')}

def validate_snapshot(data, kb):
    if not isinstance(data, dict) or data.get('schema') != 'litkg-full-kb-v1' or data.get('knowledge_base_id') != kb or data.get('complete') is not True:
        raise KnowledgeAcquisitionError('Incomplete or foreign knowledge snapshot')
    for kind in ('entities', 'relations', 'claims', 'facts'):
        rows = data.get(kind)
        if not isinstance(rows, list) or any(not isinstance(r, dict) or r.get('id') is None for r in rows):
            raise KnowledgeAcquisitionError('Invalid knowledge snapshot collection')
        if len({str(r['id']) for r in rows}) != len(rows) or data.get('counts', {}).get(kind) != len(rows):
            raise KnowledgeAcquisitionError('Knowledge snapshot count mismatch')
    return data

async def _json(client, path, params=None):
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise KnowledgeAcquisitionError('Knowledge acquisition request failed') from exc
    if not isinstance(result, dict):
        raise KnowledgeAcquisitionError('Invalid knowledge acquisition response')
    return result

async def _pages(client, prefix, kind, *, params=None):
    """Drain every page. A page size is a transport setting, never a collection limit."""
    rows, ids, offset, expected, size = [], set(), 0, None, 500
    passes, previous_count = 0, -1
    while True:
        response = await client.get(prefix + '/' + kind, params={**(params or {}), 'limit': size, 'offset': offset})
        if response.status_code == 422 and size > 25:
            size //= 2
            continue
        try:
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KnowledgeAcquisitionError('Knowledge collection request failed') from exc
        if not isinstance(data, dict) or data.get('knowledge_base_id', int(prefix.rsplit('/', 1)[-1])) != int(prefix.rsplit('/', 1)[-1]):
            raise KnowledgeAcquisitionError('Foreign knowledge collection')
        page = data.get(kind)
        if not isinstance(page, list) or any(not isinstance(r, dict) or r.get('id') is None for r in page):
            raise KnowledgeAcquisitionError('Invalid knowledge collection page')
        total = data.get('total')
        if total is not None:
            if type(total) is not int or total < 0:
                raise KnowledgeAcquisitionError('Invalid knowledge collection total')
            expected = total
        if not page:
            if expected is not None and len(rows) != expected:
                if passes >= 3 or len(rows) <= previous_count or len(rows) > expected:
                    raise KnowledgeAcquisitionError('Knowledge collection could not be completed while changing')
                previous_count = len(rows)
                passes += 1
                offset = 0
                continue
            break
        for row in page:
            identity = str(row['id'])
            if identity in ids:
                continue
            ids.add(identity)
            rows.append(row)
        offset += len(page)
        if expected is not None and offset >= expected:
            if len(rows) == expected:
                break
            if passes >= 3 or len(rows) <= previous_count or len(rows) > expected:
                raise KnowledgeAcquisitionError('Knowledge collection could not be completed while changing')
            previous_count = len(rows)
            passes += 1
            offset = 0
        # The server may cap page length below requested size. Stop only on an empty page.
    return rows

async def _export(client, prefix, kind):
    response = await client.get(prefix + '/' + kind + '/export', params={'format': 'json'})
    if response.status_code in {404, 405}:
        return await _pages(client, prefix, kind)
    try:
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise KnowledgeAcquisitionError('Knowledge export failed') from exc
    rows = data.get(kind) if isinstance(data, dict) else None
    if not isinstance(rows, list) or data.get('knowledge_base_id', int(prefix.rsplit('/', 1)[-1])) != int(prefix.rsplit('/', 1)[-1]):
        raise KnowledgeAcquisitionError('Invalid or foreign complete export')
    if type(data.get('total')) is not int or data['total'] != len(rows) or data.get('exported_count', len(rows)) != len(rows):
        raise KnowledgeAcquisitionError('Incomplete knowledge export')
    return rows

_LOCKS = weakref.WeakKeyDictionary()

async def acquire_knowledge_base(config, *, transport=None, force_refresh=False, cache_path=None):
    loop = asyncio.get_running_loop()
    locks = _LOCKS.setdefault(loop, {})
    key = str(cache_path if cache_path is not None else snapshot_path(config))
    lock = locks.setdefault(key, asyncio.Lock())
    async with lock:
        return await _acquire_knowledge_base(config, transport=transport, force_refresh=force_refresh, cache_path=cache_path)

async def _acquire_knowledge_base(config, *, transport=None, force_refresh=False, cache_path=None):
    path = Path(cache_path) if cache_path is not None else snapshot_path(config)
    ttl = float(os.environ.get('WGS_KNOWLEDGE_SNAPSHOT_TTL', '300'))
    if not force_refresh and transport is None and path.is_file():
        try:
            data = validate_snapshot(json.loads(path.read_text()), config.knowledge_base_id)
            if 0 <= time.time() - data['acquired_at'] <= ttl:
                return data
        except (OSError, ValueError, KeyError, TypeError, KnowledgeAcquisitionError):
            pass
    prefix = f'/knowledge-bases/{config.knowledge_base_id}'
    headers = {'Accept': 'application/json'}
    if config.token:
        headers['Authorization'] = 'Bearer ' + config.token
    # File publication is atomic; failures never publish a partial snapshot.
    async with httpx.AsyncClient(base_url=config.base_url, headers=headers, timeout=max(config.timeout, 120), transport=transport) as client:
        for attempt in range(3):
            try:
                meta = await _json(client, prefix)
                kb = meta.get('knowledge_base', meta)
                if kb.get('id') != config.knowledge_base_id:
                    raise KnowledgeAcquisitionError('Foreign knowledge base metadata')
                entities, relations, claims, facts = await asyncio.gather(
                    _pages(client, prefix, 'entities'),
                    _pages(client, prefix, 'relations', params={'include_pending': 'true', 'include_negated': 'true', 'include_speculative': 'true', 'evidence_limit': 3}),
                    _export(client, prefix, 'claims'), _export(client, prefix, 'facts'))
                data = {'schema': 'litkg-full-kb-v1', 'knowledge_base_id': config.knowledge_base_id,
                        'acquisition_scope': 'full', 'complete': True, 'acquired_at': time.time(),
                        'consistency': 'complete-per-collection; source may change between collections',
                        'knowledge_base': kb, 'entities': entities, 'relations': relations, 'claims': claims, 'facts': facts,
                        'counts': {'entities': len(entities), 'relations': len(relations), 'claims': len(claims), 'facts': len(facts)}}
                validate_snapshot(data, config.knowledge_base_id)
                break
            except KnowledgeAcquisitionError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.2)
    if transport is None or cache_path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.snapshot-')
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return data
