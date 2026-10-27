"""Bounded LitKG pagination with a scoped, last-successful snapshot."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import httpx

CACHE_SCHEMA = "litkg-report-claims-v1"
PAGE_SIZE = 100
MAX_FALLBACK_AGE_SECONDS = 86400


def _cache_file(client, knowledge_base_id, cache_dir):
    if cache_dir is False:
        return None, None
    if cache_dir is None:
        from wgs_fmt_platform.paths import workspace_root
        workspace = workspace_root().resolve()
        directory = workspace / "cache/report_litkg"
        if not directory.resolve().is_relative_to(workspace):
            return None, None
    else:
        directory = Path(cache_dir)
    url = client.base_url
    # Never place authentication material in cache identities or metadata.
    if url.username or url.password or url.query or url.path.rstrip("/") not in {"", "/api"}:
        return None, None
    identity = json.dumps([url.scheme, url.host, url.port, url.path.rstrip("/"), knowledge_base_id], separators=(",", ":"))
    key = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return directory / f"kb-{knowledge_base_id}-{key}.json", identity


def _read_cache(path, identity):
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("claims")
        if data.get("schema") != CACHE_SCHEMA or data.get("identity") != identity or data.get("complete") is not True:
            return None
        if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) or r.get("id") is None for r in rows):
            return None
        if len({str(r["id"]) for r in rows}) != len(rows) or len(rows) != data.get("total"):
            return None
        age = time.time() - float(data["fetched_at"])
        if not 0 <= age <= MAX_FALLBACK_AGE_SECONDS:
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_cache(path, identity, rows, total, head_id):
    if path is None:
        return False
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {"schema": CACHE_SCHEMA, "identity": identity, "complete": True, "total": total, "head_id": head_id, "fetched_at": time.time(), "claims": rows}
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".claims-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return True
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _page(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
        raise ValueError("invalid_litkg_page")
    rows = payload["claims"]
    total = payload.get("total")
    if any(not isinstance(r, dict) for r in rows) or type(total) is not int or total < 0:
        raise ValueError("invalid_litkg_page")
    return rows, total


async def load_claims(client, knowledge_base_id, limit, *, cache_dir=None, page_size=PAGE_SIZE, retries=2):
    """Return evidence plus an explicit complete/partial/cached source status."""
    path, identity = _cache_file(client, knowledge_base_id, cache_dir)
    cached = _read_cache(path, identity)
    audit = {"status": "unavailable", "knowledge_base_id": knowledge_base_id, "source": "live", "pages_completed": 0, "retry_count": 0}
    raw, seen = [], set()
    total, head_id = None, None
    offset, size = 0, max(25, min(int(page_size), 250))
    started = time.monotonic()

    async def request(count, position):
        nonlocal size
        for attempt in range(retries + 1):
            try:
                response = await client.get(f"/knowledge-bases/{knowledge_base_id}/claims", params={"limit": count, "offset": position})
                response.raise_for_status()
                return _page(response.json())
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt >= retries:
                    raise
                audit["retry_count"] += 1
                count = max(25, count // 2)
                size = min(size, count)
                await asyncio.sleep(.2 * (attempt + 1))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {429, 500, 502, 503, 504} or attempt >= retries:
                    raise
                audit["retry_count"] += 1
                await asyncio.sleep(.2 * (attempt + 1))

    def cached_result(error=None):
        rows = cached["claims"][:limit]
        metadata = {**audit, "status": "cached", "source": "last_successful_snapshot", "total_claims": cached["total"], "scan_truncated": len(rows) < cached["total"], "cache_age_seconds": round(time.time() - cached["fetched_at"]), "cache_fetched_at": cached["fetched_at"], "cache_validated": error is None}
        if error:
            metadata["refresh_error_type"] = type(error).__name__
        return rows, metadata

    try:
        while offset < limit:
            if time.monotonic() - started > 180:
                raise httpx.ReadTimeout("litkg_report_deadline")
            batch, observed_total = await request(min(size, limit - offset), offset)
            total = observed_total
            if head_id is None and batch:
                head_id = str(batch[0]["id"])
            if not batch:
                break
            for row in batch:
                if row.get("id") is None:
                    audit["skipped_invalid_claims"] = audit.get("skipped_invalid_claims", 0) + 1
                    continue
                key = str(row["id"])
                if key not in seen:
                    raw.append(row)
                    seen.add(key)
            offset += len(batch)
            audit["pages_completed"] += 1
            if offset >= total:
                break
        complete = total is not None and len(raw) == total and offset >= total
        audit.update(status="complete" if complete else "partial", total_claims=total, scan_truncated=not complete)
        if complete:
            audit["cache_written"] = _write_cache(path, identity, raw, total, head_id)
        return raw, audit
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        if cached:
            return cached_result(exc)
        if raw:
            return raw, {**audit, "status": "partial", "total_claims": total, "scan_truncated": True, "refresh_error_type": type(exc).__name__}
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {429, 500, 502, 503, 504}:
            if cached:
                return cached_result(exc)
            if raw:
                return raw, {**audit, "status": "partial", "total_claims": total, "scan_truncated": True, "refresh_error_type": type(exc).__name__}
        raise
