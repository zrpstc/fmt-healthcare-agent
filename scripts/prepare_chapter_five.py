"""Build data-only, versioned chapter 5 references from official upstream data.

Requires a shallow resfinder_db checkout and a SHA256-verified MGEdb 1.1.1
wheel. No downloaded package code or installation scripts are executed.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


def fasta(lines):
    name, parts = None, []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                yield name, "".join(parts).upper()
            name, parts = line[1:].split()[0], []
        else:
            if name is None:
                raise ValueError("FASTA_HEADER_MISSING")
            parts.append(line)
    if name is not None:
        yield name, "".join(parts).upper()


def build(root, module, entries, database, version, scope, provenance):
    from wgs_agent.pipeline.resistome_mge import atomic_json
    destination = root/module
    destination.mkdir(parents=True, exist_ok=True)
    groups = {}
    for seq, row in entries:
        if not re.fullmatch(r"[ACGTRYSWKMBDHVN]+", seq) or len(seq)<50:
            raise ValueError("INVALID_REFERENCE_SEQUENCE")
        seq = re.sub(r"[RYSWKMBDHV]", "N", seq)
        # Exact reverse complements have the same read evidence.
        rev = seq.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]
        seq = min(seq, rev)
        h = hashlib.sha256(seq.encode()).hexdigest()
        if h not in groups:
            groups[h] = {"sequence":seq,"rows":[]}
        groups[h]["rows"].append(row)
    catalog = {}
    fasta_path = destination/"references.fna"
    if (destination/"manifest.json").exists():
        raise ValueError("DATABASE_ALREADY_BUILT_USE_NEW_DIRECTORY")
    with fasta_path.open("x") as handle:
        for i, (_, item) in enumerate(sorted(groups.items()), 1):
            key = "ref"+str(i)
            rows, seq = item["rows"], item["sequence"]
            names = sorted({r["name"] for r in rows})
            row = {"name":" / ".join(names),"length":len(seq),"gene_aliases":names,"database":database,"database_version":version,"reference_scope":scope}
            for field in ("gene", "drug_class", "mechanism", "phenotype_annotation", "element_type", "family"):
                vals = sorted({r[field] for r in rows if r.get(field)})
                if vals:
                    row[field] = " / ".join(vals)
            catalog[key]=row
            handle.write(">"+key+"\n"+seq+"\n")
    digest = hashlib.sha256(fasta_path.read_bytes()).hexdigest()
    atomic_json(destination/"catalog.json", catalog)
    catalog_digest=hashlib.sha256((destination/"catalog.json").read_bytes()).hexdigest()
    atomic_json(destination/"manifest.json", {"database":database,"version":version,"scope":scope,"sha256":digest,"catalog_sha256":catalog_digest,"iupac_policy":"ambiguity_to_N","reference_count":len(catalog),"prepared_at":datetime.now(timezone.utc).isoformat(),"provenance":provenance})
    return {"reference_count":len(catalog),"scope":scope}


def prepare(root, wheel_sha256):
    root = Path(root)
    res = root/"resfinder_db"
    wheel = root/"MGEdb-1.1.1.whl"
    if hashlib.sha256(wheel.read_bytes()).hexdigest()!=wheel_sha256:
        raise ValueError("MGEDB_HASH_MISMATCH")
    revision = subprocess.run(["git","rev-parse","HEAD"],cwd=res,capture_output=True,text=True,check=True).stdout.strip()
    # The source and the gene annotation table are tied to the same Git revision.
    phenotype = {}
    with (res/"phenotypes.txt").open() as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            phenotype[row["Gene_accession no."]] = row
    amr=[]
    for file in sorted(res.glob("*.fsa")):
        if file.name=="all.fsa":
            continue
        for name, seq in fasta(file.read_text().splitlines()):
            ph = phenotype.get(name,{})
            gene = name.rsplit("_",2)[0]
            amr.append((seq,{"name":gene,"gene":gene,"drug_class":ph.get("Class") or file.stem,"mechanism":ph.get("Mechanism of resistance") or "未提供机制注释","phenotype_annotation":ph.get("Phenotype","")}))
    mge=[]
    with zipfile.ZipFile(wheel) as archive:
        records=json.loads(archive.read("mgedb/data/mge_records.json"))
        for header,seq in fasta(archive.read("mgedb/data/sequences.d/mge_records.fna").decode().splitlines()):
            name=header.split("|")[0]
            record=records.get(name,{})
            # Restrict short-read screening to IS and MITE. Whole ICE/Tn/IME
            # sequences carry accessory ARGs and require a contig-level analysis.
            if record.get("type") not in {"is","mite"}:
                continue
            mge.append((seq,{"name":name,"element_type":record["type"],"family":record.get("family") or "未分组"}))
    return {"resistance":build(root,"resistance",amr,"ResFinder",revision,"acquired_ARGs",{"url":"https://bitbucket.org/genomicepidemiology/resfinder_db/","revision":revision}),
            "mobile_elements":build(root,"mobile_elements",mge,"MGEdb","1.1.1","IS_and_MITE_reference_signals",{"url":"https://pypi.org/project/MGEdb/1.1.1/","wheel_sha256":wheel_sha256})}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database-root",type=Path,required=True)
    p.add_argument("--mgedb-sha256",required=True)
    args=p.parse_args()
    print(json.dumps(prepare(args.database_root,args.mgedb_sha256)))

if __name__=="__main__":main()
