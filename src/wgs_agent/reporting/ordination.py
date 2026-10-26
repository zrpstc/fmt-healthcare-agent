"""Auditable joint community ordination; deliberately does not infer enterotypes."""
from __future__ import annotations

import math


def community_ordination(target, matrix, selected, *, reference_version="", stratify_by=()):
    """Use the complete union of species and the already vetted reference selection.

    Bray-Curtis is computed after independently closing every profile to one.
    Classical PCoA uses a Lingoes correction when its Gram matrix is indefinite.
    Original Bray-Curtis distances are retained for descriptive summaries.
    """
    import numpy as np
    from scipy.spatial.distance import pdist, squareform

    def unavailable(reason):
        return {"status": "unavailable", "reason": reason, "points": []}

    ids = sorted(selected)
    if len(ids) < 2 or len(set(ids)) != len(ids) or any(sid not in matrix for sid in ids):
        return unavailable("invalid_reference_selection")
    if len(ids) > 2000:
        return unavailable("reference_selection_too_large")
    profiles = [target, *(matrix[sid] for sid in ids)]
    if any(not isinstance(profile, dict) or not profile for profile in profiles):
        return unavailable("invalid_profile")
    features = sorted(set().union(*(profile.keys() for profile in profiles)))
    values = []
    for profile in profiles:
        row = []
        for feature in features:
            value = profile.get(feature, 0.0)
            if isinstance(value, bool):
                return unavailable("invalid_abundance")
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                return unavailable("invalid_abundance")
            if not math.isfinite(value) or value < 0:
                return unavailable("invalid_abundance")
            row.append(value)
        total = math.fsum(row)
        if not math.isfinite(total) or total <= 0:
            return unavailable("empty_profile")
        values.append([value / total for value in row])
    distances = squareform(pdist(np.asarray(values, dtype=float), metric="braycurtis"))
    n = len(profiles)
    centering = np.eye(n) - np.ones((n, n)) / n
    gram = -0.5 * centering @ np.square(distances) @ centering
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(gram)
        tolerance = max(float(np.max(np.abs(eigenvalues))), 1.0) * 1e-12
        correction = max(0.0, -float(eigenvalues[0])) if eigenvalues[0] < -tolerance else 0.0
        if correction:
            squared = np.square(distances) + 2 * correction * (np.ones((n, n)) - np.eye(n))
            gram = -0.5 * centering @ squared @ centering
            eigenvalues, eigenvectors = np.linalg.eigh(gram)
    except np.linalg.LinAlgError:
        return unavailable("ordination_numerical_failure")
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues, eigenvectors = eigenvalues[order], eigenvectors[:, order]
    positive = eigenvalues > tolerance
    if not np.any(positive):
        return unavailable("no_community_variation")
    total_variance = float(np.sum(eigenvalues[positive]))
    coordinates = np.zeros((n, 2))
    explained = [0.0, 0.0]
    for axis in range(min(2, int(np.sum(positive)))):
        vector = eigenvectors[:, axis]
        pivot = int(np.argmax(np.abs(vector)))
        if vector[pivot] < 0:
            vector = -vector
        coordinates[:, axis] = vector * math.sqrt(float(eigenvalues[axis]))
        explained[axis] = float(eigenvalues[axis]) / total_variance
    points = [
        {"x": float(row[0]), "y": float(row[1]), "group": "本次样本" if i == 0 else "参考人群", "is_sample": i == 0}
        for i, row in enumerate(coordinates)
    ]
    original = distances[0, 1:]
    return {
        "status": "available", "method": "Bray-Curtis PCoA" + (" (Lingoes correction)" if correction else ""),
        "distance_metric": "Bray-Curtis", "normalization": "per_sample_closure_to_one",
        "correction": "Lingoes" if correction else "none", "correction_constant": correction,
        "points": points, "explained_variance": explained,
        "axis_x": f"PCoA 1 ({explained[0] * 100:.1f}%)",
        "axis_y": f"PCoA 2 ({explained[1] * 100:.1f}%)",
        "n_reference": len(ids), "n_features": len(features), "reference_version": reference_version,
        "stratify_by": list(stratify_by), "joint_fit": True,
        "distance_summary": {"median": float(np.median(original)), "minimum": float(np.min(original)), "maximum": float(np.max(original))},
        "limitations": ["二维位置仅概括部分群落差异。", "距离为描述性指标，不是疾病概率、显著性检验或肠型分类。"],
    }


def composition_summary(document):
    """Describe observed genus abundance without claiming a categorical enterotype."""
    metadata = document.get("metadata") or {}
    if str(metadata.get("qc_status", "")).strip().lower() in {"failed", "fail", "rejected", "不合格"}:
        return "本次样本质控未通过，暂不解读群落组成倾向。"
    taxonomy = (document.get("template_inputs") or {}).get("taxonomy") or {}
    if taxonomy.get("complete") is not True:
        return "本次未提供完整且可核对的菌群组成，暂不判断组成倾向。群落位置与参考差异见 2.2；目前未完成可靠肠型分类。"
    rows = (taxonomy.get("ranks") or {}).get("genus") or []
    observed = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("taxon") or row.get("label")
        value = row.get("abundance")
        if isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if name and math.isfinite(value) and value > 0:
            observed.append((str(name), value))
    observed.sort(key=lambda row: (-row[1], row[0]))
    if not observed:
        return "本次未提供可核对的菌属组成，暂不判断组成倾向。群落位置与参考差异见 2.2；目前未完成可靠肠型分类。"
    labels = [name.replace("g__", "").replace("_", " ") for name, _ in observed[:3]]
    return "本次检出丰度较高的菌属依次为：" + "、".join(labels) + "。这是群落组成的描述，目前未完成可靠肠型分类。群落位置与参考差异统一见 2.2。"


def community_paragraph(document, *, interpretation=False):
    inputs = document.get("template_inputs") or {}
    if str((document.get("metadata") or {}).get("qc_status", "")).strip().lower() in {"failed", "fail", "rejected", "不合格"}:
        return "本次样本质控未通过，暂不解读群落位置与参考差异。"
    comparison = inputs.get("healthy_comparison") or {}
    payload = (comparison.get("ordination") or {}) if comparison else ((inputs.get("diversity") or {}).get("ordination") or {})
    if payload.get("status") != "available":
        if interpretation:
            return "结果解读：缺少通过校验的参考比较坐标，暂无法判断群落位置；不据优势菌属直接推定肠型。"
        return "参考群落位置尚不可用；需要完整的同方法物种丰度、通过校验的参考人群以及联合降维坐标。"
    if interpretation:
        text = "结果解读：点间距离反映群落组成差异；二维图仅概括部分差异，不作为疾病概率、显著性或肠型分类结果。"
        if not payload.get("stratify_by"):
            text += "当前参考人群未按年龄、性别或国家作人口学匹配。"
        else:
            titles = {"age": "年龄", "sex": "性别", "country": "国家"}
            text += "参考人群按" + "、".join(titles.get(k, k) for k in payload["stratify_by"]) + "筛选。"
        return text
    summary = payload.get("distance_summary") or {}
    text = f"参考人群：{payload.get('n_reference', 0)} 个独立参考样本；方法：{payload.get('method', 'PCoA')}。"
    if summary.get("median") is not None:
        text += f"本次样本与参考样本的 Bray-Curtis 距离中位数为 {summary['median']:.3f}（范围 {summary['minimum']:.3f}–{summary['maximum']:.3f}，0 表示组成相同）。"
    return text
