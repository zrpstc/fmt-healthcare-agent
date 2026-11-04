"""Independent, resumable chapter-four sequence analyses (stdlib orchestration)."""
from __future__ import annotations

import argparse
import bz2
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import re
import shutil
import subprocess
import tempfile

VERSION = "chapter4-v1"
STATES = {"not_run", "running", "completed", "missing_input", "missing_database",
          "missing_tool", "insufficient_coverage", "failed", "invalid_result"}
MODULES = ("strains", "virulence")


class AnalysisError(Exception):
    def __init__(self, state, code):
        self.state, self.code = state, code
        super().__init__(code)


def sample_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("INVALID_SAMPLE_ID")
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".chapter4-", delete=False) as handle:
            temp = Path(handle.name)
            os.chmod(temp, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def artifact_path(root, module, sid):
    if module not in MODULES:
        raise ValueError("INVALID_MODULE")
    return Path(root) / "profiles" / module / (sample_name(sid) + ".json")


def envelope(module, sid, state="not_run", reason="NOT_RUN", **extra):
    return {"schema_version": VERSION, "sample_id": sample_name(sid), "module": module,
            "status": state, "reason_code": reason,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strains" if module == "strains" else "markers": [], **extra}


def load_chapter4_inputs(sid, root, *, include_missing=True):
    """Reject mismatched/invalid artifacts; never turn absent/failed runs into negatives."""
    sid = sample_name(sid)
    root = Path(root).resolve()
    result = {}
    for module in MODULES:
        path = artifact_path(root, module, sid)
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError("OUTSIDE_OUTPUT_ROOT")
            if not path.is_file():
                if include_missing:
                    result[module] = envelope(module, sid)
                continue
            if path.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("RESULT_TOO_LARGE")
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            rows_key = "strains" if module == "strains" else "markers"
            if (not isinstance(value, dict) or value.get("sample_id") != sid
                    or value.get("module") != module or value.get("schema_version") != VERSION
                    or value.get("status") not in STATES
                    or not isinstance(value.get(rows_key), list)
                    or any(not isinstance(row, dict) for row in value[rows_key])):
                raise ValueError("RESULT_CONTRACT_MISMATCH")
            if value["status"] != "completed":
                value[rows_key] = []
            # Explicit output schema: arbitrary configuration and nested credentials never enter reports.
            module_fields = {"schema_version", "sample_id", "module", "status", "reason_code",
                             "generated_at", "method", "database_version", "database_sha256",
                             "input_fingerprint", "source_files", "summary", "thresholds", rows_key}
            row_fields = {"species", "name", "analysis_level", "result", "lineage", "strain",
                          "evidence_status", "confidence", "gene", "marker", "category", "detected",
                          "detection_status", "reads", "read_count", "coverage", "breadth", "identity",
                          "sequence_support", "reference_aliases", "marker_count", "callable_bases",
                          "polymorphic_sites", "sequence_link_target", "sequence_link_supported",
                          "link_evidence", "host"}
            safe = {k: v for k, v in value.items() if k in module_fields and k != rows_key}
            safe[rows_key] = [{k: v for k, v in row.items() if k in row_fields and
                              (v is None or isinstance(v, (str, bool, int, float)) or
                               k == "reference_aliases" and isinstance(v, list) and
                               all(isinstance(a, str) for a in v))} for row in value[rows_key]]
            # Provenance and numeric summaries are produced by this module, not free-form supplied config.
            allowed_numeric = {
                "summary": {"processed_reads", "rejected_mappings", "screened_reference_groups",
                            "detected_groups", "subthreshold_groups", "thresholds_clinically_validated",
                            "reconstructed_markers", "observed_clades", "supported_clades",
                            "reference_comparison_performed"},
                "thresholds": {"min_reads", "min_breadth_pct", "min_identity_pct", "min_mapq",
                               "min_markers", "min_marker_breadth_pct", "min_reads_aligning",
                               "min_base_coverage", "min_base_quality", "min_mapping_quality"},
            }
            for key in ("summary", "thresholds"):
                if key in safe:
                    safe[key] = {k: v for k, v in safe[key].items()
                                 if k in allowed_numeric[key] and
                                 (isinstance(v, bool) or isinstance(v, (int, float)) and math.isfinite(v))}
            safe["source_files"] = [str(path)]
            result[module] = safe
        except FileNotFoundError:
            if include_missing:
                result[module] = envelope(module, sid)
        except PermissionError:
            result[module] = envelope(module, sid, "missing_input", "RESULT_NOT_READABLE")
        except (OSError, ValueError, TypeError, AttributeError):
            result[module] = envelope(module, sid, "invalid_result", "RESULT_CONTRACT_MISMATCH")
    return result


def merge_chapter4_inputs(inputs, analysis):
    """A persisted, validated artifact outranks stale analysis JSON, including failed reruns."""
    for module in MODULES:
        fresh = inputs.get(module)
        previous = analysis.get(module)
        if isinstance(fresh, dict) and fresh.get("schema_version") == VERSION and fresh.get("status") != "not_run":
            continue
        if isinstance(previous, (dict, list)):
            inputs[module] = previous
    return inputs


def open_text(path):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="ascii")
    if path.suffix == ".bz2":
        return bz2.open(path, "rt", encoding="ascii")
    return path.open(encoding="ascii")


def open_binary(path):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    if path.suffix == ".bz2":
        return bz2.open(path, "rb")
    return path.open("rb")


def fingerprint_fastq(path):
    path = Path(path)
    digest = hashlib.sha256()
    count = 0
    try:
        with open_text(path) as handle:
            while True:
                header = handle.readline()
                if not header:
                    break
                seq, plus, quality = handle.readline(), handle.readline(), handle.readline()
                seq, quality = seq.rstrip("\r\n"), quality.rstrip("\r\n")
                if (not header.startswith("@") or not plus.startswith("+") or not seq
                        or len(seq) != len(quality) or not re.fullmatch("[ACGTNacgtn]+", seq)
                        or any(not 33 <= ord(c) <= 126 for c in quality)):
                    raise AnalysisError("missing_input", "INVALID_FASTQ")
                digest.update((header + seq + "\n" + plus + quality + "\n").encode("ascii"))
                count += 1
    except (OSError, EOFError, UnicodeError) as exc:
        raise AnalysisError("missing_input", "FASTQ_NOT_READABLE") from exc
    if not count:
        raise AnalysisError("missing_input", "EMPTY_FASTQ")
    return {"sha256": digest.hexdigest(), "reads": count}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fasta_catalog(path):
    """Deduplicate identical reference sequences so equivalent aliases cannot create false ambiguity."""
    entries, ids, sequences = {}, set(), {}
    header, parts = None, []
    def add():
        if header is None:
            return
        original_id = header.split()[0]
        sequence = "".join(parts).upper()
        if original_id in ids or not sequence or not re.fullmatch("[ACGTRYSWKMBDHVN]+", sequence):
            raise AnalysisError("missing_database", "INVALID_VFDB_FASTA")
        ids.add(original_id)
        digest = hashlib.sha256(sequence.encode()).hexdigest()
        vfg = re.match(r"VFG\d+", original_id)
        label = vfg.group() if vfg else original_id
        if digest in sequences:
            entries[sequences[digest]]["aliases"].append(label)
        else:
            key = "vf_" + str(len(entries) + 1)
            sequences[digest] = key
            entries[key] = {"gene": label, "aliases": [label], "sequence": sequence, "length": len(sequence)}
    try:
        with open_binary(path) as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                # Descriptions can contain Unicode in the official database. They are
                # not sequence data; identifiers and nucleotide lines stay strict ASCII.
                if raw_line.startswith(b">"):
                    first = raw_line[1:].split(maxsplit=1)
                    line = ">" + (first[0].decode("ascii") if first else "")
                else:
                    line = raw_line.decode("ascii")
                line = line.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    add()
                    header, parts = line[1:], []
                    if not header:
                        raise AnalysisError("missing_database", "INVALID_VFDB_FASTA")
                else:
                    if header is None:
                        raise AnalysisError("missing_database", "INVALID_VFDB_FASTA")
                    parts.append(line)
            add()
    except (OSError, EOFError, UnicodeError) as exc:
        raise AnalysisError("missing_database", "VFDB_NOT_READABLE") from exc
    if not entries:
        raise AnalysisError("missing_database", "EMPTY_VFDB_FASTA")
    return entries


def summarize_vf_sam(path, catalog, *, expected_reads=None, min_reads=3,
                     min_breadth=80.0, min_identity=90.0, min_mapq=20):
    """Summarize unique primary, high-quality mappings; deleted/skipped bases never add coverage."""
    evidence = defaultdict(lambda: {"reads": 0, "events": Counter(), "matches": 0, "columns": 0})
    primary, rejected, lengths = 0, 0, {}
    with open_text(path) as handle:
        for line in handle:
            if line.startswith("@SQ\t"):
                fields = dict(x.split(":", 1) for x in line.rstrip().split("\t")[1:] if ":" in x)
                if fields.get("SN") not in catalog or int(fields.get("LN", 0)) != catalog[fields["SN"]]["length"]:
                    raise AnalysisError("failed", "SAM_REFERENCE_MISMATCH")
                lengths[fields["SN"]] = int(fields["LN"])
                continue
            if line.startswith("@"):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 11:
                raise AnalysisError("failed", "INVALID_SAM")
            try:
                flag, pos, mapq = int(fields[1]), int(fields[3]) - 1, int(fields[4])
            except ValueError as exc:
                raise AnalysisError("failed", "INVALID_SAM") from exc
            if flag & (0x100 | 0x800):
                continue
            primary += 1
            if flag & 0x4:
                continue
            if flag & (0x200 | 0x400) or mapq < min_mapq or mapq == 255:
                rejected += 1
                continue
            target = fields[2]
            if target not in catalog or target not in lengths or pos < 0:
                raise AnalysisError("failed", "SAM_REFERENCE_MISMATCH")
            operations = re.findall(r"(\d+)([MIDNSHP=X])", fields[5])
            if not operations or "".join(n + op for n, op in operations) != fields[5]:
                raise AnalysisError("failed", "INVALID_CIGAR")
            operations = [(int(n), op) for n, op in operations]
            if any(n <= 0 for n, _ in operations):
                raise AnalysisError("failed", "INVALID_CIGAR")
            query_length = sum(n for n, op in operations if op in "MIS=X")
            if fields[9] == "*" or query_length != len(fields[9]):
                raise AnalysisError("failed", "INVALID_CIGAR")
            columns = sum(n for n, op in operations if op in "MID=X")
            nm_tags = [v[5:] for v in fields[11:] if v.startswith("NM:i:")]
            if len(nm_tags) != 1 or not nm_tags[0].isdigit() or not columns:
                rejected += 1
                continue
            edits = int(nm_tags[0])
            if edits > columns:
                raise AnalysisError("failed", "INVALID_SAM")
            identity = 100.0 * (columns - edits) / columns
            cursor, intervals = pos, []
            for n, op in operations:
                if op in "M=X":
                    intervals.append((cursor, cursor + n))
                    cursor += n
                elif op in "DN":
                    cursor += n
            if cursor > catalog[target]["length"]:
                raise AnalysisError("failed", "INVALID_CIGAR")
            if identity < min_identity:
                rejected += 1
                continue
            row = evidence[target]
            row["reads"] += 1
            row["matches"] += columns - edits
            row["columns"] += columns
            for start, stop in intervals:
                row["events"][start] += 1
                row["events"][stop] -= 1
    if not primary or expected_reads is not None and primary != expected_reads:
        raise AnalysisError("failed", "SAM_READ_COUNT_MISMATCH")
    markers, candidates = [], []
    for key, ev in evidence.items():
        depth, last, covered, depth_sum = 0, 0, 0, 0
        for point, delta in sorted(ev["events"].items()):
            if depth:
                covered += point - last
                depth_sum += depth * (point - last)
            depth += delta
            last = point
        length = catalog[key]["length"]
        breadth, mean_depth = covered / length * 100.0, depth_sum / length
        positive = ev["reads"] >= min_reads and breadth >= min_breadth
        row = {"gene": catalog[key]["gene"], "reference_aliases": catalog[key]["aliases"],
               "category": "VFDB core 参考序列", "detected": positive,
               "detection_status": "detected" if positive else "insufficient_evidence",
               "read_count": ev["reads"], "breadth": round(breadth, 4),
               "coverage": round(mean_depth, 4), "identity": round(ev["matches"] / ev["columns"] * 100, 4),
               "sequence_support": f"reads={ev['reads']}；覆盖广度={breadth:.2f}%；平均深度={mean_depth:.2f}×；身份率={ev['matches'] / ev['columns'] * 100:.2f}%",
               "sequence_link_target": "host", "sequence_link_supported": False}
        (markers if positive else candidates).append(row)
    markers.sort(key=lambda v: (-v["read_count"], v["gene"]))
    return {"markers": markers, "candidates": candidates,
            "summary": {"processed_reads": primary, "rejected_mappings": rejected,
                        "screened_reference_groups": len(catalog), "detected_groups": len(markers),
                        "subthreshold_groups": len(candidates), "thresholds_clinically_validated": False}}


class PrimitiveUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise ValueError("NON_PRIMITIVE_DATABASE_PICKLE")


def marker_metadata(path):
    with bz2.open(path, "rb") as handle:
        data = PrimitiveUnpickler(handle).load()
    if not isinstance(data, dict) or not isinstance(data.get("markers"), dict):
        raise AnalysisError("missing_database", "INVALID_MARKER_DATABASE")
    species = {}
    for lineage in data.get("taxonomy", {}):
        components = str(lineage).split("|")
        names = [v[3:].replace("_", " ") for v in components if v.startswith("s__")]
        if names:
            species[components[-1]] = names[-1]
    markers = {}
    for key, value in data["markers"].items():
        if isinstance(value, dict) and isinstance(value.get("clade"), str):
            markers[key] = value["clade"]
    return markers, species


def summarize_consensus(path, metadata, *, min_markers=20):
    with open_text(path) as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("consensus_markers"), list):
        raise AnalysisError("failed", "UNSUPPORTED_CONSENSUS_FORMAT")
    if data.get("database_name") != Path(metadata).stem:
        raise AnalysisError("failed", "CONSENSUS_DATABASE_MISMATCH")
    marker_clades, species = marker_metadata(metadata)
    grouped, seen = defaultdict(list), set()
    for marker in data["consensus_markers"]:
        if not isinstance(marker, dict):
            raise AnalysisError("failed", "INVALID_CONSENSUS_MARKER")
        name = marker.get('marker', marker.get('name'))
        sequence = marker.get('sequence')
        if 'marker' in marker and 'name' in marker and marker['marker'] != marker['name']:
            raise AnalysisError('failed', 'INVALID_CONSENSUS_MARKER')
        if not isinstance(name, str) or name not in marker_clades or name in seen or not isinstance(sequence, str) or not re.fullmatch(r"[ACGTNacgtn*\-]+", sequence):
            raise AnalysisError("failed", "INVALID_CONSENSUS_MARKER")
        seen.add(name)
        grouped[marker_clades[name]].append(sequence.upper())
    rows = []
    for clade, sequences in sorted(grouped.items()):
        bases = sum(sum(seq.count(base) for base in "ACGT") for seq in sequences)
        polymorphic = sum(seq.count("*") for seq in sequences)
        if len(sequences) < min_markers or not bases:
            continue
        rows.append({"species": species.get(clade, clade), "analysis_level": "菌株 marker 共识",
                     "result": f"重建 {len(sequences)} 个 marker，共 {bases} 个可判定位点；未进行参考菌株命名或 MLST 分型",
                     "evidence_status": "共识序列支持；具体菌株身份未确定", "marker_count": len(sequences),
                     "callable_bases": bases, "polymorphic_sites": polymorphic})
    return {"strains": rows, "summary": {"reconstructed_markers": len(seen),
            "observed_clades": len(grouped), "supported_clades": len(rows), "reference_comparison_performed": False}}


