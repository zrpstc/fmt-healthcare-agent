import test from "node:test";
import assert from "node:assert/strict";
import { parseRichText, buildNavItems, tierPosition, graphTextSummary, plainRichText, drawableGraph } from "../lib/consumer-pure.mjs";

test("rich text splits glossary terms and italic Latin names", () => {
  const tokens = parseRichText("菌群[[reference_population|参考人群]]中有*Faecalibacterium prausnitzii*。");
  assert.deepEqual(tokens, [
    { kind: "text", text: "菌群" },
    { kind: "term", termId: "reference_population", text: "参考人群" },
    { kind: "text", text: "中有" },
    { kind: "italic", text: "Faecalibacterium prausnitzii" },
    { kind: "text", text: "。" },
  ]);
  assert.equal(plainRichText("菌群[[reference_population|参考人群]]"), "菌群参考人群");
});

test("plain text with no markup is preserved", () => {
  assert.deepEqual(parseRichText("没有标记的句子。"), [{ kind: "text", text: "没有标记的句子。" }]);
});

test("navigation items follow section order and anchors", () => {
  const items = buildNavItems([
    { id: "composition", nav_label: "菌群组成" },
    { id: "diversity", nav_label: "多样性" },
  ]);
  assert.deepEqual(items, [
    { id: "composition", label: "菌群组成", href: "#composition" },
    { id: "diversity", label: "多样性", href: "#diversity" },
  ]);
});

test("tier position is bounded to the 0-100 track", () => {
  assert.equal(tierPosition({ percentile: 0 }), 0);
  assert.equal(tierPosition({ percentile: 100 }), 100);
  assert.equal(tierPosition({ percentile: 150 }), 100);
  assert.equal(tierPosition(null), null);
});

test("graph print summary uses Chinese endpoints and relation labels", () => {
  const lines = graphTextSummary({
    nodes: [{ id: "a", label: "普拉梭菌" }, { id: "b", label: "丁酸" }],
    edges: [{ from: "a", to: "b", label: "产生" }],
  });
  assert.deepEqual(lines, ["研究提示：普拉梭菌 — 产生 → 丁酸"]);
  assert.deepEqual(graphTextSummary(null), []);
});

test("drawableGraph drops dangling edges, duplicate ids and orphan nodes", () => {
  const graph = drawableGraph({
    nodes: [{ id: "a", label: "丁酸" }, { id: "b", label: "普拉梭菌" }, { id: "c", label: "孤立节点" }],
    edges: [
      { id: "e1", from: "b", to: "a", label: "产生" },
      { id: "e1", from: "a", to: "b", label: "相关" },
      { id: "e2", from: "b", to: "missing", label: "相关" },
    ],
  });
  assert.equal(graph.edges.length, 2);
  assert.equal(new Set(graph.edges.map((edge) => edge.id)).size, 2);
  assert.deepEqual(graph.nodes.map((node) => node.id).sort(), ["a", "b"]);
});

test("drawableGraph returns null when nothing can be drawn", () => {
  assert.equal(drawableGraph(null), null);
  assert.equal(drawableGraph({ nodes: [{ id: "a", label: "丁酸" }], edges: [] }), null);
  assert.equal(drawableGraph({ nodes: [], edges: [{ id: "e1", from: "a", to: "b", label: "产生" }] }), null);
});
