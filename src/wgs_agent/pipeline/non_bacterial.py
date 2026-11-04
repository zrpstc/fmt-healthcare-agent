"""Chapter six inputs from full MetaPhlAn profiles and completed VSC screens.

The marker assay has limited reference coverage. No inference of fungal
membership from Eukaryota, and no inference of DNA type or host from a VSC name.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

SCHEMA = 1
MODULES = ('archaea', 'fungi', 'dna_viruses')
FUNGAL_PHYLA = frozenset(('Ascomycota', 'Basidiomycota', 'Mucoromycota',
    'Chytridiomycota', 'Blastocladiomycota', 'Zoopagomycota', 'Microsporidia',
    'Glomeromycota', 'Cryptomycota'))


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def sample_path(sample_id, root):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', sample_id) or sample_id in ('.', '..'):
        raise ValueError('invalid sample identifier')
    return Path(root).resolve()


def within(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('input outside bioinformatics root')
    return path


def classify(lineage):
    parts = str(lineage).split('|')
    if any(x in ('k__Archaea', 'd__Archaea', 'd__Archaea') for x in parts):
        return 'archaea'
    if 'k__Fungi' in parts or any(x.startswith('p__') and x[3:] in FUNGAL_PHYLA for x in parts):
        return 'fungi'
    return None


def payload(status, method, source=None, **extra):
    return {'chapter_six_schema': SCHEMA, 'status': status, 'method': method,
            'records': [], 'source_file': str(source) if source else None, **extra}


def read_marker_profile(path):
    path = Path(path)
    output = {k: payload('not_analyzed', 'MetaPhlAn marker profile', path,
                        reason='profile_missing', scope='reference_marker_screen',
                        unit='%', denominator='all_profiled_cellular_organisms') for k in MODULES[:2]}
    if not path.is_file():
        return output
    seen = set()
    valid_rows = invalid_rows = 0
    headers = None
    db_version = None
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if line.startswith('#mpa_'):
                db_version = line[1:].strip()
            stripped = line.lstrip('#').strip()
            if stripped.startswith('clade_name\t'):
                headers = stripped.split('\t')
                continue
            if not stripped or line.startswith('#'):
                continue
            cells = line.rstrip('\r\n').split('\t')
            idx = headers.index('relative_abundance') if headers and 'relative_abundance' in headers else 2
            if len(cells) <= idx:
                invalid_rows += 1
                continue
            lineage = cells[0]
            value = number(cells[idx])
            if value is None or value > 100 or not (lineage.startswith(('k__', 'd__')) or lineage == 'UNCLASSIFIED'):
                invalid_rows += 1
                continue
            valid_rows += 1
            leaf = lineage.rsplit('|', 1)[-1]
            if not leaf.startswith('s__'):
                continue
            if lineage in seen:
                invalid_rows += 1
                continue
            seen.add(lineage)
            group = classify(lineage)
            if group and value > 0:
                output[group]['records'].append({'name': leaf[3:].replace('_', ' '),
                    'lineage': lineage, 'tax_id': cells[1].rsplit('|', 1)[-1] if len(cells) > 1 else None,
                    'abundance': value, 'unit': '%', 'detected': True,
                    'source_file': str(path), 'method': 'MetaPhlAn marker profile'})
    for module in output.values():
        valid = valid_rows > 0 and invalid_rows == 0
        module.update(status=('detected' if module['records'] else 'not_detected') if valid else 'invalid_input',
                      reason=None if valid else 'profile_invalid_or_empty', complete=valid,
                      database_version=db_version, invalid_rows=invalid_rows,
                      detected_species=len(module['records']), profile_rows=valid_rows)
        if not valid:
            module['records'] = []
    return output


def header_key(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def read_vsc(path, completed=False, threshold=0.75):
    path = Path(path)
    out = payload('not_analyzed', 'MetaPhlAn VSC', path, reason='viral_workflow_not_run',
                  scope='viral_sequence_clusters', genome_type_verified=False,
                  breadth_threshold=threshold, unit=None)
    if not completed or not path.is_file():
        return out
    aliases = {
        'id': ('mgroupcluster', 'mgroup', 'vsc', 'vscid', 'vsg', 'vsgid'),
        'breadth': ('breadthofcoverage', 'breadth'),
        'mean': ('depthofcoveragemean', 'meandepth', 'meandepthofcoverage'),
        'median': ('depthofcoveragemedian', 'mediandepth', 'mediandepthofcoverage'),
        'reference': ('firstgenomeincluster', 'firstgenome', 'referencegenome'),
        'kind': ('mgrouptypeku', 'mgrouptype', 'grouptype', 'vsgtype'),
        'genome_type': ('genometype',),
    }
    header = None
    invalid = 0
    records = []
    seen = set()
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            cells = next(csv.reader([line.lstrip('#').rstrip('\r\n')], delimiter='\t'))
            keys = [header_key(x) for x in cells]
            if any(k in keys for k in aliases['id']) and any(k in keys for k in aliases['breadth']):
                header = keys
                continue
            if line.startswith('#'):
                continue
            if header is None or len(cells) != len(header):
                invalid += 1
                continue
            raw = dict(zip(header, cells))
            def get(key):
                return next((raw[k] for k in aliases[key] if k in raw), None)
            ident, breadth, depth = get('id'), number(get('breadth')), number(get('mean'))
            if not ident or ident in seen or breadth is None or breadth > 1 or depth is None:
                invalid += 1
                continue
            seen.add(ident)
            if breadth < threshold or depth <= 0:
                continue
            gt = re.sub(r'[^a-z]', '', (get('genome_type') or '').lower())
            if gt in ('rna', 'ssrna', 'dsrna', 'positivessrna', 'negativessrna'):
                continue
            dna = gt in ('dna', 'ssdna', 'dsdna')
            reference = get('reference')
            if not reference or reference.strip().lower() in ('-', 'na', 'n/a', 'none', 'unknown'):
                reference = None
            records.append({'name': ident, 'vsc_id': ident, 'reference_genome': reference,
                'group_type': get('kind'), 'breadth_of_coverage': breadth,
                'depth_of_coverage_mean': depth, 'depth_of_coverage_median': number(get('median')),
                'genome_type': (get('genome_type') if dna else 'unknown'),
                'dna_confirmed': dna, 'detected': True, 'source_file': str(path)})
    valid = header is not None and invalid == 0
    out.update(status=('detected' if records else 'not_detected') if valid else 'invalid_input',
               reason=None if valid else 'vsc_schema_or_values_invalid', complete=valid,
               records=records if valid else [], invalid_rows=invalid,
               detected_clusters=len(records) if valid else None,
               dna_confirmed_clusters=sum(r['dna_confirmed'] for r in records) if valid else None,
               genome_type_unresolved_clusters=sum(not r['dna_confirmed'] for r in records) if valid else None)
    return out


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_chapter6_inputs(sample_id, root=None):
    if root is None:
        from wgs_fmt_platform.paths import bioinformatics_root
        root = bioinformatics_root()
    root = sample_path(sample_id, root)
    profile = within(root / 'profiles/metaphlan' / f'{sample_id}_profile.tsv', root)
    result = read_marker_profile(profile)
    vsc = within(root / 'profiles/viruses' / f'{sample_id}_vsc.tsv', root)
    marker = within(root / 'profiles/viruses' / f'{sample_id}_vsc.completed.json', root)
    complete = False
    if marker.is_file() and vsc.is_file():
        try:
            saved = json.loads(marker.read_text(encoding='utf-8'))
            complete = (saved.get('sample_id') == sample_id and saved.get('exit_code') == 0
                        and saved.get('vsc_sha256') == digest(vsc))
        except (OSError, ValueError, TypeError):
            pass
    result['dna_viruses'] = read_vsc(vsc, completed=complete)
    return result


def merge_chapter6_inputs(fresh, saved):
    """Verified disk outputs supersede stale generated summaries, not supplied assays."""
    result = {}
    for key in MODULES:
        current, previous = fresh.get(key), saved.get(key)
        if isinstance(current, dict) and current.get('complete'):
            result[key] = current
        elif isinstance(previous, (dict, list)) and not (isinstance(previous, dict) and previous.get('chapter_six_schema') == SCHEMA):
            result[key] = previous
        elif isinstance(current, dict):
            result[key] = current
    return result


def ensure_viral_output(sample_id, root, executable, db_dir, index, threads=4):
    """Supplement legacy cached cellular profiles without overwriting them."""
    root = sample_path(sample_id, root)
    target = within(root / 'profiles/viruses' / f'{sample_id}_vsc.tsv', root)
    if load_chapter6_inputs(sample_id, root)['dna_viruses'].get('complete'):
        return True
    fastq = within(root / 'clean_merged' / f'{sample_id}.dehosted.fastq.gz', root)
    if not fastq.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = os.environ.copy()
    env['PATH'] = str(Path(executable).resolve().parent) + os.pathsep + env.get('PATH', '')
    with tempfile.TemporaryDirectory(prefix=f'.{sample_id}.vsc-', dir=target.parent) as temp:
        temp = Path(temp)
        output = temp / 'vsc.tsv'
        args = [str(executable), str(fastq), '--input_type', 'fastq', '--db_dir', str(db_dir),
                '--index', index, '--offline', '--nproc', str(max(1, min(int(threads), 32))),
                '--profile_vsc', '--vsc_breadth', '0.75', '--vsc_out', str(output),
                '--samout', str(temp / 'viral.sam'), '--mapout', str(temp / 'viral.mapout.bz2'),
                '--tmp_dir', str(temp), '-o', str(temp / 'cellular_profile.tsv')]
        log = target.parent / f'{sample_id}_vsc.log'
        fd = os.open(log, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            completed = subprocess.run(args, env=env, stdout=handle, stderr=handle, check=False)
        if completed.returncode != 0 or not output.is_file():
            return False
        if read_vsc(output, completed=True)['status'] == 'invalid_input':
            return False
        os.replace(output, target)
        os.chmod(target, 0o600)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description='Record completed chapter six workflow inputs')
    parser.add_argument('--sample-id', required=True)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--complete-vsc', action='store_true')
    parser.add_argument('--ensure-viral', action='store_true')
    parser.add_argument('--metaphlan', type=Path)
    parser.add_argument('--db-dir', type=Path)
    parser.add_argument('--index')
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args(argv)
    root = sample_path(args.sample_id, args.output_root)
    vsc = within(root / 'profiles/viruses' / f'{args.sample_id}_vsc.tsv', root)
    if args.complete_vsc and vsc.is_file():
        parsed = read_vsc(vsc, completed=True)
        if parsed['status'] == 'invalid_input':
            raise ValueError('invalid VSC output')
        atomic_json(vsc.with_suffix('.completed.json'), {'sample_id': args.sample_id,
            'exit_code': 0, 'vsc_sha256': digest(vsc), 'schema_version': SCHEMA})
    viral_ok = True
    if args.ensure_viral:
        if not all((args.metaphlan, args.db_dir, args.index)):
            parser.error('--ensure-viral requires --metaphlan, --db-dir and --index')
        viral_ok = ensure_viral_output(args.sample_id, root, args.metaphlan, args.db_dir, args.index, args.threads)
    if (args.complete_vsc or args.ensure_viral) and viral_ok and vsc.is_file():
        parsed = read_vsc(vsc, completed=True)
        if parsed['status'] == 'invalid_input':
            raise ValueError('invalid VSC output')
        atomic_json(vsc.with_suffix('.completed.json'), {'sample_id': args.sample_id,
            'exit_code': 0, 'vsc_sha256': digest(vsc), 'schema_version': SCHEMA})
    result = load_chapter6_inputs(args.sample_id, root)
    atomic_json(root / 'profiles/non_bacterial' / f'{args.sample_id}.json',
                {'sample_id': args.sample_id, 'schema_version': SCHEMA, **result})
    return 0 if viral_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