def execute(command, log_dir, label, env, *, timeout=14400):
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with (log_dir / (label + ".stdout")).open("wb") as stdout, (log_dir / (label + ".stderr")).open("wb") as stderr:
            os.chmod(stdout.name, 0o600)
            os.chmod(stderr.name, 0o600)
            done = subprocess.run([str(v) for v in command], stdout=stdout, stderr=stderr,
                                  env=env, timeout=timeout, check=False)
        if done.returncode:
            raise AnalysisError("failed", "TOOL_EXIT_NONZERO")
    except FileNotFoundError as exc:
        raise AnalysisError("missing_tool", "EXECUTABLE_NOT_FOUND") from exc
    except subprocess.TimeoutExpired as exc:
        raise AnalysisError("failed", "TOOL_TIMEOUT") from exc


@contextmanager
def lock_file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        os.chmod(path, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError) as exc:
            raise AnalysisError("running", "MODULE_ALREADY_RUNNING") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def executable(env_bin, name):
    path = Path(env_bin) / name
    if not path.is_file() or not os.access(path, os.X_OK):
        raise AnalysisError("missing_tool", "EXECUTABLE_NOT_FOUND")
    return path


def settings_from_env(root, sid, *, reads=None, db_root=None, env_bin=None, threads=4):
    from wgs_fmt_platform.paths import PROJECT_ROOT
    resource = Path(os.environ.get("WGS_FMT_RESOURCE_ROOT") or PROJECT_ROOT / "var")
    db = Path(db_root or os.environ.get("DB_ROOT") or resource / "databases")
    if not db.is_dir() and (PROJECT_ROOT / "fmt-databases").is_dir():
        db = PROJECT_ROOT / "fmt-databases"
    tax = Path(env_bin or os.environ.get("WGS_CHAPTER4_TAX_BIN") or resource / "runtime/envs/fmt-tax/bin")
    sid = sample_name(sid)
    if reads is None:
        candidates = [Path(root) / directory / (sid + suffix)
                      for directory in ("clean_merged", "clean_reads", "clean")
                      for suffix in (".dehosted.fastq.gz", ".fastq.gz", ".clean.fastq.gz", "_clean.fastq.gz")]
        available = [p for p in candidates if p.is_file()]
        if len(available) > 1:
            raise ValueError("AMBIGUOUS_CLEAN_READS_REQUIRES_EXPLICIT_PATH")
        reads = available[0] if available else candidates[0]
    return {"root": Path(root), "sid": sid,
            "reads": Path(reads),
            "db_root": db, "env_bin": tax, "threads": max(1, min(int(threads), 32))}


