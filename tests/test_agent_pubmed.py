import io
import json

import pytest

from wgs_agent.tools.knowledge_tools import PubmedSearchTool


@pytest.mark.asyncio
async def test_empty_and_structured_abstracts_do_not_break_retrieval(monkeypatch):
    xml = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
    <ArticleTitle>Vitamin <i>B12</i> study</ArticleTitle><Abstract>
    <AbstractText Label="BACKGROUND"/><AbstractText Label="RESULTS">First <b>finding</b>.</AbstractText>
    <AbstractText Label="CONCLUSIONS">Full conclusion.</AbstractText></Abstract>
    <PublicationTypeList><PublicationType>Review</PublicationType></PublicationTypeList>
    </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
    responses = iter([json.dumps({'esearchresult': {'idlist': ['123']}}).encode(), xml])
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: io.BytesIO(next(responses)))
    monkeypatch.setattr('time.sleep', lambda *a: None)
    result = await PubmedSearchTool().invoke({'query': 'vitamin', 'max_results': 1})
    assert result.is_error is False
    data = json.loads(result.content.split('---JSON---\n')[1])[0]
    assert data['title'] == 'Vitamin B12 study'
    assert data['abstract'] == 'RESULTS: First finding.\nCONCLUSIONS: Full conclusion.'
    assert data['publication_types'] == ['Review']
    assert data['url'] == 'https://pubmed.ncbi.nlm.nih.gov/123/'
    assert data['abstract_truncated'] is False
