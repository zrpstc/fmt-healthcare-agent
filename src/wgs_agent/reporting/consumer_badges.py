"""G15: conservative, source-deduplicated badges for glossary explanations."""
from __future__ import annotations
import re
from urllib.parse import urlsplit


def _source_identity(source):
    doi = str(source.get('doi') or '').casefold().removeprefix('https://doi.org/').removeprefix('doi:').strip()
    if doi: return 'doi:' + doi
    pmid = str(source.get('pmid') or '').strip()
    if pmid: return 'pmid:' + pmid
    kind = source.get('type')
    ident = str(source.get('id_or_url') or '')
    if kind == 'pubmed': return 'pmid:' + ident.rstrip('/').split('/')[-1]
    if source.get('document_id') is not None:
        return 'document:' + str(source.get('knowledge_base_id') or '') + ':' + str(source['document_id'])
    title = str(source.get('title') or '').casefold().strip()
    if title and title != 'litkg功能证据': return 'title:' + re.sub(r'\W+', '', title)
    if kind == 'litkg': return 'unresolved-litkg-paper'
    if kind == 'web':
        url = urlsplit(ident)
        return 'web:' + str(url.hostname or '').casefold() + url.path.rstrip('/')
    return str(kind) + ':' + ident


def research_badge(entry, *, field='one_liner'):
    """Count independent species-level studies, never claims from the same paper.

    Curated editorial sources are not research studies. Strain-only evidence does
    not receive a species-level badge. A watch badge requires a visible one_liner
    as well as a separately approved watch note.
    """
    if not entry or not entry.get('one_liner') or entry.get('review_status') != 'approved': return None
    if field == 'watch_note':
        if not entry.get('watch_note') or entry.get('watch_review_status') != 'approved': return None
        sources = entry.get('watch_sources', [])
        scope = entry.get('watch_evidence_scope')
    else:
        sources = entry.get('sources', []); scope = entry.get('evidence_scope')
    studies = {}
    for source in sources:
        if source.get('type') not in {'litkg', 'pubmed', 'web'}: continue
        studies.setdefault(_source_identity(source), set()).add(source.get('evidence_scope', scope))
    species = sum('species' in scopes for scopes in studies.values())
    if species >= 3: return '多项研究'
    if species: return '少量研究'
    if studies and all(scopes <= {'genus'} for scopes in studies.values()): return '同属研究推断'
    return None