def run_module(module, settings, *, force=False, vfdb=None, marker_db=None,
               min_reads=3, min_breadth=80.0, min_identity=90.0, min_markers=20):
    root, sid = settings["root"], settings["sid"]
    output = artifact_path(root, module, sid)
    log_dir = root / "chapter4" / sid / module
    try:
        with lock_file(log_dir / ".lock"):
            try:
                input_info = fingerprint_fastq(settings["reads"])
                db = Path(vfdb or os.environ.get("WGS_VFDB_FASTA") or settings["db_root"] / "vfdb/VFDB_setA_nt.fas.gz") if module == "virulence" else Path(marker_db or os.environ.get("WGS_CHAPTER4_MARKER_DB") or settings["db_root"] / "metaphlan4/mpa_vJan25_CHOCOPhlAnSGB_202503.pkl")
                if not db.is_file():
                    raise AnalysisError("missing_database", "VFDB_NOT_CONFIGURED" if module == "virulence" else "MARKER_DATABASE_NOT_CONFIGURED")
                database_hash = sha256_file(db)
                thresholds = {"min_reads": min_reads, "min_breadth_pct": min_breadth, "min_identity_pct": min_identity, "min_mapq": 20} if module == "virulence" else {
                    "min_markers": min_markers, "min_marker_breadth_pct": 80,
                    "min_reads_aligning": 8, "min_base_coverage": 2,
                    "min_base_quality": 30, "min_mapping_quality": 10}
                if min_reads < 1 or not 0 < min_breadth <= 100 or not 0 < min_identity <= 100 or min_markers < 1:
                    raise ValueError("INVALID_THRESHOLDS")
                tool_names = ["bowtie2", "bowtie2-build"] if module == "virulence" else ["metaphlan", "sample2markers.py", "samtools"]
                tools = {name: executable(settings["env_bin"], name) for name in tool_names}
                tool_identity = {name: [str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns] for name, p in tools.items()}
                fingerprint = hashlib.sha256(json.dumps([VERSION, sid, input_info, database_hash, thresholds, tool_identity], sort_keys=True).encode()).hexdigest()
                old = load_chapter4_inputs(sid, root, include_missing=False).get(module, {})
                if not force and old.get("status") == "completed" and old.get("input_fingerprint") == fingerprint:
                    return old
                base = {"input_fingerprint": fingerprint, "database_version": db.name,
                        "database_sha256": database_hash, "thresholds": thresholds,
                        "method": "VFDB-core Bowtie2 nucleotide screening" if module == "virulence" else "MetaPhlAn sample2markers consensus"}
                atomic_json(output, envelope(module, sid, "running", "RUNNING", **base))
                env = {**os.environ, "PATH": str(settings["env_bin"]) + os.pathsep + os.environ.get("PATH", "")}
                # Per-run directory avoids consuming a partial or stale subprocess output after retry.
                with tempfile.TemporaryDirectory(prefix="run-", dir=log_dir) as run_name:
                    run = Path(run_name)
                    if module == "virulence":
                        catalog = fasta_catalog(db)
                        fasta, index, sam = run / "references.fna", run / "vfdb", run / "alignments.sam"
                        with fasta.open("w") as handle:
                            for key, entry in catalog.items():
                                handle.write(">" + key + "\n" + entry["sequence"] + "\n")
                        execute([tools["bowtie2-build"], "--threads", settings["threads"], fasta, index], log_dir, "vfdb-index", env)
                        # Default best-alignment reporting retains Bowtie2's calibrated MAPQ.
                        # Its -k mode can use MAPQ=255, which correctly fails our unknown-quality filter.
                        execute([tools["bowtie2"], "--very-sensitive", "--end-to-end", "-p", settings["threads"],
                                 "-x", index, "-U", settings["reads"], "-S", sam], log_dir, "vfdb-map", env)
                        result = summarize_vf_sam(sam, catalog, expected_reads=input_info["reads"], min_reads=min_reads,
                                                 min_breadth=min_breadth, min_identity=min_identity)
                    else:
                        sam, profile, mapout, consensus = run / "sample.sam", run / "profile.tsv", run / "mapout.bz2", run / "consensus"
                        consensus.mkdir()
                        # CLI compatibility is determined from the installed executable, never guessed from tutorial age.
                        help_result = subprocess.run([str(tools["metaphlan"]), "--help"], capture_output=True, env=env, timeout=30)
                        help_text = (help_result.stdout + help_result.stderr).decode(errors="replace")
                        if help_result.returncode or "--samout" not in help_text:
                            raise AnalysisError("missing_tool", "UNSUPPORTED_METAPHLAN_CLI")
                        db_flag = "--db_dir" if "--db_dir" in help_text else "--bowtie2db"
                        map_flag = "--mapout" if "--mapout" in help_text else "--bowtie2out"
                        execute([tools["metaphlan"], settings["reads"], "--input_type", "fastq", "--samout", sam,
                                 map_flag, mapout, "-o", profile, db_flag, db.parent, "--index", db.stem,
                                 "--nproc", settings["threads"], "--offline"], log_dir, "marker-map", env)
                        execute([tools["sample2markers.py"], "-i", sam, "-f", "sam", "-d", db,
                                 "-o", consensus, "-n", settings["threads"], "--breadth_threshold", 80,
                                 "--min_reads_aligning", 8, "--min_base_coverage", 2,
                                 "--min_base_quality", 30, "--min_mapping_quality", 10], log_dir, "marker-consensus", env)
                        files = list(consensus.glob("*.json.bz2"))
                        if len(files) != 1:
                            raise AnalysisError("failed", "UNSUPPORTED_CONSENSUS_FORMAT")
                        result = summarize_consensus(files[0], db, min_markers=min_markers)
                        target = log_dir / "consensus.json.bz2"
                        shutil.copyfile(files[0], target)
                        os.chmod(target, 0o600)
                state = "insufficient_coverage" if module == "strains" and not result["strains"] else "completed"
                value = envelope(module, sid, state, "INSUFFICIENT_MARKER_SUPPORT" if state != "completed" else "COMPLETED", **base, **result)
            except AnalysisError as exc:
                value = envelope(module, sid, exc.state, exc.code)
            except PermissionError:
                value = envelope(module, sid, "missing_input", "INPUT_NOT_READABLE")
            except (OSError, ValueError, TypeError, KeyError, EOFError, pickle.UnpicklingError, subprocess.TimeoutExpired):
                value = envelope(module, sid, "failed", "ANALYSIS_VALIDATION_FAILED")
            atomic_json(output, value)
            return value
    except AnalysisError as exc:
        # Do not overwrite the result of a currently running process.
        return envelope(module, sid, exc.state, exc.code)


