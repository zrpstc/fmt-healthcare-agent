"""Public and authenticated consumer-report routes."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from wgs_agent.consumer_web.builder import build_report
from wgs_agent.consumer_web.glossary import GlossaryService
from wgs_agent.consumer_web.glossary_candidates import generate_for_sample, needs_path
from wgs_fmt_platform.infrastructure.api import _authenticated_user
from wgs_fmt_platform.infrastructure.database import (
    ConsumerGlossaryReview,
    ConsumerShareLink,
    SessionLocal,
)
from wgs_fmt_platform.paths import runtime_path
from wgs_agent.pipeline.sample_registry import read_record

router = APIRouter(tags=["consumer-report"])

RESULTS_DIR = runtime_path("WGS_RESULTS_DIR", "results")
SAMPLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DOWNLOAD_KINDS = {
    "professional_pdf": lambda sid: RESULTS_DIR / f"{sid}_health_report.pdf",
    "virulence": lambda sid: RESULTS_DIR / f"{sid}_consumer_virulence.csv",
    "mobile_elements": lambda sid: RESULTS_DIR / f"{sid}_consumer_mobile_elements.csv",
    "viral_clusters": lambda sid: RESULTS_DIR / f"{sid}_consumer_viral_clusters.csv",
    "pathway_contributions": lambda sid: RESULTS_DIR / f"{sid}_consumer_pathway_contributions.csv",
}
_RATE_LOCK = threading.Lock()
_RATE: dict[str, tuple[float, float]] = {}


def _rate_limit(request: Request) -> None:
    """Simple per-IP token bucket: 60 requests per minute."""
    now = time.monotonic()
    ip = request.client.host if request.client else "unknown"
    with _RATE_LOCK:
        tokens, last = _RATE.get(ip, (60.0, now))
        tokens = min(60.0, tokens + (now - last) * 1.0)
        if tokens < 1.0:
            raise HTTPException(429, "请求过于频繁，请稍后再试。")
        _RATE[ip] = (tokens - 1.0, now)


def _sid(value: str) -> str:
    if not SAMPLE_ID.fullmatch(value):
        raise HTTPException(422, "样本编号格式无效。")
    return value


def _optional_user(authorization: str | None):
    if not authorization:
        return None
    try:
        return _authenticated_user(authorization)
    except HTTPException:
        return None


def _require_editor(authorization: str | None):
    user = _optional_user(authorization)
    if user is None:
        raise HTTPException(401, "请先登录。")
    if user.role not in {"admin", "researcher"}:
        raise HTTPException(403, "需要管理员或研究者权限。")
    return user


def _alias(sample_id: str) -> str:
    metadata = read_record(sample_id)
    return str(metadata.get("name") or "").strip() or ("样本 " + sample_id.rsplit("_", 1)[-1][:6])


def _report_for(sample_id: str, *, refresh: bool = False, allow_pending: bool | None = None) -> dict:
    return build_report(sample_id, refresh=refresh, allow_pending=allow_pending, alias=_alias(sample_id))


def _public_report(sample_id: str, *, refresh: bool = False) -> dict:
    report = _report_for(sample_id, refresh=refresh, allow_pending=False)
    alias = _alias(sample_id)
    report["sample"]["sample_id"] = alias
    report["sample"]["alias"] = alias
    for item in report.get("downloads", []):
        kind = item.get("kind", "")
        if kind != "professional_pdf":
            item["href"] = f"/backend/api/reports/{sample_id}/consumer/downloads/{kind}"
    return report


class SharePayload(BaseModel):
    expires_days: int = Field(default=30, ge=1, le=90)


class ReviewPayload(BaseModel):
    field: Literal["one_liner", "watch_note"] = "one_liner"
    status: Literal["approved", "rejected"] = "approved"
    text: str = Field(default="", max_length=2000)


@router.get("/reports/{sample_id}/consumer")
def consumer_report(sample_id: str, refresh: int = Query(default=0, ge=0, le=1),
                    authorization: str | None = Header(default=None)) -> dict:
    sample_id = _sid(sample_id)
    if refresh and _optional_user(authorization) is None:
        raise HTTPException(401, "刷新消费者版需要登录。")
    if refresh:
        user = _optional_user(authorization)
        if user is None or user.role not in {"admin", "researcher"}:
            raise HTTPException(403, "需要管理员或研究者权限。")
    try:
        return _report_for(sample_id, refresh=bool(refresh), allow_pending=None)
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == "report_missing" else 422, "消费者版报告暂不可构建。") from exc


@router.post("/reports/{sample_id}/consumer/share")
def create_share(sample_id: str, payload: SharePayload,
                 authorization: str | None = Header(default=None)) -> dict:
    sample_id = _sid(sample_id)
    user = _require_editor(authorization)
    try:
        _report_for(sample_id)
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == "report_missing" else 422, "消费者版报告暂不可构建。") from exc
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=payload.expires_days)
    with SessionLocal() as session:
        link = ConsumerShareLink(
            sample_id=sample_id,
            token_sha256=token_hash,
            created_by=user.id,
            expires_at=expires_at,
        )
        session.add(link)
        session.commit()
        session.refresh(link)
    return {
        "token": token,
        "url": f"/share/{token}",
        "expires_at": expires_at.isoformat(),
        "id": link.id,
    }


@router.get("/reports/{sample_id}/consumer/shares")
def list_shares(sample_id: str, authorization: str | None = Header(default=None)) -> dict:
    sample_id = _sid(sample_id)
    _require_editor(authorization)
    with SessionLocal() as session:
        rows = session.scalars(
            select(ConsumerShareLink).where(ConsumerShareLink.sample_id == sample_id)
        ).all()
    return {
        "sample_id": sample_id,
        "shares": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                "last_accessed_at": row.last_accessed_at.isoformat() if row.last_accessed_at else None,
            }
            for row in rows
        ],
    }


@router.delete("/reports/{sample_id}/consumer/shares/{share_id}")
def revoke_share(sample_id: str, share_id: str,
                 authorization: str | None = Header(default=None)) -> dict:
    sample_id = _sid(sample_id)
    _require_editor(authorization)
    with SessionLocal() as session:
        row = session.scalar(
            select(ConsumerShareLink).where(
                ConsumerShareLink.id == share_id,
                ConsumerShareLink.sample_id == sample_id,
            )
        )
        if row is None:
            raise HTTPException(404, "分享链接不存在。")
        row.revoked_at = datetime.now(UTC)
        session.commit()
    return {"status": "revoked", "id": share_id}


def _share_record(token: str) -> ConsumerShareLink:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with SessionLocal() as session:
        row = session.scalar(select(ConsumerShareLink).where(ConsumerShareLink.token_sha256 == token_hash))
        if row is None:
            raise HTTPException(404, "链接无效或已过期。")
        now = datetime.now(UTC)
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if row.revoked_at is not None or expires_at <= now:
            raise HTTPException(404, "链接无效或已过期。")
        row.last_accessed_at = now
        session.commit()
        return row


@router.get("/share/{token}")
def shared_report(token: str, request: Request, response: Response) -> dict:
    _rate_limit(request)
    row = _share_record(token)
    try:
        report = _public_report(row.sample_id)
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == "report_missing" else 422, "报告暂不可用。") from exc
    alias = _alias(row.sample_id)
    report["sample"]["sample_id"] = alias
    report["sample"]["alias"] = alias
    for item in report.get("downloads", []):
        kind = item.get("kind", "")
        if kind:
            item["href"] = f"/backend/api/share/{token}/downloads/{kind}"
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return report


@router.get("/share/{token}/downloads/{kind}")
def shared_download(token: str, kind: str, request: Request) -> FileResponse:
    _rate_limit(request)
    if kind not in DOWNLOAD_KINDS:
        raise HTTPException(404, "下载类型不存在。")
    row = _share_record(token)
    path = DOWNLOAD_KINDS[kind](row.sample_id)
    if not path.is_file():
        raise HTTPException(404, "文件不存在。")
    media = "application/pdf" if kind == "professional_pdf" else "text/csv; charset=utf-8"
    return FileResponse(path, media_type=media, filename=path.name, headers={"Cache-Control": "no-store, max-age=0"})


@router.get("/reports/{sample_id}/consumer/downloads/{kind}")
def consumer_download(sample_id: str, kind: str) -> FileResponse:
    sample_id = _sid(sample_id)
    if kind not in DOWNLOAD_KINDS:
        raise HTTPException(404, "下载类型不存在。")
    try:
        _report_for(sample_id)
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == "report_missing" else 422, "报告暂不可用。") from exc
    path = DOWNLOAD_KINDS[kind](sample_id)
    if not path.is_file():
        raise HTTPException(404, "文件不存在。")
    media = "application/pdf" if kind == "professional_pdf" else "text/csv; charset=utf-8"
    return FileResponse(path, media_type=media, filename=path.name, headers={"Cache-Control": "no-store, max-age=0"})


@router.get("/consumer/glossary/review")
def glossary_review(include_rejected: int = Query(default=0, ge=0, le=1),
                    authorization: str | None = Header(default=None)) -> dict:
    _require_editor(authorization)
    service = GlossaryService(allow_pending=True)
    rows = service.review_queue(include_rejected=bool(include_rejected))
    for row in rows:
        row["samples_used"] = sorted(set(row.pop("sample_ids", []) or []) | set(_samples_using(row["term_id"])))
    return {"count": len(rows), "entries": rows}


def _samples_using(term_id: str) -> list[str]:
    samples: list[str] = []
    if not RESULTS_DIR.is_dir():
        return samples
    needle = f"[[{term_id}|"
    for path in RESULTS_DIR.glob("*_consumer_report.json"):
        try:
            if needle in path.read_text(encoding="utf-8"):
                samples.append(path.name.replace("_consumer_report.json", ""))
        except OSError:
            continue
    return sorted(samples)


@router.post("/consumer/glossary/review/{term_id}")
def review_term(term_id: str, payload: ReviewPayload,
                authorization: str | None = Header(default=None)) -> dict:
    user = _require_editor(authorization)
    service = GlossaryService(allow_pending=True)
    if term_id not in service.entries or not service.has_record(term_id, payload.field):
        raise HTTPException(404, "术语或字段不存在。")
    text = payload.text.strip()
    if payload.status == "approved" and not text:
        raise HTTPException(422, "通过前需要填写解释文字。")
    status = payload.status
    if status == "rejected":
        text = ""
    with SessionLocal() as session:
        row = session.scalar(
            select(ConsumerGlossaryReview).where(
                ConsumerGlossaryReview.term_id == term_id,
                ConsumerGlossaryReview.field == payload.field,
            )
        )
        if row is None:
            row = ConsumerGlossaryReview(term_id=term_id, field=payload.field)
            session.add(row)
        row.status = status
        row.text = text
        row.reviewer = user.display_name or user.username
        row.reviewed_at = datetime.now(UTC)
        session.commit()
    return {"status": status, "term_id": term_id, "field": payload.field, "reviewer": user.username}


class GeneratePayload(BaseModel):
    sample_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=20, ge=1, le=100)
    use_llm: bool = True


@router.post("/consumer/glossary/generate")
def generate_glossary(payload: GeneratePayload, authorization: str | None = Header(default=None)) -> dict:
    """Draft explanations for a sample's unexplained taxa; results stay pending."""
    _require_editor(authorization)
    sample_id = _sid(payload.sample_id)
    try:
        _report_for(sample_id, refresh=not needs_path(sample_id, RESULTS_DIR).is_file())
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == "report_missing" else 422, "消费者版报告暂不可构建。") from exc
    summary = generate_for_sample(sample_id, limit=payload.limit, use_llm=payload.use_llm, results_dir=RESULTS_DIR)
    return summary
