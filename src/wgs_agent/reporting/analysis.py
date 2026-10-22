"""Create report input from completed uploads without rerunning bioinformatics."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .inputs import load_existing_report_inputs


def ensure_analysis_input(sample_id: str, results_dir: Path) -> Path:
    """Preserve existing analyses; publish a complete new input only if absent.

    The caller must confirm the upload workflow has completed before calling.
    Missing reference comparisons and optional assays remain unassessed.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", sample_id):
        raise ValueError("样本编号格式无效")
    target = results_dir / f"{sample_id}_analysis.json"
    if target.is_file():
        return target

    inputs = load_existing_report_inputs(sample_id)
    taxonomy = inputs.get("taxonomy", {})
    observed = taxonomy.get("ranks", {}).get("species", [])
    if not taxonomy.get("complete") or not observed:
        raise ValueError("缺少完整有效的物种谱，请检查已完成的生信任务产物。")
    pathways = inputs.get("pathways", {})
    if not pathways.get("pathways") and not pathways.get("special_rows"):
        raise ValueError("缺少功能通路产物，请检查已完成的生信任务产物。")
    species = [
        {**row, "species": row["name"], "status": "unknown", "status_cn": "未建立参考比较"}
        for row in observed
    ]
    analysis = {
        "sample_id": sample_id,
        "species": {
            "species_list": species, "n_total": len(species),
            "n_high": 0, "n_low": 0, "n_unknown": len(species),
            "unit": "%", "is_complete": True,
        },
        **inputs,
        "metadata": {
            "analysis_source": "completed_upload_profiles",
            "analysis_version": "uploaded-profiles-v1",
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }
    payload = json.dumps(analysis, ensure_ascii=False, indent=2, allow_nan=False)
    results_dir.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{sample_id}-analysis-",
            suffix=".tmp", dir=results_dir, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # An atomic create prevents concurrent requests from replacing an
        # existing, potentially richer analysis or exposing partial JSON.
        try:
            os.link(temporary, target)
        except FileExistsError:
            if not target.is_file():
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
