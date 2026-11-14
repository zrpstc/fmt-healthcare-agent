import csv
import importlib.util
import json
from pathlib import Path

from wgs_agent.reporting import cmd, reference


def bundle(tmp_path, n=35):
    base = tmp_path/"reference";base.mkdir()
    labels = [{"sample_id": f"Study::S{i}", "original_sample_id": f"S{i}", "subject_id": f"P{i}",
               "study_id": "Study", "phenotype": cmd.PHENOTYPE, "source_runs": f"ERR{10000+i}"}
              for i in range(n)]
    with (base/"metadata.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]), delimiter="\t")
        writer.writeheader();writer.writerows(labels)
    with (base/"species_abundance.tsv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["sample_id", "s__Taxon_a", "s__Taxon_b"])
        writer.writerows([r["sample_id"], 20+i, 80-i] for i,r in enumerate(labels))
    manifest = {"schema_version": cmd.VERSION, "cohort_id": "cMD-test", "cohort_version": "test-v1",
                "source_package": "curatedMetagenomicData", "source_package_version": "3.14.0",
                "source_url": "https://github.com/waldronlab/curatedMetagenomicData",
                "phenotype": cmd.PHENOTYPE, "body_site": "stool", "feature_level": "species",
                "pipeline": cmd.PIPELINE, "normalization": cmd.NORMALIZATION, "unit": "%",
                "complete_species_profiles": True, "minimum_subjects": 30, "stratify_by": [],
                "selection_criteria": {"minimum_age": 18, "disease": "healthy", "study_condition": "control",
                    "antibiotics_current_use": "no", "deduplicate_by": ["study_id", "subject_id"]},
                "files": {name: cmd.digest((base/name).read_bytes()) for name in ("metadata.tsv", "species_abundance.tsv")}}
    (base/"manifest.json").write_text(json.dumps(manifest))
    return base


def target(tmp_path, sid="T", pipeline=None):
    root = tmp_path/"targets";folder = root/sid;folder.mkdir(parents=True)
    pipeline = pipeline or {**cmd.PIPELINE, "profiler_version": "3.0.14"}
    raw = ("#"+pipeline["database_version"]+"\n#clade_name\tNCBI_tax_id\trelative_abundance\n"
           "k__Bacteria|s__Taxon_a\t1\t30\n"
           "k__Bacteria|s__Taxon_b\t2\t70\n").encode()
    (folder/"profile.tsv").write_bytes(raw)
    (folder/"provenance.json").write_text(json.dumps({"sample_id":sid,"pipeline":pipeline,
        "normalization":cmd.NORMALIZATION,"profile_sha256":cmd.digest(raw)}))
    return root


def test_cmd_comparison_excludes_same_subject_and_run(tmp_path, monkeypatch):
    base=bundle(tmp_path);profiles=target(tmp_path)
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR",str(base));monkeypatch.setenv("WGS_CMD_PROFILES_DIR",str(profiles))
    result=cmd.compare("T",{"study_id":"Study","subject_id":"P0","source_runs":"ERR10001"})
    assert result["audit"]["status"]=="available"
    assert result["audit"]["provider"]=="cmd"
    assert result["audit"]["n_subjects"]==33
    assert result["audit"]["exclusions"]["self"]==2
    assert len(result["diversity"])==4
    assert result["species"][0]["generated_by"]==cmd.VERSION
    assert "小版本" in "".join(result["audit"]["limitations"])


def test_cmd_never_uses_jan25_as_compatible_target(tmp_path,monkeypatch):
    base=bundle(tmp_path)
    profiles=target(tmp_path,pipeline={"profiler":"MetaPhlAn","profiler_version":"4.2.4","database_version":"mpa_vJan25_OTHER"})
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR",str(base));monkeypatch.setenv("WGS_CMD_PROFILES_DIR",str(profiles))
    result=cmd.compare("T",{})
    assert result["audit"]["reason"]=="incompatible_pipeline"
    assert not result["species"] and not result["diversity"]


def test_cmd_checksum_failure_and_missing_target_do_not_fall_back(tmp_path,monkeypatch):
    base=bundle(tmp_path)
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR",str(base));monkeypatch.setenv("WGS_CMD_PROFILES_DIR",str(tmp_path/"missing"))
    assert cmd.compare("T",{})["audit"]["reason"]=="target_missing"
    with (base/"species_abundance.tsv").open("a") as handle:handle.write("bad\n")
    assert cmd.compare("T",{})["audit"]["reason"]=="invalid_reference"


def test_cmd_qc_failure_and_minimum_sample_count(tmp_path,monkeypatch):
    base=bundle(tmp_path,n=30);profiles=target(tmp_path)
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR",str(base));monkeypatch.setenv("WGS_CMD_PROFILES_DIR",str(profiles))
    assert cmd.compare("T",{"qc_status":"failed"})["audit"]["reason"]=="target_qc_failed"
    assert cmd.compare("T",{"subject_id":"P0"})["audit"]["reason"]=="insufficient_subjects"


def test_cmd_excludes_original_sample_alias(tmp_path,monkeypatch):
    base=bundle(tmp_path);profiles=target(tmp_path,sid="S0")
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR",str(base));monkeypatch.setenv("WGS_CMD_PROFILES_DIR",str(profiles))
    result=cmd.compare("S0",{})
    assert result["audit"]["n_subjects"]==34
    assert result["audit"]["exclusions"]["self"]==1


def test_refresh_cmd_preserves_primary_values_and_clears_stale_mho(tmp_path,monkeypatch):
    base=bundle(tmp_path);profiles=target(tmp_path)
    monkeypatch.setenv("WGS_HEALTHY_REFERENCE_PROVIDER","cmd")
    monkeypatch.setenv("WGS_CMD_REFERENCE_DIR",str(base));monkeypatch.setenv("WGS_CMD_PROFILES_DIR",str(profiles))
    data={"sample_id":"T","metadata":{},"species":{"species_list":[{"species":"Jan25_species","abundance":99}]},
          "healthy_comparison":{"audit":{"provider":"mho"}}}
    result=reference.refresh_reference_comparisons(data,{})
    assert result["species"]==data["species"]
    assert result["healthy_comparison"]["audit"]["provider"]=="cmd"
    assert data["healthy_comparison"]["audit"]["provider"]=="mho"


def test_cmd_presentation_names_current_population():
    from wgs_agent.reporting import reference_labels
    data={"healthy_comparison":{"audit":{"provider":"cmd","reference_population":cmd.POPULATION}}}
    assert reference_labels.profile(data)=="cMD 独立谱"
    assert reference_labels.title(data)==cmd.POPULATION
    assert "v30" in reference_labels.method(data)
    assert reference_labels.profile({})=="cMD 独立谱"


def test_cmd_large_ordination_has_explicit_deterministic_subset(monkeypatch):
    from wgs_agent.reporting import ordination
    calls=[]
    def calculate(target,matrix,selected,**kwargs):
        calls.append(list(selected))
        return {"status":"available","n_reference":len(selected),"limitations":[]}
    monkeypatch.setattr(ordination,"community_ordination",calculate)
    ids=[f"S{i}" for i in range(3500)]
    first=cmd.community_ordination({}, {}, ids,reference_version="v1")
    second=cmd.community_ordination({}, {}, list(reversed(ids)),reference_version="v1")
    assert first==second
    assert first["n_reference"]==300 and first["n_reference_total"]==3500
    assert calls[0]==calls[1]
    assert first["reference_sampling"]=="deterministic_hash_subset_300"


def test_cmd_builder_selection_rejects_disease_unknown_age_antibiotics_and_pregnancy():
    spec=importlib.util.spec_from_file_location("prepare_cmd_reference",Path(__file__).parents[1]/"scripts/prepare_cmd_reference.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    row={"age":"36","body_site":"stool","disease":"healthy","study_condition":"control",
         "antibiotics_current_use":"no","subject_id":"P1","study_name":"S","sample_id":"A"}
    assert module.eligible(row)
    for key,value in [("age",""),("age","17"),("disease","T2D"),("antibiotics_current_use",""),
                      ("antibiotics_current_use","yes"),("pregnant","yes"),("lactating","yes")]:
        assert not module.eligible({**row,key:value})
