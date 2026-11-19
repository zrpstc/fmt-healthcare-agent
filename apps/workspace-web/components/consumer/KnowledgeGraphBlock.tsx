"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import type { Network, Options, Node as VisNode, Edge as VisEdge } from "vis-network";
import { ENTITY_COLORS } from "@/components/evidence-graph";
import { drawableGraph, graphTextSummary } from "@/lib/consumer-pure.mjs";
import { useDismiss } from "./useDismiss";
import type { GraphBlock, Reference, GlossaryEntry } from "@/lib/consumer-report";

function edgeColor(edge: GraphBlock["edges"][number]) {
  return edge.status === "pending" ? "#9A5410" : "#45606A";
}

export default function KnowledgeGraphBlock({
  graph: rawGraph,
  references,
  glossary,
}: {
  graph: GraphBlock;
  references: Reference[];
  glossary: GlossaryEntry[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [mounted, setMounted] = useState(false);
  const [selectedEdge, setSelectedEdge] = useState<GraphBlock["edges"][number] | null>(null);
  const [failed, setFailed] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  // Clicks on the graph canvas pick another edge, so they do not count as outside.
  // Closing also clears the edge selection, otherwise clicking the same edge
  // again would not fire a new selectEdge event and the drawer would not reopen.
  const closeDrawer = () => {
    setSelectedEdge(null);
    networkRef.current?.unselectAll();
  };
  useDismiss(selectedEdge !== null, [drawerRef, containerRef], closeDrawer);
  const graph = useMemo(() => drawableGraph(rawGraph), [rawGraph]);
  const refMap = new Map(references.map((item) => [item.id, item]));
  const note = glossary.find((entry) => entry.term_id === "knowledge_subgraph");
  const fallback = graphTextSummary(graph);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || !graph) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setMounted(true);
      },
      { rootMargin: "200px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [graph]);

  useEffect(() => {
    if (!mounted || !containerRef.current || !graph) return;
    let cancelled = false;
    import("vis-network/standalone").then(({ Network: NetworkClass }) => {
      if (cancelled || !containerRef.current) return;
      const nodes = graph.nodes.map((node) => ({
        id: node.id,
        label: node.label,
        shape: "box",
        margin: 10,
        borderWidth: 1,
        color: {
          border: ENTITY_COLORS[node.type] || "#45606A",
          background: ENTITY_COLORS[node.type] ? `${ENTITY_COLORS[node.type]}22` : "#F3F0E8",
        },
        font: { size: 14, face: "PingFang SC, Noto Sans SC, Microsoft YaHei, sans-serif", color: "#1C2629" },
      })) as VisNode[];
      const edges = graph.edges.map((edge) => ({
        id: edge.id,
        from: edge.from,
        to: edge.to,
        label: edge.label,
        color: { color: edgeColor(edge), highlight: edgeColor(edge) },
        arrows: "to",
        dashes: edge.status === "pending",
        width: 1.4,
        font: { size: 12, face: "PingFang SC, Noto Sans SC, Microsoft YaHei, sans-serif", color: "#45606A", background: "#fff" },
      })) as VisEdge[];
      const options: Options = {
        layout: { randomSeed: 42, improvedLayout: true },
        physics: { enabled: true, stabilization: { enabled: true, iterations: 180 }, barnesHut: { gravitationalConstant: -6000, springLength: 150 } },
        interaction: { hover: true, dragView: true, zoomView: false },
        nodes: { shapeProperties: { borderRadius: 8 }, widthConstraint: { maximum: 180 } },
        edges: { smooth: false, arrowStrikethrough: false },
      };
      let network: Network;
      try {
        network = new NetworkClass(containerRef.current, { nodes, edges }, options);
      } catch (error) {
        console.error("knowledge subgraph render failed", error);
        setFailed(true);
        return;
      }
      networkRef.current = network;
      network.on("selectEdge", (params) => {
        if (!params.edges.length) return;
        const id = String(params.edges[0]);
        const edge = graph.edges.find((item) => item.id === id) || null;
        setSelectedEdge(edge);
      });
      // Clicking empty canvas deselects the edge; close its evidence drawer too.
      network.on("deselectEdge", () => setSelectedEdge(null));
      network.once("stabilizationIterationsDone", () => {
        network.setOptions({ physics: { enabled: false } });
      });
    }).catch((error) => {
      if (cancelled) return;
      console.error("knowledge subgraph render failed", error);
      setFailed(true);
    });
    return () => {
      cancelled = true;
      networkRef.current?.destroy();
      networkRef.current = null;
    };
  }, [mounted, graph]);

  // A subgraph with nothing drawable (or one the graph library rejected) is
  // hidden entirely: no heading, empty canvas or legend.
  if (!graph || failed) return null;

  const firstEvidence = selectedEdge?.evidence?.[0];
  const reference = firstEvidence ? refMap.get(firstEvidence.ref_id) : undefined;

  return (
    <section className="cr-graph">
      <div className="cr-graph-head">
        <h4>与本部分相关的知识子图</h4>
        <span>{graph.topic_ids.length ? "已发表研究关系" : ""}</span>
      </div>
      {graph.first_in_report && note && (
        <p className="cr-graph-note">{note.text}</p>
      )}
      <div ref={containerRef} className="cr-graph-stage" aria-label="知识子图交互区域" />
      <div className="cr-graph-legend">
        <span><b />实线：已核对</span>
        <span><i />虚线：尚待人工核对的研究结论</span>
      </div>
      <div className="cr-graph-fallback">
        <ul>{fallback.map((line) => <li key={line}>{line}</li>)}</ul>
      </div>
      {selectedEdge && (
        <div ref={drawerRef} className="cr-graph-drawer" role="dialog" aria-label="关系证据">
          <button type="button" className="cr-drawer-close" onClick={closeDrawer} aria-label="关闭">
            <X size={18} />
          </button>
          <h4>{selectedEdge.label}</h4>
          <p>{firstEvidence?.sentence || "该关系没有可读的证据句。"}</p>
          {reference && (
            <p style={{ fontSize: 12 }}>
              {reference.title}{reference.year ? `（${reference.year}）` : ""}{reference.doi ? ` · DOI: ${reference.doi}` : ""}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
