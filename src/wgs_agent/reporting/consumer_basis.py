"""Shared G12 comparison-basis note, emitted once by each chapter renderer."""

NOTE = "为与健康人群同口径比较，本章数值经重新计算，可能与其他章节略有差异。"


def comparison_basis_note(document, chapter):
    """Return a note only when the chapter displays an independent cMD result.

    This component is pure so repeated report renders remain identical. Callers
    place it once per chapter, rather than suppressing it with persistent state.
    """
    if str(document.get("metadata", {}).get("qc_status", "")).lower() in {"failed", "fail", "未通过", "不通过"}:
        return None
    comparison = document.get("template_inputs", {}).get("healthy_comparison") or {}
    if comparison.get("audit", {}).get("status") != "available":
        return None
    if chapter == 1 and (comparison.get("species") or document.get("consumer", {}).get("concentration_reference")):
        return NOTE
    if chapter == 2 and (comparison.get("diversity") or comparison.get("typicality", {}).get("status") == "available"):
        return NOTE
    return None
