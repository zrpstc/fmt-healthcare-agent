"""Consumer glossary service with an explicit approved-only publication gate.

Text comes from three places, merged per ``(term_id, field)``:

* the curated file ``knowledge_base/consumer_glossary.yaml`` (JSON content);
* machine-drafted candidates in ``consumer_glossary_candidates`` (always pending);
* human review decisions in ``consumer_glossary_reviews`` (override both).

Only ``approved`` text may reach a published report.  ``allow_pending`` exists for
internal previews; public share pages always build with ``allow_pending=False``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from wgs_agent.reporting.functional_metrics import taxon_name
from wgs_fmt_platform.paths import PROJECT_ROOT

from .names import canonical

TERM_MARKUP = re.compile(r"\[\[([A-Za-z0-9_.:-]+)\|([^\]]+)\]\]")
DEFAULT_PATH = PROJECT_ROOT / "knowledge_base" / "consumer_glossary.yaml"
FIELDS = ("one_liner", "watch_note")
TAXON_KINDS = {"species", "genus", "taxon"}


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


def taxon_term_id(latin: str) -> str:
    """Stable glossary id for a machine-drafted taxon entry."""
    slug = re.sub(r"[^a-z0-9]+", "_", canonical(str(latin or "")).casefold()).strip("_")
    return f"taxon:{slug}" if slug else ""


class GlossaryService:
    """Curated file + candidates + reviews, with approved-only output."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        allow_pending: bool | None = None,
        load_reviews: bool = True,
        load_candidates: bool = True,
        candidates: list[dict[str, Any]] | None = None,
        reviews: list[dict[str, Any]] | None = None,
    ) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self.document = _load_document(self.path)
        self.version = str(self.document.get("version") or "consumer-glossary-v1")
        self.entries: dict[str, dict[str, Any]] = {
            str(item["term_id"]): dict(item) for item in self.document["entries"] if item.get("term_id")
        }
        # (term_id, field) -> record
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        for term_id, entry in self.entries.items():
            for field in FIELDS:
                text = str(entry.get(field) or "").strip()
                if text:
                    self.records[(term_id, field)] = {
                        "text": text,
                        "status": str(entry.get("review_status") or "pending"),
                        "origin": "curated",
                        "sources": entry.get("sources") or [],
                        "model": str(entry.get("model") or ""),
                        "evidence": [],
                        "evidence_scope": str(entry.get("evidence_scope") or ""),
                    }
        candidate_rows = candidates if candidates is not None else (self._load_candidates() if load_candidates else [])
        self.candidate_digest = hashlib.sha256(
            json.dumps(candidate_rows, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()[:16]
        for row in candidate_rows:
            self._add_candidate(row)
        review_rows = reviews if reviews is not None else (self._load_reviews() if load_reviews else [])
        self.reviews: dict[tuple[str, str], dict[str, str]] = {}
        for row in review_rows:
            field = str(row.get("field") or "one_liner")
            status = str(row.get("status") or "pending")
            if status not in {"approved", "rejected", "pending"}:
                status = "pending"
            self.reviews[(str(row["term_id"]), field)] = {
                "status": status,
                "text": "" if status == "rejected" else str(row.get("text") or ""),
            }
        self._latin_index: dict[str, str] = {}
        for term_id, entry in self.entries.items():
            if str(entry.get("kind") or "") not in TAXON_KINDS:
                continue
            for name in [entry.get("latin"), *(entry.get("aliases") or [])]:
                if name:
                    self._latin_index.setdefault(canonical(str(name)), term_id)
        if allow_pending is None:
            allow_pending = os.environ.get("WGS_GLOSSARY_REQUIRE_REVIEW", "1").strip() != "1"
        self.allow_pending = allow_pending
        self.used: set[str] = set()

    # --------------------------------------------------------------- loading
    @staticmethod
    def _load_reviews() -> list[dict[str, Any]]:
        try:
            from wgs_fmt_platform.infrastructure.database import ConsumerGlossaryReview, SessionLocal
        except Exception:
            return []
        try:
            with SessionLocal() as session:
                return [
                    {"term_id": row.term_id, "field": row.field, "status": row.status, "text": row.text or ""}
                    for row in session.query(ConsumerGlossaryReview).all()
                ]
        except Exception:
            return []

    @staticmethod
    def _load_candidates() -> list[dict[str, Any]]:
        try:
            from wgs_fmt_platform.infrastructure.database import ConsumerGlossaryCandidate, SessionLocal
        except Exception:
            return []
        try:
            with SessionLocal() as session:
                return [
                    {
                        "term_id": row.term_id, "field": row.field, "kind": row.kind,
                        "display_name": row.display_name, "latin": row.latin, "text": row.text or "",
                        "evidence_scope": row.evidence_scope, "evidence": row.evidence or [],
                        "sources": row.sources or [], "sample_ids": row.sample_ids or [],
                        "model": row.model, "draft_status": row.draft_status,
                    }
                    for row in session.query(ConsumerGlossaryCandidate).all()
                ]
        except Exception:
            return []

    def _add_candidate(self, row: dict[str, Any]) -> None:
        term_id = str(row.get("term_id") or "")
        field = str(row.get("field") or "one_liner")
        if not term_id or field not in FIELDS:
            return
        if term_id not in self.entries:
            self.entries[term_id] = {
                "term_id": term_id,
                "kind": str(row.get("kind") or "species"),
                "display_name": str(row.get("display_name") or term_id),
                "latin": str(row.get("latin") or ""),
                "aliases": [],
                "sources": row.get("sources") or [],
                "review_status": "pending",
                "model": str(row.get("model") or ""),
                "origin": "candidate",
            }
        if (term_id, field) in self.records:
            return  # curated text for the same field always wins
        self.records[(term_id, field)] = {
            "text": str(row.get("text") or "").strip(),
            "status": "pending",
            "origin": "candidate",
            "sources": row.get("sources") or [],
            "model": str(row.get("model") or ""),
            "evidence": row.get("evidence") or [],
            "evidence_scope": str(row.get("evidence_scope") or ""),
            "sample_ids": row.get("sample_ids") or [],
            "draft_status": str(row.get("draft_status") or ""),
        }

    def review_version(self) -> str:
        payload = json.dumps(
            {f"{key[0]}::{key[1]}": value for key, value in sorted(self.reviews.items())},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256((self.version + "|" + payload + "|" + self.candidate_digest).encode()).hexdigest()[:16]

    # ---------------------------------------------------------------- status
    def has_record(self, term_id: str, field: str = "one_liner") -> bool:
        return (term_id, field) in self.records or (term_id, field) in self.reviews

    def status(self, term_id: str, field: str = "one_liner") -> str:
        review = self.reviews.get((term_id, field))
        if review:
            return review["status"]
        record = self.records.get((term_id, field))
        if record:
            return record["status"]
        if term_id in self.entries:
            return str(self.entries[term_id].get("review_status") or "pending")
        return "missing"

    def is_approved(self, term_id: str, field: str = "one_liner") -> bool:
        return self.status(term_id, field) == "approved" and bool(self.field_text(term_id, field))

    def is_publishable(self, term_id: str, field: str = "one_liner") -> bool:
        status = self.status(term_id, field)
        if status == "approved":
            return bool(self.field_text(term_id, field))
        return self.allow_pending and status == "pending" and bool(self.field_text(term_id, field))

    # --------------------------------------------------------------- content
    def entry(self, term_id: str) -> dict[str, Any] | None:
        return self.entries.get(term_id)

    def reviewed_text(self, term_id: str, field: str = "one_liner") -> str | None:
        review = self.reviews.get((term_id, field))
        if review and review["status"] == "approved" and review["text"].strip():
            return review["text"].strip()
        return None

    def field_text(self, term_id: str, field: str = "one_liner") -> str:
        reviewed = self.reviewed_text(term_id, field)
        if reviewed:
            return reviewed
        record = self.records.get((term_id, field))
        return str(record["text"]).strip() if record else ""

    def one_liner(self, term_id: str) -> str:
        return self.field_text(term_id, "one_liner")

    def watch_note(self, term_id: str) -> str:
        return self.field_text(term_id, "watch_note")

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
        # A reviewer-edited one-liner replaces the curated pair entirely.
        if self.reviewed_text(term_id, "one_liner"):
            return one
        if detail and detail != one:
            return one + " " + detail
        return one

    def badge(self, term_id: str) -> str | None:
        entry = self.entries.get(term_id) or {}
        return str(entry.get("evidence_badge") or "").strip() or None

    def source_ids(self, term_id: str) -> list[str]:
        entry = self.entries.get(term_id) or {}
        result: list[str] = []
        sources = list(entry.get("sources") or [])
        for field in FIELDS:
            record = self.records.get((term_id, field))
            if record:
                sources.extend(record.get("sources") or [])
        for source in sources:
            ident = str(source.get("id_or_url") or "").strip()
            if ident and ident not in result:
                result.append(ident)
        return result

    # ----------------------------------------------------------------- taxa
    def taxon_term(self, raw_name: str) -> str | None:
        """Exact species-level (or alias) entry for a detected taxon name."""
        raw_name = taxon_name(str(raw_name or ""))
        key = canonical(raw_name)
        if not key:
            return None
        term_id = self._latin_index.get(key)
        if term_id:
            return term_id
        candidate = taxon_term_id(raw_name)
        return candidate if candidate in self.entries else None

    def genus_term(self, raw_name: str) -> str | None:
        key = canonical(taxon_name(str(raw_name or "")))
        genus = key.split(" ")[0] if key else ""
        if not genus or genus == key:
            return None
        term_id = self._latin_index.get(genus)
        if term_id and str(self.entries.get(term_id, {}).get("kind")) == "genus":
            return term_id
        return None

    # --------------------------------------------------------------- markup
    def markup(self, term_id: str, display: str | None = None) -> str:
        """Emit a glossary term only if publishable; otherwise plain text."""
        self.used.add(term_id)
        label = display or self.display_name(term_id)
        if not self.is_publishable(term_id):
            return label
        return f"[[{term_id}|{label}]]"

    def validate_markup(self, text: str) -> list[str]:
        errors: list[str] = []
        for term_id, _display in TERM_MARKUP.findall(text):
            if term_id not in self.entries or not self.is_publishable(term_id):
                errors.append(term_id)
        return errors

    def strip_markup(self, text: str) -> str:
        return TERM_MARKUP.sub(lambda match: match.group(2), text)

    def used_entries(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for term_id in sorted(self.used):
            if not self.is_publishable(term_id):
                continue
            result.append({
                "term_id": term_id,
                "name": self.display_name(term_id),
                "latin": self.latin(term_id),
                "text": self.text(term_id),
                "evidence_badge": "待审" if not self.is_approved(term_id) else self.badge(term_id),
                "source_ids": self.source_ids(term_id),
            })
        return result

    # --------------------------------------------------------------- review
    def review_queue(self, *, include_rejected: bool = False) -> list[dict[str, Any]]:
        """One row per (term, field) that still needs a human decision.

        Rejected rows are hidden unless ``include_rejected`` is set, so a rejection
        does not reappear after a page refresh.
        """
        rows: list[dict[str, Any]] = []
        for (term_id, field), record in sorted(self.records.items()):
            status = self.status(term_id, field)
            if status == "approved" or (status == "rejected" and not include_rejected):
                continue
            entry = self.entries.get(term_id) or {}
            text = self.field_text(term_id, field)
            rows.append({
                "term_id": term_id,
                "field": field,
                "kind": str(entry.get("kind") or ""),
                "generated_text": text,
                "needs_writing": not bool(text),
                "name": self.display_name(term_id),
                "latin": self.latin(term_id) or "",
                "status": status,
                "origin": record.get("origin") or "curated",
                "sources": record.get("sources") or entry.get("sources") or [],
                "evidence": record.get("evidence") or [],
                "evidence_scope": record.get("evidence_scope") or "",
                "model": record.get("model") or entry.get("model") or "",
                "version": entry.get("version") or self.version,
                "sample_ids": record.get("sample_ids") or [],
            })
        return rows
