"""G14: one versioned consumer panel for matching, reference sums and G11 tags."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from .inputs import finite

PANEL = Path(__file__).resolve().parents[3] / 'knowledge_base/consumer_key_taxa.yaml'


def load_panel(path=None):
    path = Path(path) if path else PANEL
    raw = path.read_bytes(); panel = json.loads(raw)
    if panel.get('schema_version') != 'consumer-key-taxa-v1' or not isinstance(panel.get('categories'), list):
        raise ValueError('invalid_consumer_key_taxa_panel')
    ids = set()
    for category in panel['categories']:
        if category['id'] in ids or category['section'] not in {'helpful', 'watch'} or not category['members']:
            raise ValueError('invalid_consumer_key_taxa_category')
        ids.add(category['id'])
        if any(member['rank'] not in {'species', 'genus'} or not member['name'] for member in category['members']):
            raise ValueError('invalid_consumer_key_taxa_member')
    thresholds = panel.get('reliability_thresholds', {})
    if not 0 < thresholds.get('medium', 0) < thresholds.get('high', 0):
        raise ValueError('invalid_reliability_thresholds')
    return {**panel, 'sha256': hashlib.sha256(raw).hexdigest()}


def taxon_key(name):
    from .population_reference import species_key
    value = str(name or '')
    if '|s__' in value: value = value.rsplit('|s__', 1)[1]
    return species_key(value).replace('s__', '').strip()


def matches(name, member):
    key = taxon_key(name)
    names = [taxon_key(n) for n in [member['name'], *member.get('aliases', [])]]
    if member['rank'] == 'genus':
        return any(key == item or key.startswith(item + ' ') for item in names)
    return key in names


def category_matches(name, category):
    return any(matches(name, member) for member in category['members'])


def canonical_taxon(name, panel=None):
    panel = panel or load_panel()
    return next((taxon_key(member['name']) for category in panel['categories'] for member in category['members']
                 if member['rank'] == 'species' and matches(name, member)), taxon_key(name))


def primary_species(document):
    """Prefer the complete primary species table; never add genus and species sums."""
    taxonomy = document.get('template_inputs', {}).get('taxonomy') or {}
    rows = taxonomy.get('ranks', {}).get('species')
    if not isinstance(rows, list):
        rows = [row for row in document.get('evidence', {}).values() if row.get('kind') == 'species']
    result = []
    seen = set()
    for row in rows:
        name = row.get('species') or row.get('name') or row.get('label') or row.get('taxon')
        key = taxon_key(name)
        value = finite(row.get('value', row.get('abundance')))
        unit = row.get('unit', taxonomy.get('unit'))
        if key and key not in seen and value is not None and value >= 0 and unit == '%':
            result.append({**row, 'species': str(name), 'value': value, 'unit': '%'})
            seen.add(key)
    return result


def reliability(row, thresholds=None):
    thresholds = thresholds or load_panel()['reliability_thresholds']
    fields = ('estimated_reads', 'estimated_read_count', 'estimated_number_of_reads', 'estimated_number_of_reads_from_the_clade')
    for field in fields:
        if field not in row: continue
        number = finite(row[field])
        if number is None or number < 0 or not float(number).is_integer(): return None
        return {'label': '高' if number >= thresholds['high'] else '中' if number >= thresholds['medium'] else '低',
                'estimated_reads': int(number), 'source_field': field}
    return None


def function_tag_entries(document, panel=None):
    """Resolve G11 functional tags from the SAME panel, including genus members."""
    panel = panel or load_panel()
    return [{'latin': row['species'], 'tags': category['function_tags'], 'source': panel['schema_version']}
            for category in panel['categories'] if category.get('function_tags')
            for row in primary_species(document) if category_matches(row['species'], category)]


def category_totals(species, panel=None):
    """Sum each matching species once within a category, without cross-rank sums."""
    panel = panel or load_panel()
    return {category['id']: math.fsum(value for name, value in species.items() if category_matches(name, category))
            for category in panel['categories']}


def build_panel(document, *, panel=None, references=None):
    from .chapter_two import qc_failed
    from .consumer_state import omit
    panel = panel or load_panel(); rows = primary_species(document)
    taxonomy = document.get('template_inputs', {}).get('taxonomy') or {}
    qc = str(document.get('metadata', {}).get('qc_status', '')).casefold()
    complete = taxonomy.get('complete') is True
    passed = qc in {'passed', 'pass', '通过', '合格'}
    comparison_rows = document.get('consumer', {}).get('chapters', {}).get('1', {}).get('reference_rows')
    if comparison_rows is None:
        if document.get('template_inputs', {}).get('healthy_comparison', {}).get('audit', {}).get('status') == 'available' and 'sections' in document:
            from .consumer_chapter import comparison_rows as first_reference_rows
            comparison_rows = first_reference_rows(document)
        else:
            comparison_rows = []
    fragile_high = any(taxon_key(row.get('species') or row.get('name') or row.get('label')) == 'bacteroides fragilis'
                       and row.get('tier_label') == '明显偏高' for row in comparison_rows)
    cards = []
    for category in panel['categories']:
        ident = category['id']
        if ident == 'watch.conditional_commensal' and not fragile_high:
            omit(document, 3, ident, 'conditional_commensal_not_high', '第1章没有标为明显偏高')
            continue
        if qc_failed(document):
            omit(document, 3, ident, 'qc_failed', '质控未通过，不发布重点菌判断'); continue
        matched = [row for row in rows if category_matches(row['species'], category)]
        detected = [row for row in matched if row['value'] > 0]
        absent = not matched and passed and complete
        if not detected and not absent:
            omit(document, 3, ident, 'absence_not_established', '缺少质控通过、完整分类谱或成员完全缺席的联合依据'); continue
        members = []
        for row in sorted(detected, key=lambda item: (-item['value'], item['species'])):
            badge = reliability(row, panel['reliability_thresholds'])
            if badge is None:
                omit(document, 3, 'reliability:'+taxon_key(row['species']), 'estimated_reads_missing', '原分类输出没有可用的估算读段字段')
            note = next((member.get('note') for member in category['members'] if member.get('note') and matches(row['species'], member)), '')
            members.append({**row, 'reliability': badge, 'panel_note': note})
        reference = (references or {}).get(ident)
        cards.append({**category, 'members': members, 'total': math.fsum(row['value'] for row in detected),
                      'status': 'not_detected' if absent else 'detected', 'reference': reference,
                      'absence_basis': {'qc_passed': passed, 'taxonomy_complete': complete, 'members_absent': not matched}})
    return {'panel_version': panel['schema_version'], 'panel_sha256': panel['sha256'], 'cards': cards,
            'reliability_thresholds': panel['reliability_thresholds'], 'taxonomy_complete': complete, 'qc_passed': passed}
