import copy
import json

from wgs_agent.reporting.document import build_document
from wgs_agent.reporting.overview_chart import overview_items, render_overview_figure, translate_overview_taxa
from test_mho_reference import cohort, refresh, rewrite_manifest


def build(rows):
    return build_document("REFERENCE_TEST", {"species_list": rows}, {}, {}, {}, {}, {}, {}, {})


def row(name="Escherichia coli", **extra):
    return {"species": name, "abundance": 8.5, "reference_median": 0, "unit": "%",
            "p5": 0, "p95": .86, "status": "high", "n_reference": 103, "n_detected": 41,
            "reference_detected_median": .02711, **extra}


def test_true_zero_median_kept_with_nonzero_interval_and_prevalence(tmp_path):
    doc = build([row()])
    evidence = copy.deepcopy(doc["evidence"])
    item = overview_items(doc)[0]
    assert item["reference_median"] == 0 and item["p95"] == .86
    assert item["n_zero"] == 62 and item["n_detected"] == 41
    assert item["reference_detected_median"] == .02711
    assert item["reference_interval_available"]
    render_overview_figure(doc, tmp_path)
    assert doc["overview_chart"]["reference_representation"] == "p5_p95_band_with_overall_median_marker"
    assert doc["evidence"] == evidence


def test_stable_ids_retry_only_rejected_names(monkeypatch):
    doc = build([row("mediterraneibacter gnavus")])
    calls = []
    def request(config, messages, schema, post):
        items = json.loads(messages[1]["content"])["items"]
        calls.append(items)
        assert all(set(item) == {"id", "name"} for item in items)
        if len(calls) == 1:
            return json.dumps({"items": [{"id": "Mediterraneibacter gnavus", "label": "活泼地中海杆菌"}]})
        return json.dumps({"items": [{"id": item["id"], "label": "活泼地中海杆菌"} for item in items]})
    monkeypatch.setattr("wgs_agent.reporting.narrative._request", request)
    translate_overview_taxa(doc, {"model": "test"}, post=object())
    audit = doc["audit"]["overview_taxon_translation"]
    assert audit["attempts"] == 2 and audit["rejected"]["bad_id"] == 1
    assert audit["untranslated"] == 0 and audit["model_translated"] == 1
    assert calls[0][0]["id"] == "t1"
    assert overview_items(doc)[0]["label"] == "活泼地中海杆菌"


def test_lineage_rank_used_without_inventing_a_species(monkeypatch):
    lineage1 = "k__Bacteria|p__Firmicutes|c__Clostridia|o__Eubacteriales|f__Acutalibacteraceae|g__GGB38744|s__GGB38744_SGB14842"
    lineage2 = "k__Bacteria|p__Firmicutes|c__CFGB3054|o__OFGB3054|f__FGB3054|g__GGB9715|s__GGB9715_SGB15266"
    doc = build([row("GGB38744 SGB14842", lineage=lineage1), row("GGB9715 SGB15266", lineage=lineage2)])
    evidence = copy.deepcopy(doc["evidence"])
    wanted = {"Acutalibacteraceae": "尖杆菌科", "Firmicutes": "厚壁菌门"}
    def request(config, messages, schema, post):
        items = json.loads(messages[1]["content"])["items"]
        assert {item["name"] for item in items}.issubset(wanted)
        return json.dumps({"items": [{"id": item["id"], "label": wanted[item["name"]]} for item in items]})
    monkeypatch.setattr("wgs_agent.reporting.narrative._request", request)
    translate_overview_taxa(doc, {"model": "test"}, post=object())
    labels = doc["overview_taxon_labels"]
    assert labels["ggb38744 sgb14842"]["label"] == "尖杆菌科未定种"
    assert labels["ggb38744 sgb14842"]["rank"] == "family"
    assert labels["ggb9715 sgb15266"]["label"] == "厚壁菌门未定种"
    assert labels["ggb9715 sgb15266"]["rank"] == "phylum"
    assert doc["evidence"] == evidence


def test_service_unavailable_uses_clear_curated_name_instead_of_placeholder():
    doc = build([row("mediterraneibacter gnavus")])
    translate_overview_taxa(doc, None)
    assert overview_items(doc)[0]["label"] == "活泼地中海杆菌"
    assert doc["audit"]["overview_taxon_translation"]["untranslated"] == 0


def test_primary_lineage_can_describe_separate_healthy_profile():
    name = "GGB9715 SGB15266"
    primary = row(name, lineage="k__Bacteria|p__Firmicutes|c__CFGB3054|o__OFGB3054|f__FGB3054|g__GGB9715|s__GGB9715_SGB15266")
    doc = build_document("REFERENCE_TEST", {"species_list": [primary]}, {}, {}, {}, {}, {}, {}, {},
                         context={"health_inputs": {"healthy_comparison": {"species": [row(name)]}}})
    translate_overview_taxa(doc, None)
    item = overview_items(doc)[0]
    assert item["label"] == "厚壁菌门未定种" and item["evidence_id"].startswith("HS")
    assert item["source"] == "1.4"


def test_supplemental_median_is_not_population_median(cohort):
    base, _, data = cohort
    (base / "species_abundance.tsv").write_text(
        "sample_id\ts__A\ts__B\ts__Rare\n" + "".join(
            f"D{i}\t{10+i if i<13 else 0}\t{90-i if i<13 else 100}\t0\n" for i in range(35)))
    rewrite_manifest(base)
    result = refresh(data)
    a = next(row for row in result["healthy_comparison"]["species"] if row["species"] == "a")
    assert a["reference_median"] == 0 and a["reference_detected_median"] == 16
    assert a["n_detected"] == 13 and a["n_zero"] == 22
    assert a["taxonomy_lineage"] == "k__Bacteria|s__A"
    rare = next(row for row in result["healthy_comparison"]["species"] if row["species"] == "rare")
    assert rare["reference_detected_median"] is None and rare["n_zero"] == 35
