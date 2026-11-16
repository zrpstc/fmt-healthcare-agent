"""Consumer glossary service with an explicit approved-only publication gate."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from wgs_fmt_platform.paths import PROJECT_ROOT

TERM_MARKUP = re.compile(r"\[\[([A-Za-z0-9_.:-]+)\|([^\]]+)\]\]")
DEFAULT_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_glossary.yaml"


def _load_document(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except ValueError:
        try:
            import yaml  # optional; JSON is valid YAML and is used by default
        except ModuleNotFoundError as exc:
            raise ValueError("invalid_glossary_file") from exc
        value = yaml.safe_load(raw)
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise ValueError("invalid_glossary_file")
    return value


class GlossaryService:
    """YAML/JSON glossary plus database reviews, with approved-only output."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        allow_pending: bool | None = None,
        load_reviews: bool = True,
    ) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.document = _load_document(self.path)
        self.version = str(self.document.get("version") or "consumer-glossary-v1")
        self.entries: dict[str, dict[str, Any]] = {
            str(item["term_id"]): item for item in self.document["entries"] if item.get("term_id")
        }
        self.reviews: dict[str, dict[str, str]] = {}
        if load_reviews:
            self.reviews = self._load_reviews()
        if allow_pending is None:
            allow_pending = os.environ.get("WGS_GLOSSARY_REQUIRE_REVIEW", "1").strip() != "1"
        self.allow_pending = allow_pending
        self.used: set[str] = set()

    # ------------------------------------------------------------------ review
    def _load_reviews(self) -> dict[str, dict[str, str]]:
        try:
            from wgs_fmt_platform.infrastructure.database import SessionLocal, ConsumerGlossaryReview
        except Exception:
            return {}
        try:
            with SessionLocal() as session:
                rows = session.query(ConsumerGlossaryReview).all()
                result: dict[str, dict[str, str]] = {}
                for row in rows:
                    if row.status == "rejected":
                        result[row.term_id] = {"status": "rejected", "text": ""}
                    elif row.status == "approved":
                        result[row.term_id] = {"status": "approved", "text": row.text or ""}
                    else:
                        result[row.term_id] = {"status": "pending", "text": row.text or ""}
                return result
        except Exception:
            return {}

    def review_version(self) -> str:
        payload = json.dumps(self.reviews, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256((self.version + "|" + payload).encode()).hexdigest()[:16]

    def status(self, term_id: str) -> str:
        review = self.reviews.get(term_id)
        if review:
            return review["status"]
        return str(self.entries.get(term_id, {}).get("review_status") or "pending")

    def is_approved(self, term_id: str) -> bool:
        return self.status(term_id) == "approved"

    # ----------------------------------------------------------------- content
    def entry(self, term_id: str) -> dict[str, Any] | None:
        return self.entries.get(term_id)

    def reviewed_text(self, term_id: str) -> str | None:
        review = self.reviews.get(term_id)
        if review and review["status"] == "approved" and review["text"]:
            return review["text"]
        return None

    def one_liner(self, term_id: str) -> str:
        reviewed = self.reviewed_text(term_id)
        if reviewed:
            return reviewed
        entry = self.entries.get(term_id) or {}
        return str(entry.get("one_liner") or "").strip()

    def watch_note(self, term_id: str) -> str:
        reviewed = self.reviewed_text(term_id)
        if reviewed:
            return reviewed
        entry = self.entries.get(term_id) or {}
        return str(entry.get("watch_note") or entry.get("one_liner") or "").strip()

    def display_name(self, term_id: str) -> str:
        entry = self.entries.get(term_id) or {}
        return str(entry.get("display_name") or term_id).strip()

    def latin(self, term_id: str) -> str | None:
        entry = self.entries.get(term_id) or {}
        return str(entry.get("latin") or "").strip() or None

    def text(self, term_id: str) -> str:
        entry = self.entries.get(term_id) or {}
        one = self.one_liner(term_id)
        detail = str(entry.get("detail") or "").strip()
        if detail and detail != one:
            return one + " " + detail
        return one

    def badge(self, term_id: str) -> str | None:
        entry = self.entries.get(term_id) or {}
        return str(entry.get("evidence_badge") or "").strip() or None

    def source_ids(self, term_id: str) -> list[str]:
        entry = self.entries.get(term_id) or {}
        result: list[str] = []
        for source in entry.get("sources") or []:
            ident = str(source.get("id_or_url") or "").strip()
            if ident:
                result.append(ident)
        return result

    # ------------------------------------------------------------------ markup
    def markup(self, term_id: str, display: str | None = None) -> str:
        """Emit a glossary term only if approved; pending is allowed only explicitly."""
        self.used.add(term_id)
        label = display or self.display_name(term_id)
        status = self.status(term_id)
        if status != "approved" and not (self.allow_pending and status == "pending"):
            return label
        return f"[[{term_id}|{label}]]"

    def validate_markup(self, text: str) -> list[str]:
        errors: list[str] = []
        for term_id, _display in TERM_MARKUP.findall(text):
            status = self.status(term_id)
            if term_id not in self.entries or (status != "approved" and not (self.allow_pending and status == "pending")):
                errors.append(term_id)
        return errors

    def strip_markup(self, text: str) -> str:
        return TERM_MARKUP.sub(lambda match: match.group(2), text)

    def used_entries(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for term_id in sorted(self.used):
            status = self.status(term_id)
            if status != "approved" and not (self.allow_pending and status == "pending"):
                continue
            entry = self.entries.get(term_id) or {}
            result.append({
                "term_id": term_id,
                "name": self.display_name(term_id),
                "latin": self.latin(term_id),
                "text": self.text(term_id),
                "evidence_badge": "待审" if status != "approved" else self.badge(term_id),
                "source_ids": self.source_ids(term_id),
            })
        return result

    def review_queue(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for term_id, entry in self.entries.items():
            status = self.status(term_id)
            if status == "approved":
                continue
            rows.append({
                "term_id": term_id,
                "field": "one_liner" if entry.get("one_liner") else "watch_note",
                "generated_text": self.reviewed_text(term_id) or self.one_liner(term_id) or self.watch_note(term_id),
                "name": self.display_name(term_id),
                "status": status,
                "sources": entry.get("sources") or [],
                "model": entry.get("model") or "",
                "version": entry.get("version") or self.version,
            })
        return rows
