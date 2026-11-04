"""Read-based acquired ARG and insertion-sequence/MITE screening for chapter 5.

This is a Bowtie2 screen against ResFinder sequences and MGEdb IS/MITE
references, not the ResFinder or MobileElementFinder application. It does not
infer phenotype, plasmid structure, host assignment or physical linkage.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

VERSION = 1
MODULES = ("resistance", "mobile_elements")
STATES = {"not_run", "running", "completed", "missing_input", "missing_database", "missing_dependency", "failed", "invalid_output", "locked"}
ROW_KEYS = {"name", "gene", "gene_aliases", "drug_class", "mechanism", "phenotype_annotation", "element_type", "family", "detected", "detection_status", "mapped_reads", "breadth_coverage", "coverage", "identity", "abundance", "abundance_unit", "source_unit", "result", "method", "sequence_evidence", "host_linked", "mobile_element_linked", "reference_length", "database", "reference_scope", "database_version"}


def sample_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("INVALID_SAMPLE_ID")
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".chapter5-", delete=False) as handle:
            temp = Path(handle.name)
            os.chmod(temp, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


@contextmanager
def lock(path):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        os.chmod(path, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def artifact_path(root, module, sid):
    if module not in MODULES:
        raise ValueError("INVALID_MODULE")
    return Path(root) / "modules" / module / (sample_name(sid) + ".json")


def envelope(module, sid, status="not_run", reason_code="", **extra):
    return {"schema_version": VERSION, "sample_id": sample_name(sid), "module": module,
            "status": status, "reason_code": reason_code, "generated_at": datetime.now(timezone.utc).isoformat(),
            "genes" if module == "resistance" else "results": [], **extra}


def load_chapter5_inputs(sid, root, *, include_missing=True):
    sid = sample_name(sid)
    root = Path(root).resolve()
    result = {}
    for module in MODULES:
        path = artifact_path(root, module, sid)
        key = "genes" if module == "resistance" else "results"
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError("PATH_ESCAPE")
            if not path.is_file():
                if include_missing:
                    result[module] = envelope(module, sid)
                continue
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("OVERSIZED_ARTIFACT")
            value = json.loads(path.read_text(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict) or value.get("schema_version") != VERSION or value.get("sample_id") != sid or value.get("module") != module or value.get("status") not in STATES or not isinstance(value.get(key), list):
                raise ValueError("INVALID_ARTIFACT")
            rows = []
            if value["status"] == "completed":
                for row in value[key]:
                    if not isinstance(row, dict):
                        raise ValueError("INVALID_ROW")
                    safe = {}
                    for k, v in row.items():
                        if k not in ROW_KEYS:
                            continue
                        if isinstance(v, float) and not math.isfinite(v):
                            raise ValueError("NONFINITE")
                        if v is None or isinstance(v, (str, int, float, bool)):
                            safe[k] = v
                        elif k == "gene_aliases" and isinstance(v, list) and all(isinstance(x, str) for x in v):
                            safe[k] = v
                    if safe.get("detected") is not True or not (safe.get("gene") or safe.get("name")):
                        raise ValueError("INVALID_DETECTION")
                    rows.append(safe)
            fields = {"schema_version", "sample_id", "module", "status", "reason_code", "generated_at", "method", "database", "database_version", "reference_scope", "fingerprint", "database_sha256", "thresholds", "summary"}
            safe = {k: v for k, v in value.items() if k in fields}
            for k in ("summary", "thresholds"):
                if k in safe:
                    if not isinstance(safe[k], dict):
                        raise ValueError("INVALID_SUMMARY")
                    safe[k] = {n: v for n, v in safe[k].items() if n in {"input_reads", "reference_count", "detected_count", "candidate_count", "rejected_reads", "min_reads", "min_breadth", "min_identity", "min_mapq"} and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0}
            safe.update({key: rows, "source_files": [str(path)]})
            result[module] = safe
        except FileNotFoundError:
            if include_missing:
                result[module] = envelope(module, sid)
        except (OSError, ValueError, TypeError, AttributeError):
            result[module] = envelope(module, sid, "invalid_output", "ARTIFACT_UNREADABLE_OR_INVALID")
    return result


def merge_chapter5_inputs(inputs, analysis):
    for module in MODULES:
        fresh = inputs.get(module)
        if isinstance(fresh, dict) and fresh.get("status") != "not_run":
            continue
        if isinstance(analysis.get(module), (dict, list)):
            inputs[module] = analysis[module]
    return inputs


def fingerprint_reads(path):
    digest, count = hashlib.sha256(), 0
    opener = gzip.open if Path(path).suffix == ".gz" else open
    with opener(path, "rt", encoding="ascii") as handle:
        while True:
            header = handle.readline()
            if not header:
                break
            seq, plus, quality = handle.readline(), handle.readline(), handle.readline()
            if not header.startswith("@") or not plus.startswith("+") or not seq.strip() or len(seq.rstrip()) != len(quality.rstrip()) or not re.fullmatch(r"[ACGTNacgtn]+", seq.rstrip()):
                raise ValueError("INVALID_FASTQ")
            digest.update((header + seq + plus + quality).encode("ascii"))
            count += 1
    if not count:
        raise ValueError("EMPTY_FASTQ")
    return {"sha256": digest.hexdigest(), "reads": count}


def summarize_sam(path, catalog, *, expected_reads=None, min_reads=3, min_breadth=80.0, min_identity=90.0, min_mapq=20):
    """Count independent read alignments, with union breadth and weighted identity."""
    if min_reads < 1 or not 0 < min_breadth <= 100 or not 0 < min_identity <= 100 or not 0 <= min_mapq <= 254:
        raise ValueError("INVALID_THRESHOLDS")
    events = defaultdict(Counter)
    evidence = defaultdict(Counter)
    references, primary, rejected = {}, 0, 0
    with Path(path).open() as handle:
        for line in handle:
            if line.startswith("@SQ\t"):
                h = dict(x.split(":", 1) for x in line.rstrip().split("\t")[1:] if ":" in x)
                name, length = h.get("SN"), int(h.get("LN", 0))
                if name in references or name not in catalog or length != catalog[name]["length"]:
                    raise ValueError("INVALID_SAM_REFERENCE")
                references[name] = length
                continue
            if line.startswith("@"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 11:
                raise ValueError("INVALID_SAM")
            flag, pos, mapq = int(f[1]), int(f[3]) - 1, int(f[4])
            if flag & (0x100 | 0x800):
                continue
            primary += 1
            if flag & 4:
                continue
            if flag & (0x200 | 0x400) or mapq < min_mapq or mapq == 255:
                rejected += 1
                continue
            target = f[2]
            if target not in references or pos < 0:
                raise ValueError("INVALID_SAM_POSITION")
            ops = re.findall(r"(\d+)([MIDNSHP=X])", f[5])
            if not ops or "".join(n + c for n, c in ops) != f[5] or any(int(n) <= 0 for n, _ in ops):
                raise ValueError("INVALID_CIGAR")
            ops = [(int(n), c) for n, c in ops]
            if f[9] == "*" or sum(n for n, c in ops if c in "MIS=X") != len(f[9]):
                raise ValueError("INVALID_QUERY_LENGTH")
            columns = sum(n for n, c in ops if c in "MID=X")
            nm = [x[5:] for x in f[11:] if x.startswith("NM:i:")]
            if len(nm) != 1 or not nm[0].isdigit() or not columns:
                rejected += 1
                continue
            edits = int(nm[0])
            if edits > columns:
                raise ValueError("INVALID_EDIT_DISTANCE")
            cursor, intervals = pos, []
            for n, c in ops:
                if c in "M=X":
                    intervals.append((cursor, cursor+n))
                    cursor += n
                elif c in "DN":
                    cursor += n
            if cursor > references[target]:
                raise ValueError("ALIGNMENT_OUT_OF_BOUNDS")
            if 100 * (columns-edits) / columns < min_identity:
                rejected += 1
                continue
            evidence[target].update(reads=1, matching=columns-edits, columns=columns)
            for a, b in intervals:
                events[target][a] += 1
                events[target][b] -= 1
    if set(references) != set(catalog) or primary == 0 or (expected_reads is not None and primary != expected_reads):
        raise ValueError("INCOMPLETE_SAM")
    rows, candidates = [], 0
    for target, counts in evidence.items():
        depth, last, covered, area = 0, 0, 0, 0
        for point, delta in sorted(events[target].items()):
            if depth:
                covered += point-last
                area += depth*(point-last)
            depth += delta
            last = point
        entry = catalog[target]
        length = entry["length"]
        breadth = 100 * covered / length
        if counts["reads"] < min_reads or breadth < min_breadth:
            candidates += 1
            continue
        row = {k: v for k, v in entry.items() if k in ROW_KEYS}
        row.update(detected=True, detection_status="detected", mapped_reads=counts["reads"],
                   breadth_coverage=round(breadth, 4), coverage=round(area/length, 4),
                   identity=round(100*counts["matching"]/counts["columns"], 4),
                   abundance=round(counts["reads"]*1e9/(length*primary), 6), abundance_unit="RPKM", source_unit="RPKM",
                   reference_length=length, host_linked=False, mobile_element_linked=False,
                   result="检出参考序列信号", method="Bowtie2 reference-read screen",
                   sequence_evidence=f"{counts['reads']} reads; breadth {breadth:.2f}%; identity {100*counts['matching']/counts['columns']:.2f}%")
        rows.append(row)
    rows.sort(key=lambda r: (-r["abundance"], r.get("gene", r["name"])))
    return rows, {"input_reads": primary, "reference_count": len(catalog), "detected_count": len(rows), "candidate_count": candidates, "rejected_reads": rejected}


def execute(command, log_dir, name, env):
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir/(name+".stdout")).open("wb") as out, (log_dir/(name+".stderr")).open("wb") as err:
        os.chmod(out.name, 0o600)
        os.chmod(err.name, 0o600)
        r = subprocess.run([str(x) for x in command], stdout=out, stderr=err, env=env, timeout=14400)
    if r.returncode:
        raise RuntimeError("ALIGNER_NONZERO")


def run_module(root, sid, reads, database_root, tax_bin, module, *, threads=4, force=False, min_reads=3, min_breadth=80.0, min_identity=90.0, min_mapq=20):
    root, reads, database_root, tax_bin = map(Path, (root, reads, database_root, tax_bin))
    output = artifact_path(root, module, sid)
    log_dir = root/"module-work"/sample_name(sid)/module
    thresholds = dict(min_reads=min_reads, min_breadth=min_breadth, min_identity=min_identity, min_mapq=min_mapq)
    try:
        with lock(log_dir/".lock"):
            try:
                if not reads.is_file():
                    value = envelope(module, sid, "missing_input", "CLEAN_FASTQ_MISSING")
                elif not (database_root/module/"manifest.json").is_file():
                    value = envelope(module, sid, "missing_database", "REFERENCE_DATABASE_MISSING")
                elif any(not (tax_bin/x).is_file() for x in ("bowtie2", "bowtie2-build")):
                    value = envelope(module, sid, "missing_dependency", "BOWTIE2_MISSING")
                else:
                    db = database_root/module
                    manifest = json.loads((db/"manifest.json").read_text())
                    catalog = json.loads((db/"catalog.json").read_text())
                    fasta = db/"references.fna"
                    checksum = hashlib.sha256(fasta.read_bytes()).hexdigest()
                    catalog_checksum = hashlib.sha256((db/"catalog.json").read_bytes()).hexdigest()
                    if checksum != manifest["sha256"] or catalog_checksum != manifest["catalog_sha256"] or not catalog:
                        raise ValueError("DATABASE_CHECKSUM_MISMATCH")
                    input_info = fingerprint_reads(reads)
                    identity = [(str((tax_bin/n).resolve()), (tax_bin/n).stat().st_mtime_ns) for n in ("bowtie2", "bowtie2-build")]
                    fingerprint = hashlib.sha256(json.dumps([VERSION, input_info, checksum, manifest, thresholds, identity], sort_keys=True).encode()).hexdigest()
                    old = load_chapter5_inputs(sid, root, include_missing=False).get(module, {})
                    if not force and old.get("status") == "completed" and old.get("fingerprint") == fingerprint:
                        return old
                    base = {"fingerprint": fingerprint, "database_sha256": checksum, "thresholds": thresholds, "database": manifest["database"], "database_version": manifest["version"], "reference_scope": manifest["scope"], "method": "Bowtie2 reference-read screen"}
                    atomic_json(output, envelope(module, sid, "running", **base))
                    env = {**os.environ, "PATH": str(tax_bin)+os.pathsep+os.environ.get("PATH", "")}
                    with lock(db/".index.lock"):
                        index = db/"index"/"reference"
                        index.parent.mkdir(parents=True, exist_ok=True)
                        ready = db/"index"/"ready.json"
                        known = json.loads(ready.read_text()) if ready.is_file() else {}
                        indexes = [index.parent/(index.name+s+".bt2") for s in (".1", ".2", ".3", ".4", ".rev.1", ".rev.2")]
                        if known.get("sha256") != checksum or not all(x.is_file() for x in indexes):
                            execute([tax_bin/"bowtie2-build", "--threads", max(1, min(int(threads), 16)), fasta, index], log_dir, "index", env)
                            if not all(x.is_file() for x in indexes):
                                raise ValueError("INCOMPLETE_INDEX")
                            atomic_json(ready, {"sha256": checksum})
                    with tempfile.TemporaryDirectory(prefix="run-", dir=log_dir) as temp:
                        sam = Path(temp)/"alignments.sam"
                        execute([tax_bin/"bowtie2", "--very-sensitive", "--end-to-end", "--seed", "42", "-p", max(1, min(int(threads), 16)), "-x", index, "-U", reads, "-S", sam], log_dir, "align", env)
                        rows, summary = summarize_sam(sam, catalog, expected_reads=input_info["reads"], **thresholds)
                    key = "genes" if module == "resistance" else "results"
                    value = envelope(module, sid, "completed", **base, summary=summary, **{key: rows})
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired):
                value = envelope(module, sid, "failed", "INPUT_DATABASE_OR_ALIGNMENT_INVALID")
            atomic_json(output, value)
            return value
    except BlockingIOError:
        return envelope(module, sid, "locked", "ANALYSIS_ALREADY_RUNNING")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reads", type=Path)
    parser.add_argument("--database-root", type=Path)
    parser.add_argument("--tax-bin", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    from wgs_fmt_platform.paths import PROJECT_ROOT
    sid = sample_name(args.sample_id)
    reads = args.reads or args.output_root/"clean_merged"/(sid+".dehosted.fastq.gz")
    db = args.database_root or Path(os.environ.get("WGS_CHAPTER5_DATABASE_ROOT") or PROJECT_ROOT/"fmt-databases/resistome_mge")
    tax = args.tax_bin or Path(os.environ.get("WGS_CHAPTER5_TAX_BIN") or PROJECT_ROOT/"var/runtime/envs/fmt-tax/bin")
    results = {module: run_module(args.output_root, sid, reads, db, tax, module, threads=args.threads, force=args.force) for module in MODULES}
    print(json.dumps({k: {"status": v["status"], "reason_code": v["reason_code"], "summary": v.get("summary", {})} for k, v in results.items()}))
    return 0 if all(v["status"] == "completed" for v in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
