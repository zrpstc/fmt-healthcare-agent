// Pure browser-side helpers. Kept in a plain ES module so `node --test` can
// exercise them without adding a runtime dependency or a TS loader.

export function parseRichText(text) {
  const source = String(text || "");
  const tokens = [];
  const pattern = /\[\[([A-Za-z0-9_.:-]+)\|([^\]]+)\]\]|\*([^*]+)\*/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(source))) {
    if (match.index > last) tokens.push({ kind: "text", text: source.slice(last, match.index) });
    if (match[1]) tokens.push({ kind: "term", termId: match[1], text: match[2] });
    else tokens.push({ kind: "italic", text: match[3] });
    last = match.index + match[0].length;
  }
  if (last < source.length) tokens.push({ kind: "text", text: source.slice(last) });
  return tokens;
}

export function buildNavItems(sections) {
  return (sections || []).map((section) => ({
    id: section.id,
    label: section.nav_label,
    href: `#${section.id}`,
  }));
}

export function currentSectionFromEntries(entries) {
  const visible = entries
    .filter((entry) => entry.isIntersecting && entry.intersectionRatio > 0.12)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
  return visible[0]?.target?.id || null;
}

export function tierPosition(tier) {
  if (!tier) return null;
  const value = Number(tier.percentile);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
}

/**
 * Keep only drawable parts of a knowledge subgraph: edges with a unique id whose
 * both ends exist, and nodes that still have at least one edge.  Returns null
 * when nothing drawable remains, so the caller can hide the whole widget.
 */
export function drawableGraph(graph) {
  if (!graph) return null;
  const nodeById = new Map();
  for (const node of graph.nodes || []) {
    if (node && node.id && String(node.label || "").trim() && !nodeById.has(node.id)) nodeById.set(node.id, node);
  }
  const edgeIds = new Set();
  const edges = [];
  for (const edge of graph.edges || []) {
    if (!edge || !nodeById.has(edge.from) || !nodeById.has(edge.to)) continue;
    let id = String(edge.id || "");
    if (!id || edgeIds.has(id)) id = `${id || "edge"}#${edges.length}`;
    edgeIds.add(id);
    edges.push({ ...edge, id });
  }
  if (!edges.length) return null;
  const linked = new Set(edges.flatMap((edge) => [edge.from, edge.to]));
  const nodes = [...nodeById.values()].filter((node) => linked.has(node.id));
  return { ...graph, nodes, edges };
}

export function graphTextSummary(graph) {
  if (!graph) return [];
  const nodes = new Map((graph.nodes || []).map((node) => [node.id, node.label]));
  return (graph.edges || []).map((edge) => {
    const from = nodes.get(edge.from) || "起点";
    const to = nodes.get(edge.to) || "终点";
    return `研究提示：${from} — ${edge.label} → ${to}`;
  });
}

export function plainRichText(text) {
  return parseRichText(text).map((token) => token.text).join("");
}
