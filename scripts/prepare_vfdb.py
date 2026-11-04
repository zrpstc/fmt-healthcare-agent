"""Download and validate data from the official VFDB core nucleotide endpoint."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import urllib.request

from wgs_agent.pipeline.strain_virulence import atomic_json, fasta_catalog, sha256_file

URL = "https://www.mgc.ac.cn/VFs/Down/VFDB_setA_nt.fas.gz"


def prepare(destination):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Existing databases are never silently replaced by a moving upstream release.
    if destination.exists():
        fasta_catalog(destination)
        return destination
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".fas.gz", delete=False) as handle:
            temp = Path(handle.name)
            os.chmod(temp, 0o600)
            request = urllib.request.Request(URL, headers={
                "User-Agent": "Mozilla/5.0 (compatible; fmt-healthcare-agent/1.0)",
                "Referer": "https://www.mgc.ac.cn/VFs/download.htm"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.geturl() != URL:
                    raise ValueError("UNEXPECTED_DATABASE_REDIRECT")
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > 100 * 1024 * 1024:
                        raise ValueError("DATABASE_DOWNLOAD_TOO_LARGE")
                    handle.write(block)
            handle.flush()
            os.fsync(handle.fileno())
        catalog = fasta_catalog(temp)
        provenance = {"schema_version": "vfdb-core-source-v1", "source_url": URL,
                      "downloaded_at": datetime.now(timezone.utc).isoformat(),
                      "sha256": sha256_file(temp), "reference_groups": len(catalog),
                      "reference_aliases": sum(len(v["aliases"]) for v in catalog.values())}
        # Atomic create prevents racing preparation jobs from overwriting each other.
        os.link(temp, destination)
        atomic_json(destination.with_name(destination.name + ".source.json"), provenance)
        return destination
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.output)
        print("VFDB_CORE_READY")
        return 0
    except Exception:
        # Do not echo remote response bodies, environment settings or raw errors.
        print("VFDB_CORE_PREPARATION_FAILED")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
