export type Tone = "good" | "neutral" | "watch" | "consult";
export type TierKey = "very_low" | "low" | "typical" | "high" | "very_high";

export interface Num { value: number | null; display: string; unit?: string }
export interface Tier {
  key: TierKey;
  label: string;
  tone: Tone;
  percentile: number;
  phrase: string;
  borderline: boolean;
}
export type RichText = string;

export interface StatusCard {
  id: string; label: string; tier_label: string; tone: Tone; line: RichText; anchor: string;
}
export interface FindingCard {
  rank: number; tone: Tone; title: string; big: Num; compare: string; meaning: RichText; anchor: string;
}
export interface Summary {
  headline: RichText; headline_source: "rule" | "llm";
  status_cards: StatusCard[]; key_findings: FindingCard[];
}
export interface TaxonCard {
  name: string; latin?: string; first_mention: boolean; value: Num; text?: RichText;
  evidence_badge?: string; reliability_badge?: string;
}
export interface GraphNode { id: string; label: string; type: string }
export interface GraphEvidence { sentence: string; ref_id: string }
export interface GraphEdge {
  id: string; from: string; to: string; label: string;
  status: "approved" | "pending"; evidence: GraphEvidence[];
}
export interface GraphBlock {
  nodes: GraphNode[]; edges: GraphEdge[]; seeds: string[]; topic_ids: string[]; first_in_report: boolean;
}
export interface BlockBase { type: string }
export interface ParagraphBlock extends BlockBase { type: "paragraph"; text: RichText }
export interface CalloutBlock extends BlockBase { type: "callout"; tone: Tone; text: RichText }
export interface StackedSegment { label: string; value: Num; note?: RichText; color_key: string }
export interface StackedBarBlock extends BlockBase { type: "stacked_bar"; segments: StackedSegment[] }
export interface RankedRow { label: string; latin?: string; value: Num; tone?: Tone }
export interface RankedBarsBlock extends BlockBase { type: "ranked_bars"; rows: RankedRow[] }
export interface TierRow { label: string; value: Num; tier: Tier; note?: RichText }
export interface TierScalesBlock extends BlockBase { type: "tier_scales"; rows: TierRow[] }
export interface TaxonCardsBlock extends BlockBase { type: "taxon_cards"; cards: TaxonCard[] }
export interface CategoryCallout { tone: Tone; text: RichText }
export interface CategoryCard {
  title: string; text: RichText; total?: Num; tier?: Tier; members: TaxonCard[];
  absent_text?: string; callout?: CategoryCallout;
}
export interface CategoryCardsBlock extends BlockBase { type: "category_cards"; cards: CategoryCard[] }
export interface Stage { title: string; members: string[]; more: number; backup_label: string; meaning: RichText }
export interface StageFlowBlock extends BlockBase { type: "stage_flow"; stages: Stage[]; footnote: string }
export interface TableBlock extends BlockBase {
  type: "table"; columns: string[]; rows: RichText[][]; footnote?: string;
}
export interface MetaboliteCard {
  title: string; text: RichText; status: string; tone: Tone; tier?: Tier; members?: string[];
}
export interface CardGridBlock extends BlockBase { type: "card_grid"; cards: MetaboliteCard[] }
export interface ScatterBlock extends BlockBase {
  type: "scatter"; points: [number, number][]; you: [number, number]; caption: string;
}
export type Block =
  | ParagraphBlock | CalloutBlock | StackedBarBlock | RankedBarsBlock | TierScalesBlock
  | TaxonCardsBlock | CategoryCardsBlock | StageFlowBlock | TableBlock | CardGridBlock | ScatterBlock;

export interface Subsection {
  id: string; title: string; blocks: Block[]; summary?: RichText; summary_source?: "rule" | "llm"; graph?: GraphBlock;
}
export interface Section {
  id: string; nav_label: string; title: string; intro?: RichText; source_chapters: number[];
  terms_banner: string[]; subsections: Subsection[];
}
export interface Action {
  finding_code: string; because: string; title: string; how: RichText; examples?: string[];
}
export interface Retest { months: number; focus: string[] }
export interface GlossaryEntry {
  term_id: string; name: string; latin?: string; text: string; evidence_badge?: string; source_ids: string[];
}
export interface Reference { id: string; title: string; year?: number; doi?: string; url?: string }
export interface Omission { section: string; item: string; reason: string }
export interface MethodNote { section: string; title: string; body: string }
export interface Download { kind: string; label: string; href: string }
export interface SampleMeta {
  sample_id: string; alias: string; report_date: string; generated_at: string;
  source_report_sha256: string; builder_version: string;
}
export interface ConsumerReport {
  schema_version: "consumer-report/1";
  sample: SampleMeta;
  summary: Summary;
  sections: Section[];
  actions: Action[];
  retest: Retest | null;
  red_flags: string[];
  glossary: GlossaryEntry[];
  references: Reference[];
  omissions: Omission[];
  methods: MethodNote[];
  downloads: Download[];
}
export interface ShareLink {
  id: string; created_at: string; expires_at: string; revoked_at: string | null; last_accessed_at: string | null;
}
export interface ShareCreation { token: string; url: string; expires_at: string; id: string }
export interface ReviewEntry {
  term_id: string; field: "one_liner" | "watch_note"; generated_text: string; name: string;
  status: string; sources: Array<{ title?: string; id_or_url?: string; year?: number | null }>;
  model: string; version: string; samples_used: string[];
}
