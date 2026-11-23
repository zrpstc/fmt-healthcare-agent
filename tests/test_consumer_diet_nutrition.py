from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.schema import ConsumerReport
from wgs_agent.reporting import diet_nutrition, disease_risk
from wgs_agent.reporting.cohort_models import Cohort

FIXTURES = Path(__file__).parent / "fixtures" / "consumer_web"


def synthetic_diet(seed: int = 11, n_healthy: int = 400, profile_index: int = 3) -> dict:
    """Train on a synthetic population using the real shipped MR weights; score one sample."""
    weights = diet_nutrition.load_weights()
    names = sorted({disease_risk.GTDB_TO_MPA.get(disease_risk.gtdb_name(t["name"]), disease_risk.gtdb_name(t["name"]))
                    for n in weights["nutrients"] for t in n["traits"] if t["kind"] == "species"})
    names = [n for n in names if " " in n and not any(ch.isdigit() for ch in n)]
    rng = np.random.default_rng(seed)
    rows, labels = [], []
    for i in range(n_healthy):
        base = rng.lognormal(0.0, 1.0, len(names))
        base[rng.random(len(names)) < 0.3] = 0
        rows.append(100 * base / base.sum())
        labels.append({"sample_id": str(i), "study_id": f"st{i % 4}", "subject_id": str(i), "group": "healthy", "age": ""})
    cohort = Cohort(species=names, values=np.array(rows), genus_of={n: n.split()[0] for n in names}, labels=labels)
    model = diet_nutrition.train(cohort, weights)
    scored = diet_nutrition.score_profile(model, dict(zip(names, rows[profile_index])))
    return {"audit": {"status": "available", "n_healthy": n_healthy}, **scored}


def _build(monkeypatch, diet: dict | None) -> dict:
    monkeypatch.setattr("wgs_agent.consumer_web.sections.virulence.load_vfdb_index", lambda: {})
    monkeypatch.setenv("WGS_CMD_DIET_NUTRITION_DIR", str(Path(tempfile.gettempdir()) / "no-diet-bundle-here"))
    document = json.loads((FIXTURES / "sample_report.json").read_text(encoding="utf-8"))
    if diet is not None:
        document["template_inputs"]["diet_nutrition"] = diet
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        (tmp / "CONSUMER_TEST_report.json").write_text(json.dumps(document), encoding="utf-8")
        shutil.copyfile(FIXTURES / "sample_analysis.json", tmp / "CONSUMER_TEST_analysis.json")
        return build_report("CONSUMER_TEST", results_dir=tmp, refresh=True)


def test_diet_section_overall_and_groups(monkeypatch):
    diet = synthetic_diet()
    report = _build(monkeypatch, diet)
    ConsumerReport.model_validate(report)
    section = next(s for s in report["sections"] if s["id"] == "diet-nutrition")
    ids = [sub["id"] for sub in section["subsections"]]
    assert ids[0] == "diet-nutrition-overview" and len(ids) == 7  # overview + 6 nutrient groups
    overview = section["subsections"][0]
    scale = next(b for b in overview["blocks"] if b["type"] == "tier_scales")["rows"][0]
    assert scale["label"] == "膳食营养综合评分" and scale["value"]["display"].endswith("分")
    rows = [row for sub in section["subsections"][1:] for b in sub["blocks"] for row in b["rows"]]
    assert len(rows) == 22 and all(row["tier"] for row in rows)
    # Copy checks never hide content of this section.
    assert not any(o["section"] == "diet-nutrition" for o in report["omissions"])
    assessments = {a["id"]: a for a in report["summary"]["assessments"]}
    assert assessments["diet_nutrition"]["anchor"] == "#diet-nutrition"
    assert any("不是实际摄入量" in p for p in assessments["diet_nutrition"]["points"])
    methods = [sub for s in report["sections"] if s["id"] == "learn" for sub in s["subsections"]]
    assert any(sub["title"] == "膳食营养评分" for sub in methods)


def test_diet_advice_follows_direction(monkeypatch):
    diet = synthetic_diet()
    for row in diet["nutrients"]:
        row["percentile_healthy"] = 50.0
    fibre = next(r for r in diet["nutrients"] if r["id"] == "100009")
    alcohol = next(r for r in diet["nutrients"] if r["id"] == "100022")
    energy = next(r for r in diet["nutrients"] if r["id"] == "100002")
    fibre["percentile_healthy"], alcohol["percentile_healthy"], energy["percentile_healthy"] = 8.0, 92.0, 97.0
    report = _build(monkeypatch, diet)
    overview = next(s for s in report["sections"] if s["id"] == "diet-nutrition")["subsections"][0]
    table = next(b for b in overview["blocks"] if b["type"] == "table")
    advice = {row[0]: row for row in table["rows"]}
    assert advice["Englyst 膳食纤维"][1] == "偏低" and advice["Englyst 膳食纤维"][2].startswith("可以多吃")
    assert advice["酒精"][1] == "偏高" and advice["酒精"][2].startswith("可以少喝")
    assert "能量" not in advice  # neutral nutrients get no advice
    points = next(a for a in report["summary"]["assessments"] if a["id"] == "diet_nutrition")["points"]
    assert "建议增加Englyst 膳食纤维的食物来源。" in points and "建议减少酒精的摄入。" in points


def test_diet_section_hidden_without_bundle(monkeypatch):
    report = _build(monkeypatch, None)
    assert not any(s["id"] == "diet-nutrition" for s in report["sections"])
    assert any(o["section"] == "diet-nutrition" for o in report["omissions"])
    assert "diet_nutrition" not in {a["id"] for a in report["summary"]["assessments"]}