def run_sample(settings, **kwargs):
    return {module: run_module(module, settings, **kwargs) for module in MODULES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reads", type=Path)
    parser.add_argument("--db-root", type=Path)
    parser.add_argument("--tax-bin", type=Path)
    parser.add_argument("--vfdb", type=Path)
    parser.add_argument("--marker-db", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--min-vf-reads", type=int, default=3)
    parser.add_argument("--min-vf-breadth", type=float, default=80.0)
    parser.add_argument("--min-vf-identity", type=float, default=90.0)
    parser.add_argument("--min-strain-markers", type=int, default=20)
    args = parser.parse_args()
    try:
        settings = settings_from_env(args.output_root, args.sample_id, reads=args.reads,
                                     db_root=args.db_root, env_bin=args.tax_bin, threads=args.threads)
        result = run_sample(settings, force=args.force, vfdb=args.vfdb, marker_db=args.marker_db,
                            min_reads=args.min_vf_reads, min_breadth=args.min_vf_breadth,
                            min_identity=args.min_vf_identity, min_markers=args.min_strain_markers)
        print(json.dumps({key: {"status": value["status"], "reason_code": value["reason_code"]}
                          for key, value in result.items()}))
        return 0 if all(v["status"] in {"completed", "insufficient_coverage"} for v in result.values()) else 2
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "reason_code": "OUTPUT_OR_CONFIGURATION_NOT_ACCESSIBLE"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
