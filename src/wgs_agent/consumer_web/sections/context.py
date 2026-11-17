"""Shared build context for consumer sections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from wgs_agent.reporting.functional_metrics import taxon_name
from wgs_agent.reporting.inputs import finite

from ..functions import load_substrate_map, load_vitamin_map
from ..glossary import GlossaryService, taxon_term_id
from ..graph import GraphBuilder, ReferenceIndex
from ..names import NameRegistry, canonical


@dataclass
class Context:
    document: dict
    analysis: dict
    glossary: GlossaryService
    names: NameRegistry
    refs: ReferenceIndex
    graph: GraphBuilder
    omissions: list[dict] = field(default_factory=list)
    used_terms: set[str] = field(default_factory=set)
    first_graph_shown: bool = False
    # (canonical latin, field) -> displayed taxon that has no reviewable text yet
    glossary_needs: dict[tuple[str, str], dict] = field(default_factory=dict)
    _cohort: dict | None = None

    # -------------------------------------------------------- taxon texts
    def taxon_text(self, raw: str, field: str = "one_liner") -> str | None:
        """Publishable glossary text for a displayed taxon, or ``None``.

        Resolution is by Latin name (never by a hand-kept Chinese-name map).  A
        ``watch_note`` may fall back to the genus-level entry.  Any displayed taxon
        without a text record for the field is recorded in ``glossary_needs`` so a
        draft can be generated and queued for human review.
        """
        glossary = self.glossary
        raw = taxon_name(str(raw or ""))
        term_id = glossary.taxon_term(raw)
        if term_id and glossary.is_publishable(term_id, field):
            return glossary.field_text(term_id, field)
        if field == "watch_note":
            genus_id = glossary.genus_term(raw)
            if genus_id and glossary.is_publishable(genus_id, field):
                return glossary.field_text(genus_id, field)
        if not (term_id and glossary.has_record(term_id, field)):
            latin = re.sub(r"\s+", " ", str(raw or "").replace("_", " ")).strip()
            key = canonical(latin)
            if key and " " in key and not key.startswith("未分类"):
                self.glossary_needs.setdefault((key, field), {
                    "term_id": term_id or taxon_term_id(latin),
                    "latin": latin,
                    "display_name": self.names.label_only(latin),
                    "field": field,
                    "kind": "species",
                })
        return None

    # ------------------------------------------------------------------ data
    @property
    def sample_id(self) -> str:
        return str(self.document.get("sample_id") or "")

    @property
    def metadata(self) -> dict:
        value = self.document.get("metadata")
        return value if isinstance(value, dict) else {}

    @property
    def qc_failed(self) -> bool:
        status = str(self.metadata.get("qc_status", "")).strip().lower()
        return status in {"failed", "fail", "未通过", "不通过"}

    @property
    def template_inputs(self) -> dict:
        value = self.document.get("template_inputs")
        return value if isinstance(value, dict) else {}

    @property
    def taxonomy(self) -> dict:
        value = self.template_inputs.get("taxonomy")
        return value if isinstance(value, dict) else {}

    @property
    def species_rows(self) -> list[dict]:
        rows = self.taxonomy.get("ranks", {}).get("species", [])
        result = []
        for row in rows if isinstance(rows, list) else []:
            value = finite(row.get("abundance"))
            if value is not None and value >= 0:
                result.append({**row, "name": str(row.get("name") or row.get("species") or ""), "value": value})
        return result

    @property
    def classified_total(self) -> float:
        return sum(row["value"] for row in self.species_rows)

    @property
    def healthy_comparison(self) -> dict:
        value = self.template_inputs.get("healthy_comparison")
        return value if isinstance(value, dict) else {}

    @property
    def healthy_rows(self) -> list[dict]:
        rows = self.healthy_comparison.get("species", [])
        return rows if isinstance(rows, list) else []

    def healthy_by_key(self) -> dict[str, dict]:
        result = {}
        for row in self.healthy_rows:
            name = row.get("species") or row.get("name") or row.get("label")
            if name:
                result[canonical(str(name))] = row
        return result

    @property
    def reference_n(self) -> int | None:
        """Number of healthy reference subjects actually used for this sample."""
        audit = self.healthy_comparison.get("audit")
        value = audit.get("n_subjects") if isinstance(audit, dict) else None
        if not value:
            value = next((row.get("n_reference") for row in self.healthy_rows if row.get("n_reference")), None)
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    @property
    def cohort(self) -> dict:
        """Cohort-model results (gut age, enterotype, health index, disease references).

        Prefer the copy saved with the professional report; older reports are
        analysed on the fly from the same independent profile and bundle.
        """
        if self._cohort is None:
            value = self.template_inputs.get("cohort_insights")
            if not (isinstance(value, dict) and isinstance(value.get("audit"), dict)):
                from wgs_agent.reporting.reference import cohort_insights_for
                value = cohort_insights_for(self.sample_id, self.metadata) if self.sample_id else {}
            self._cohort = value if isinstance(value, dict) else {}
        return self._cohort

    @property
    def cohort_available(self) -> bool:
        audit = self.cohort.get("audit")
        return isinstance(audit, dict) and audit.get("status") == "available"

    def module(self, name: str) -> dict:
        value = self.template_inputs.get(name)
        return value if isinstance(value, dict) else {}

    def evidence(self, kind: str | None = None) -> list[dict]:
        rows = self.document.get("evidence", {})
        if not isinstance(rows, dict):
            return []
        if kind is None:
            return [row for row in rows.values() if isinstance(row, dict)]
        return [row for row in rows.values() if isinstance(row, dict) and row.get("kind") == kind]

    # -------------------------------------------------------------- omissions
    def omit(self, section: str, item: str, reason: str) -> None:
        if any(row["section"] == section and row["item"] == item for row in self.omissions):
            return
        self.omissions.append({"section": section, "item": item, "reason": reason})

    # ----------------------------------------------------------------- graphs
    def graph_for(self, topic_ids: list[str], seeds: list[str]) -> Any:
        graph, topics = self.graph.choose(topic_ids, seeds)
        if graph is None:
            self.omit("knowledge-graph", "知识子图", "清洗后的知识子图不足两条关系")
            return None
        graph.first_in_report = not self.first_graph_shown
        if not self.first_graph_shown:
            self.first_graph_shown = True
            self.glossary.used.add("knowledge_subgraph")
        graph.topic_ids = topics
        return graph

    # ----------------------------------------------------------------- naming
    def name(self, raw: str) -> str:
        return self.names.render(raw)

    def plain_name(self, raw: str) -> str:
        return self.names.plain(raw)

    def taxon_card(self, raw: str, value: float, *, text: str | None = None,
                   evidence_badge: str | None = None, reliability_badge: str | None = None) -> dict:
        record = self.names.taxon_card(raw)
        return {
            "name": record.display,
            "latin": record.latin,
            "first_mention": record.first_mention,
            "value": {"value": value, "display": _fmt_pct(value), "unit": "%"},
            "text": text,
            "evidence_badge": evidence_badge,
            "reliability_badge": reliability_badge,
        }

    # --------------------------------------------------------------- concepts
    def term(self, term_id: str, display: str | None = None) -> str:
        self.used_terms.add(term_id)
        return self.glossary.markup(term_id, display)

    # -------------------------------------------------------------- reference
    def maps(self) -> tuple[dict, dict]:
        return load_substrate_map(), load_vitamin_map()


def _fmt_pct(value: float) -> str:
    from ..format import pct
    return pct(value)
