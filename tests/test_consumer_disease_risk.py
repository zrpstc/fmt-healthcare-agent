from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from wgs_agent.consumer_web.builder import build_report
from wgs_agent.reporting import disease_risk
from wgs_agent.reporting.cohort_models import Cohort

FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"


def synthetic_risk(seed: int = 7, n_healthy: int = 400, n_t2d: int = 60) -> dict:
    """Train on a synthetic population using the real shipped MR weights; score one sample."""
    weights = disease_risk.load_weights()
    names = sorted({disease_risk.GTDB_TO_MPA.get(disease_risk.gtdb_name(t["name"]), disease_risk.gtdb_name(t["name"]))
                    for d in weights["diseases"] for t in d["traits"] if t["kind"] == "species"})
    names = [n for n in names if " " in n and not any(ch.isdigit() for ch in n)][:120]
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    for i in range(n_healthy + n_t2d):
        base = rng.lognormal(0.0, 1.0, len(names))
        base[rng.random(len(names)) < 0.3] = 0
        if i >= n_healthy:
            base[: len(names) // 4] *= 4
        rows.append(100 * base / base.sum())
        labels.append({"sample_id": str(i), "study_id": f"st{i % 4}", "subject_id": str(i),
                       "group": "T2D" if i >= n_healthy else "healthy", "age": ""})
    cohort = Cohort(species=names, values=np.array(rows), genus_of={n: n.split()[0] for n in names}, labels=labels)
    model = disease_risk.train(cohort, weights)
    profile = dict(zip(names, rows[n_healthy + 1]))  # a T2D-like profile
    return {"audit": {"status": "available", "n_healthy": n_healthy},
            "diseases": disease_risk.score_profile(model, profile)}


def _build(monkeypatch, risk: dict | None) -> dict:
    monkeypatch.setattr("wgs_agent.consumer_web.sections.virulence.load_vfdb_index", lambda: {})
    document = json.loads((FIXTURES / "sample_report.json").read_text(encoding="utf-8"))
    if risk is not None:
        document["template_inputs"]["disease_risk"] = risk
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        (tmp / "CONSUMER_TEST_report.json").write_text(json.dumps(document), encoding="utf-8")
        shutil.copyfile(FIXTURES / "sample_analysis.json", tmp / "CONSUMER_TEST_analysis.json")
        return build_report("CONSUMER_TEST", results_dir=tmp, refresh=True)


def test_disease_risk_section_with_distributions(monkeypatch):
    risk = synthetic_risk()
    report = _build(monkeypatch, risk)
    section = next(s for s in report["sections"] if s["id"] == "disease-risk")
    assert section["subsections"][0]["id"] == "disease-risk-overview"
    blocks = [b for sub in section["subsections"] for b in sub["blocks"] if b["type"] == "risk_distribution"]
    assert blocks, "featured diseases get a distribution chart"
    t2d = next(b for b in blocks if b["title"].startswith("2型糖尿病"))
    assert t2d["patients"] and len(t2d["patients"]) == len(t2d["grid"]) == len(t2d["healthy"])
    assert t2d["grid"][0] <= t2d["you"] <= t2d["grid"][-1]
    assert [band["key"] for band in t2d["bands"]] == ["low", "medium", "high"]
    assert "健康成人" in t2d["text"] and "患者" in t2d["text"]
    # Tobacco use is an FinnGen endpoint but not a disease.
    titles = {row[0] for sub in section["subsections"] for b in sub["blocks"] if b["type"] == "table" for row in b["rows"]}
    assert "烟草使用" not in titles
    assessments = {a["id"]: a for a in report["summary"]["assessments"]}
    assert assessments["disease_risk"]["anchor"] == "#disease-risk"
    methods = [sub for s in report["sections"] if s["id"] == "learn" for sub in s["subsections"]]
    assert any(sub["title"] == "疾病风险评分" for sub in methods)
    assert not any(o["item"] == "疾病风险模型分数" for o in report["omissions"])


def test_disease_risk_hidden_without_bundle(monkeypatch):
    report = _build(monkeypatch, None)
    assert not any(s["id"] == "disease-risk" for s in report["sections"])
    assert any(o["section"] == "disease-risk" for o in report["omissions"])
    assert "disease_risk" not in {a["id"] for a in report["summary"]["assessments"]}
