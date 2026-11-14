"""Reproducible synthetic cMD-scale benchmark; never publishes a reference."""
from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import resource
import tempfile
import time

import numpy as np

from wgs_agent.reporting import cmd, population_reference as population


def benchmark(subjects=3500, species=1000):
    if subjects < 30 or species < 2:
        raise ValueError('benchmark requires >=30 subjects and >=2 species')
    rng = np.random.default_rng(20261114)
    with tempfile.TemporaryDirectory(prefix='cmd-benchmark-') as directory:
        root = Path(directory)
        base, targets = root/'reference', root/'targets'
        base.mkdir()
        folder = targets/'BENCHMARK'
        folder.mkdir(parents=True)
        features = [f's__Benchmark_taxon_{j}' for j in range(species)]
        with (base/'metadata.tsv').open('w', newline='') as f:
            writer = csv.writer(f, delimiter='\t')
            writer.writerow(['sample_id', 'subject_id', 'study_id', 'phenotype', 'source_runs', 'number_reads'])
            writer.writerows([f'R{i}', f'P{i}', f'Study{i%20}', cmd.PHENOTYPE, '', 1_000_000+i*100] for i in range(subjects))
        with (base/'species_abundance.tsv').open('w', newline='') as f:
            writer = csv.writer(f, delimiter='\t')
            writer.writerow(['sample_id', *features])
            for i in range(subjects):
                values = rng.gamma(1., 1., species)
                values[rng.random(species) < .25] = 0
                values *= 100 / values.sum()
                writer.writerow([f'R{i}', *(format(v, '.12g') for v in values)])
        manifest = {'schema_version': cmd.VERSION, 'cohort_id': 'synthetic-benchmark-only',
            'cohort_version': 'seed-20261114', 'source_package': 'curatedMetagenomicData',
            'source_package_version': 'synthetic-contract-fixture', 'source_url': 'https://example.org/synthetic-benchmark',
            'pipeline': cmd.PIPELINE, 'normalization': cmd.NORMALIZATION, 'unit': '%', 'phenotype': cmd.PHENOTYPE,
            'body_site': 'stool', 'feature_level': 'species', 'complete_species_profiles': True,
            'minimum_subjects': 30, 'stratify_by': [],
            'selection_criteria': {'minimum_age': 18, 'disease': 'healthy', 'study_condition': 'control',
                'antibiotics_current_use': 'no', 'deduplicate_by': ['study_id', 'subject_id']},
            'files': {name: cmd.digest((base/name).read_bytes()) for name in ('metadata.tsv', 'species_abundance.tsv')}}
        (base/'manifest.json').write_text(json.dumps(manifest))
        observed = rng.gamma(1., 1., species)
        observed *= 100/observed.sum()
        raw = (f"#{cmd.PIPELINE['database_version']}\n#MetaPhlAn version 3.0.14\n" + ''.join(
            f'k__Bacteria|{name}\t1\t{value:.12g}\n' for name, value in zip(features, observed))).encode()
        (folder/'profile.tsv').write_bytes(raw)
        (folder/'provenance.json').write_text(json.dumps({'sample_id': 'BENCHMARK',
            'pipeline': dict(cmd.SPEC.target_pipeline), 'normalization': cmd.NORMALIZATION,
            'profile_sha256': cmd.digest(raw), 'number_reads': 1_000_000}))
        os.environ['WGS_CMD_REFERENCE_DIR'] = str(base)
        os.environ['WGS_CMD_PROFILES_DIR'] = str(targets)
        population.clear_bundle_cache()
        start = time.perf_counter()
        first = cmd.compare('BENCHMARK', {})
        cold = time.perf_counter()-start
        if first['audit']['status'] != 'available':
            raise RuntimeError('synthetic benchmark comparison unavailable')
        matrix = cmd.load_bundle(base)[3]
        start = time.perf_counter()
        second = cmd.compare('BENCHMARK', {})
        warm = time.perf_counter()-start
        assert cmd.load_bundle(base)[3] is matrix
        assert first == second
        return {'subjects': subjects, 'species': species, 'bootstrap_iterations': population.BOOTSTRAP_ITERATIONS,
            'seed': population.BOOTSTRAP_SEED, 'cold_comparison_seconds': cold, 'warm_comparison_seconds': warm,
            'peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            'matrix_mib': matrix.values_array.nbytes / 1024**2,
            'input_matrix_bytes': (base/'species_abundance.tsv').stat().st_size,
            'cache_reused': True, 'comparison_reproducible': True, 'ordination_reference_limit': 300}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subjects', type=int, default=3500)
    parser.add_argument('--species', type=int, default=1000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = benchmark(args.subjects, args.species)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text)
    else:
        print(text)
