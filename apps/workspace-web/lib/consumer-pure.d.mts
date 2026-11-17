export type RichToken =
  | { kind: "text"; text: string }
  | { kind: "term"; termId: string; text: string }
  | { kind: "italic"; text: string };

export function parseRichText(text: string): RichToken[];
export function buildNavItems(sections: Array<{ id: string; nav_label: string }>): Array<{ id: string; label: string; href: string }>;
export function currentSectionFromEntries(entries: IntersectionObserverEntry[]): string | null;
export function tierPosition(tier: { percentile: number } | null | undefined): number | null;
export function drawableGraph<T extends { nodes: Array<{ id: string; label: string }>; edges: Array<{ id: string; from: string; to: string }> }>(graph: T | null | undefined): T | null;
export function graphTextSummary(graph: { nodes: Array<{ id: string; label: string }>; edges: Array<{ from: string; to: string; label: string }> } | null | undefined): string[];
export function plainRichText(text: string): string;
