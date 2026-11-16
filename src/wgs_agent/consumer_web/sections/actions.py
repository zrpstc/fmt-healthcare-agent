"""Action suggestions (professional chapter 13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wgs_fmt_platform.paths import PROJECT_ROOT

from ..format import tier
from ..functions import fiber_contributors
from .context import Context
from .panel import category_total, load_panel
from .resistance import resistance_genes
from .virulence import high_concern_results

ACTIONS_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_actions.yaml"
RED_FLAGS = [
    "腹泻持续超过2周",
    "便血或黑便",
    "不明原因体重下降",
    "发热伴腹痛",
]


def load_actions(path: Path | None = None) -> dict[str, dict]:
    raw = Path(path or ACTIONS_PATH).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError:
        import yaml
        value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("actions"), list):
        raise ValueError("invalid_consumer_actions")
    return {str(item["finding_code"]): item for item in value["actions"]}


def _diversity_low(ctx: Context) -> bool:
    rows = ctx.healthy_comparison.get("diversity", [])
    for row in rows if isinstance(rows, list) else []:
        if row.get("metric") == "richness" and row.get("percentile") is not None:
            t = tier(float(row["percentile"]), metric="richness", borderline=bool(row.get("borderline")))
            return t.key in {"very_low", "low"}
    return False


def _watch_high(ctx: Context) -> bool:
    panel = load_panel()
    for category in panel.get("categories", []):
        if category.get("id") == "watch.opportunists" and category_total(ctx, category) > 0:
            return True
    return False


def _butyrate_ok(ctx: Context) -> bool:
    panel = load_panel()
    return any(
        category_total(ctx, category) > 0
        for category in panel.get("categories", [])
        if category.get("id") == "helpful.butyrate"
    )


def _fiber_few(ctx: Context) -> bool:
    fibers = fiber_contributors(ctx.document)
    return any(item["conclusion"] in {"少数菌具备", "本次未检出相关基因"} for item in fibers.values())


def build(ctx: Context) -> dict[str, Any]:
    rules = load_actions()
    codes: list[str] = []
    if high_concern_results(ctx):
        codes.append("consult_care")
    if _diversity_low(ctx):
        codes.append("diversity_low")
    if _watch_high(ctx):
        codes.append("opportunist_high")
    if _butyrate_ok(ctx):
        codes.append("butyrate_ok")
    if _fiber_few(ctx):
        codes.append("fiber_substrate_few")
    codes.append("retest_general")

    actions = []
    for code in codes:
        rule = rules.get(code)
        if not rule or not rule.get("title"):
            continue
        actions.append({
            "finding_code": code,
            "because": str(rule.get("because") or ""),
            "title": str(rule.get("title") or ""),
            "how": str(rule.get("how") or ""),
            "examples": rule.get("examples") or None,
        })

    # Keep the general retest advice even when earlier findings fill five slots.
    if len(actions) > 5:
        general = next((item for item in actions if item["finding_code"] == "retest_general"), None)
        filtered = [item for item in actions if item["finding_code"] != "retest_general"]
        actions = filtered[:4] + ([general] if general else [])

    focus = ["菌种数", "需留意菌占比"]
    if resistance_genes(ctx):
        focus.append("耐药基因")
    if high_concern_results(ctx):
        focus.append("毒素基因")
    if not focus:
        focus = ["菌种数", "需留意菌占比"]

    return {
        "actions": actions,
        "retest": {"months": 3, "focus": focus},
        "red_flags": RED_FLAGS,
    }
