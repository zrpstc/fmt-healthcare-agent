from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def parse_knowledge_base_ids(value: str | Iterable[int] | None) -> list[int]:
    """Parse a stable, de-duplicated list of positive LitKG knowledge-base IDs."""
    if value is None:
        return []
    if isinstance(value, str):
        if value.strip().casefold() in {"", "auto", "all", "*"}:
            return []
        raw: Iterable[Any] = value.split(",")
    else:
        raw = value
    result: list[int] = []
    for item in raw:
        try:
            parsed = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in result:
            result.append(parsed)
    return result


def normalize_knowledge_bases(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("knowledge_bases"), list):
        raise ValueError("LitKG knowledge-base catalog must contain a knowledge_bases list")
    result: list[dict[str, Any]] = []
    for item in payload["knowledge_bases"]:
        if not isinstance(item, dict):
            continue
        try:
            knowledge_base_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if knowledge_base_id <= 0:
            continue
        row = dict(item)
        row["id"] = knowledge_base_id
        row["name"] = str(item.get("name") or item.get("slug") or f"Knowledge Base {knowledge_base_id}")
        result.append(row)
    return result


def select_knowledge_bases(
    available: list[dict[str, Any]],
    *,
    requested_ids: str | Iterable[int] | None = None,
    configured_ids: str | Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    """Select requested/configured bases, or all discovered bases in automatic mode."""
    requested = parse_knowledge_base_ids(requested_ids)
    configured = parse_knowledge_base_ids(configured_ids)
    if not requested and not configured:
        return list(available)
    available_by_id = {int(item["id"]): item for item in available}
    if requested:
        return [available_by_id[item_id] for item_id in requested if item_id in available_by_id]
    selected = [available_by_id[item_id] for item_id in configured if item_id in available_by_id]
    # A stale deployment setting must not make a healthy LitKG service look offline.
    return selected or list(available)
