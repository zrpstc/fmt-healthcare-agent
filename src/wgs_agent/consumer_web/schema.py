"""Pydantic v2 contract for ``consumer-report/1``.

All business numbers are formatted in Python.  The frontend must render the
``display`` string and must never call ``toFixed`` on a business value.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Tone = Literal["good", "neutral", "watch", "consult"]
TierKey = Literal["very_low", "low", "typical", "high", "very_high"]
HeadlineSource = Literal["rule", "llm"]


class Num(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None
    display: str
    unit: str | None = None


class Tier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: TierKey
    label: str
    tone: Tone
    percentile: float
    phrase: str
    borderline: bool = False


class TaxonCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    latin: str | None = None
    first_mention: bool = False
    value: Num
    text: str | None = None
    evidence_badge: str | None = None
    reliability_badge: str | None = None


class GraphEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str
    ref_id: str


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: str


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    from_: str = Field(alias="from")
    to: str
    label: str
    status: Literal["approved", "pending"]
    evidence: list[GraphEvidence] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GraphBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    seeds: list[str]
    topic_ids: list[str]
    first_in_report: bool = False


class ParagraphBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["paragraph"] = "paragraph"
    text: str


class CalloutBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["callout"] = "callout"
    tone: Tone
    text: str


class StackedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: Num
    note: str | None = None
    color_key: str


class StackedBarBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["stacked_bar"] = "stacked_bar"
    segments: list[StackedSegment]


class DonutBlock(BaseModel):
    """Ring chart of parts of a whole; geometry is drawn by the frontend."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["donut"] = "donut"
    title: str
    caption: str | None = None
    center_label: str | None = None
    center_value: str | None = None
    segments: list[StackedSegment]


class RankedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    latin: str | None = None
    value: Num
    tone: Tone | None = None


class ChartAxis(BaseModel):
    """Axis captions and preformatted tick labels for a bar chart."""

    model_config = ConfigDict(extra="forbid")

    category_label: str
    value_label: str
    ticks: list[Num] = Field(default_factory=list)


class RankedBarsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ranked_bars"] = "ranked_bars"
    title: str | None = None
    caption: str | None = None
    axis: ChartAxis | None = None
    rows: list[RankedRow]


class TierRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: Num
    tier: Tier | None = None
    note: str | None = None


class TierScalesBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tier_scales"] = "tier_scales"
    rows: list[TierRow]


class TaxonCardsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["taxon_cards"] = "taxon_cards"
    cards: list[TaxonCard]


class CategoryCallout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone: Tone
    text: str


class CategoryCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    text: str
    total: Num | None = None
    tier: Tier | None = None
    members: list[TaxonCard] = Field(default_factory=list)
    absent_text: str | None = None
    callout: CategoryCallout | None = None


class CategoryCardsBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["category_cards"] = "category_cards"
    cards: list[CategoryCard]


class StageMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: Num | None = None
    # gene: stratified functional annotation; taxonomy: known trait of a detected taxon
    basis: Literal["gene", "taxonomy"] = "gene"


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    members: list[str]
    more: int = 0
    backup_label: str
    meaning: str
    member_details: list[StageMember] = Field(default_factory=list)


class StageFlowBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["stage_flow"] = "stage_flow"
    stages: list[Stage]
    footnote: str


class TableBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    footnote: str | None = None


class DetailRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    text: str


class MetaboliteCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    text: str
    status: str
    tone: Tone
    tier: Tier | None = None
    members: list[str] | None = None
    score: Num | None = None
    score_label: str | None = None
    details: list[DetailRow] | None = None


class CardGridBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["card_grid"] = "card_grid"
    cards: list[MetaboliteCard]


class ScatterBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["scatter"] = "scatter"
    points: list[tuple[float, float]]
    you: tuple[float, float]
    caption: str


Block = Annotated[
    Union[
        ParagraphBlock,
        CalloutBlock,
        StackedBarBlock,
        DonutBlock,
        RankedBarsBlock,
        TierScalesBlock,
        TaxonCardsBlock,
        CategoryCardsBlock,
        StageFlowBlock,
        TableBlock,
        CardGridBlock,
        ScatterBlock,
    ],
    Field(discriminator="type"),
]


class Subsection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    blocks: list[Block] = Field(default_factory=list)
    summary: str | None = None
    summary_source: HeadlineSource | None = None
    graph: GraphBlock | None = None


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    nav_label: str
    title: str
    intro: str | None = None
    source_chapters: list[int] = Field(default_factory=list)
    terms_banner: list[str] = Field(default_factory=list)
    subsections: list[Subsection] = Field(default_factory=list)


class StatusCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    tier_label: str
    tone: Tone
    line: str
    anchor: str


class FindingCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    tone: Tone
    title: str
    big: Num
    compare: str
    meaning: str
    anchor: str


class Assessment(BaseModel):
    """Overall rule-based verdict shown on the overview (pathogen / nutrition)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    verdict: str
    tone: Tone
    text: str
    points: list[str] = Field(default_factory=list)
    anchor: str


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    headline_source: HeadlineSource
    status_cards: list[StatusCard] = Field(default_factory=list)
    key_findings: list[FindingCard] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)


class SampleMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    alias: str
    report_date: str
    generated_at: str
    source_report_sha256: str
    builder_version: str


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_code: str
    because: str
    title: str
    how: str
    examples: list[str] | None = None


class Retest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int
    focus: list[str] = Field(default_factory=list)


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_id: str
    name: str
    latin: str | None = None
    text: str
    evidence_badge: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    year: int | None = None
    doi: str | None = None
    url: str | None = None


class Omission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    item: str
    reason: str


class MethodNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    title: str
    body: str


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    label: str
    href: str


class ConsumerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["consumer-report/1"] = "consumer-report/1"
    sample: SampleMeta
    summary: Summary
    sections: list[Section] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    retest: Retest | None = None
    red_flags: list[str] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    omissions: list[Omission] = Field(default_factory=list)
    methods: list[MethodNote] = Field(default_factory=list)
    downloads: list[Download] = Field(default_factory=list)


def export_schema() -> dict:
    """Return the canonical JSON Schema for the report."""
    return ConsumerReport.model_json_schema()
