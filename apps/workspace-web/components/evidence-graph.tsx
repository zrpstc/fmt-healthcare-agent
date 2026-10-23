"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CircleDot, Download, Maximize2, Minus, Plus, RefreshCw } from "lucide-react";
import type { Network, Options, Node as VisNode, Edge as VisEdge } from "vis-network";
import type { GraphEdge, KnowledgeGraph } from "@/lib/api";

// The canonical LitKG FMT_use palette; pale node fills keep labels readable.
export const ENTITY_COLORS: Record<string, string> = {
  Compound: "#F97316", Drug: "#FB7185", Protein: "#3B82F6", Gene: "#6366F1",
  Disease: "#EF4444", CellLine: "#14B8A6", CellType: "#115E59", Tissue: "#D4A373",
  AnatomicalStructure: "#7C3E19", RNA: "#A3E635", MolecularComplex: "#3730A3",
  BiologicalProcess: "#A16207", Phenotype: "#C026D3", Organism: "#22C55E",
  Assay: "#EAB308", Pathway: "#8B5CF6", Mutation: "#EC4899", MicrobialTaxon: "#06B6D4",
  MicrobialStrain: "#0E7490", MicrobialCommunity: "#84CC16", Microbiome: "#047857",
  SequenceFeature: "#FACC15", Genome: "#1E3A8A", Metabolite: "#FDBA74", Diet: "#BE123C",
  DietaryComponent: "#C4B5FD", Intervention: "#0284C7", Biospecimen: "#78716C",
  StudyGroup: "#475569", ExperimentalModel: "#A78BFA", Environment: "#4D7C0F",
  ClinicalOutcome: "#FDA4AF", MicrobialFunction: "#713F12", DiversityMetric: "#D946EF", Other: "#94A3B8",
};
export const ENTITY_LABELS: Record<string, string> = {
  Compound: "化合物", Drug: "药物", Protein: "蛋白质", Gene: "基因", Disease: "疾病",
  CellLine: "细胞系", CellType: "细胞类型", Tissue: "组织", AnatomicalStructure: "解剖结构",
  RNA: "RNA", MolecularComplex: "分子复合物", BiologicalProcess: "生物过程", Phenotype: "表型",
  Organism: "生物体", Assay: "检测方法", Pathway: "通路", Mutation: "突变",
  MicrobialTaxon: "微生物分类单元", MicrobialStrain: "微生物菌株", MicrobialCommunity: "微生物群落",
  Microbiome: "微生物组", SequenceFeature: "序列特征", Genome: "基因组", Metabolite: "代谢物",
  Diet: "饮食", DietaryComponent: "膳食成分", Intervention: "干预", Biospecimen: "生物样本",
  StudyGroup: "研究分组", ExperimentalModel: "实验模型", Environment: "环境",
  ClinicalOutcome: "临床结局", MicrobialFunction: "微生物功能", DiversityMetric: "多样性指标", Other: "其他",
};
const color = (type: string) => ENTITY_COLORS[type] || `hsl(${[...type].reduce((n, c) => (n * 31 + c.charCodeAt(0)) >>> 0, 0) % 360},65%,43%)`;
const wrap = (label: string, length = 26) => label.split("\n").flatMap(line => line.match(new RegExp(`.{1,${length}}`, "gu")) || [""]).join("\n");
const edgeColor = (edge: GraphEdge) => (edge.display_negated ?? edge.negated) ? "#DC2626" : edge.review_status === "pending" ? "#9333EA" : edge.result_status === "not_significant" ? "#0284C7" : edge.speculative ? "#D97706" : "#64748B";
const edgeFlags = (edge: GraphEdge) => [(edge.display_negated ?? edge.negated) && "否定", edge.speculative && "推测", edge.result_status === "not_significant" && "不显著", edge.review_status === "pending" && "待审核"].filter(Boolean).join(" · ");
type Layout = "force" | "hierarchy" | "circle";

function components(graph: KnowledgeGraph) {
  const adjacent = new Map(graph.nodes.map(node => [node.id, new Set<string | number>()]));
  graph.edges.forEach(edge => { adjacent.get(edge.source)?.add(edge.target); adjacent.get(edge.target)?.add(edge.source); });
  const remaining = new Set(graph.nodes.map(node => node.id));
  const groups: (string | number)[][] = [];
  while (remaining.size) {
    const queue = [remaining.values().next().value!]; remaining.delete(queue[0]);
    for (let i = 0; i < queue.length; i++) for (const neighbor of adjacent.get(queue[i]) || []) if (remaining.delete(neighbor)) queue.push(neighbor);
    groups.push(queue);
  }
  return groups.sort((a, b) => b.length - a.length);
}

function initialPositions(graph: KnowledgeGraph, layout: Layout, spacing: number) {
  const result = new Map<string | number, {x: number; y: number}>();
  let offset = 0;
  for (const ids of components(graph)) {
    if (layout === "circle") {
      const radius = ids.length === 1 ? 0 : Math.max(spacing, ids.length * spacing / (2 * Math.PI));
      ids.forEach((id, i) => result.set(id, { x: offset + radius + radius * Math.cos(i * 2 * Math.PI / ids.length), y: radius + radius * Math.sin(i * 2 * Math.PI / ids.length) }));
      offset += radius * 2 + 300;
      continue;
    }
    const members = new Set(ids);
    const outgoing = new Map(ids.map(id => [id, new Set<string | number>()]));
    const incoming = new Set<string | number>();
    graph.edges.forEach(edge => { if (members.has(edge.source) && members.has(edge.target) && edge.source !== edge.target) { outgoing.get(edge.source)!.add(edge.target); incoming.add(edge.target); } });
    const queue = ids.filter(id => !incoming.has(id));
    if (!queue.length) queue.push([...ids].sort((a, b) => outgoing.get(b)!.size - outgoing.get(a)!.size)[0]);
    const levels = new Map(queue.map(id => [id, 0]));
    let cursor = 0;
    while (levels.size < ids.length || cursor < queue.length) {
      if (cursor === queue.length) { const id = ids.find(id => !levels.has(id))!; levels.set(id, Math.max(...levels.values()) + 1); queue.push(id); }
      const id = queue[cursor++];
      for (const target of outgoing.get(id)!) if (!levels.has(target)) { levels.set(target, levels.get(id)! + 1); queue.push(target); }
    }
    const columns = new Map<number, (string | number)[]>();
    ids.forEach(id => { const level = levels.get(id)!; columns.set(level, [...(columns.get(level) || []), id]); });
    for (const [level, column] of columns) column.forEach((id, i) => result.set(id, { x: offset + level * (spacing + 200), y: (i - (column.length - 1) / 2) * 160 }));
    offset += (Math.max(...levels.values()) + 1) * (spacing + 200) + 300;
  }
  return result;
}

function packComponents(instance: Network, graph: KnowledgeGraph) {
  const positions = instance.getPositions();
  const blocks = components(graph).map(ids => {
    const boxes = ids.map(id => instance.getBoundingBox(id));
    const left = Math.min(...boxes.map(box => box.left)) - 70, top = Math.min(...boxes.map(box => box.top)) - 70;
    return { ids, left, top, width: Math.max(...boxes.map(box => box.right)) - left + 70, height: Math.max(...boxes.map(box => box.bottom)) - top + 70 };
  });
  const rowWidth = Math.max(...blocks.map(block => block.width), Math.sqrt(blocks.reduce((sum, block) => sum + block.width * block.height, 0)) * 1.25);
  let x = 0, y = 0, rowHeight = 0;
  for (const block of blocks) {
    if (x && x + block.width > rowWidth) { x = 0; y += rowHeight + 70; rowHeight = 0; }
    block.ids.forEach(id => instance.moveNode(id, positions[id].x - block.left + x, positions[id].y - block.top + y));
    x += block.width + 70; rowHeight = Math.max(rowHeight, block.height);
  }
}

export default function EvidenceGraph({ graph }: { graph: KnowledgeGraph }) {
  const container = useRef<HTMLDivElement>(null);
  const network = useRef<Network | null>(null);
  const renderData = useRef<{ nodes: VisNode[]; edges: VisEdge[] }>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<string | number | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | number | null>(null);
  const [layout, setLayout] = useState<Layout>("force");
  const [spacing, setSpacing] = useState(300);
  const [resolution, setResolution] = useState(1);
  const [arranging, setArranging] = useState(false);
  const [arrangement, setArrangement] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [message, setMessage] = useState("");
  const nodeMap = useMemo(() => new Map(graph.nodes.map(node => [node.id, node])), [graph]);
  const types = useMemo(() => [...new Set(graph.nodes.map(node => node.type || "Other"))].sort(), [graph]);
  const node = selected === null ? null : nodeMap.get(selected);
  const relations = selectedEdge !== null ? graph.edges.filter(edge => edge.id === selectedEdge) : node ? graph.edges.filter(edge => edge.source === node.id || edge.target === node.id) : [];

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setSelected(null); setSelectedEdge(null); setMessage("");
    if (!graph.nodes.length || !container.current) return;
    setArranging(true);
    import("vis-network/standalone").then(({ Network: VisNetwork }) => {
      if (cancelled || !container.current) return;
      const title = (value: string) => { const el = document.createElement("div"); el.style.whiteSpace = "pre-wrap"; el.textContent = value; return el; };
      const degree = new Map<string | number, number>();
      graph.edges.forEach(edge => { degree.set(edge.source, (degree.get(edge.source) || 0) + 1); degree.set(edge.target, (degree.get(edge.target) || 0) + 1); });
      const groups = new Map<string, GraphEdge[]>();
      graph.edges.forEach(edge => { const key = [String(edge.source), String(edge.target)].sort().join("|"); groups.set(key, [...(groups.get(key) || []), edge]); });
      const positions = initialPositions(graph, layout, spacing);
      const nodes = graph.nodes.map(row => {
        const border = color(row.type || "Other");
        return { id: row.id, label: wrap(row.label), shape: "box", margin: 12,
          ...positions.get(row.id),
          borderWidth: row.matched_features?.length ? 4 : 2,
          color: { border, background: ENTITY_COLORS[row.type] ? `${border}24` : "#f8fafc", highlight: { border, background: "#f1f5f9" } },
          title: title(`${row.label}\n${ENTITY_LABELS[row.type] || row.type} (${row.type})\n${row.normalized_id || "未规范化"}${row.matched_features?.length ? "\n匹配样本：" + row.matched_features.join("、") : ""}\n直接关系：${degree.get(row.id) || 0}`) };
      });
      const edges = graph.edges.map(row => {
        const siblings = groups.get([String(row.source), String(row.target)].sort().join("|")) || [];
        return { id: row.id, from: row.source, to: row.target,
          label: wrap(`${row.predicate || row.label}${edgeFlags(row) ? "\n[" + edgeFlags(row) + "]" : ""}`, 30),
          title: title(`${row.predicate || row.label}\n${edgeFlags(row)}\n${row.evidence || row.evidence_samples?.[0]?.sentence || ""}\n${row.match_reasons?.join("\n") || ""}`),
          color: { color: edgeColor(row), highlight: edgeColor(row), hover: edgeColor(row) },
          arrows: "to", dashes: !!(row.speculative || row.review_status === "pending"),
          width: Math.min(3, 1 + (row.document_count || 1) * .4),
          smooth: siblings.length > 1 ? { enabled: true, type: row.source === siblings[0].source ? "curvedCW" : "curvedCCW", roundness: .15 + siblings.indexOf(row) * .12 } : false,
        };
      });
      const options: Options = {
        layout: { randomSeed: 42, improvedLayout: false, hierarchical: false },
        nodes: { font: { size: 16, face: "Arial", color: "#111827" }, widthConstraint: { maximum: 230 }, shapeProperties: { borderRadius: 6 } },
        edges: { font: { size: 13, color: "#334155", background: "#ffffff", strokeWidth: 2, strokeColor: "#ffffff", align: "horizontal" }, smooth: false, arrowStrikethrough: false },
        physics: { enabled: layout === "force", barnesHut: { gravitationalConstant: -18000, centralGravity: .12, springLength: spacing, springConstant: .025, damping: .35, avoidOverlap: 1 }, stabilization: { enabled: true, iterations: 350 } },
        interaction: { hover: true, keyboard: { enabled: true, bindToWindow: false }, navigationButtons: false },
      };
      renderData.current = { nodes: nodes as VisNode[], edges: edges as VisEdge[] };
      const instance = new VisNetwork(container.current, renderData.current, options);
      network.current = instance;
      let frozen = false;
      const freeze = () => { if (cancelled || frozen) return; frozen = true; clearTimeout(timer); instance.setOptions({ physics: { enabled: false } }); instance.stopSimulation(); packComponents(instance, graph); setArranging(false); instance.fit({ animation: false }); setMessage("布局已固定，可拖动节点和画布；滚轮缩放，点击节点或关系查看证据。"); };
      instance.once("stabilizationIterationsDone", freeze);
      instance.on("click", event => { setSelected(event.nodes[0] ?? null); setSelectedEdge(event.nodes.length ? null : event.edges[0] ?? null); });
      if (layout !== "force") { instance.once("afterDrawing", freeze); timer = setTimeout(freeze, 1000); } else timer = setTimeout(freeze, 15000);
    }).catch(error => { if (!cancelled) { setArranging(false); setMessage(`图谱加载失败：${error.message}`); } });
    return () => { cancelled = true; clearTimeout(timer); network.current?.destroy(); network.current = null; };
  }, [graph, layout, spacing, arrangement]);

  async function exportImage() {
    if (!network.current || !container.current) return;
    setExporting(true); setMessage("正在生成完整白底 PNG…");
    let scratch: HTMLDivElement | undefined;
    let exportNetwork: Network | undefined;
    try {
      await document.fonts.ready;
      const current = network.current;
      const positions = current.getPositions();
      const boxes = graph.nodes.map(node => current.getBoundingBox(node.id));
      // Include curved parallel edges, self loops and full multiline relation labels.
      const padding = Math.max(350, ...graph.edges.map(edge => {
        const a = positions[edge.source], b = positions[edge.target];
        return a && b ? Math.hypot(a.x - b.x, a.y - b.y) * .55 + 200 : 350;
      }));
      const left = Math.min(...boxes.map(b => b.left)) - padding;
      const top = Math.min(...boxes.map(b => b.top)) - padding;
      const width = Math.ceil(Math.max(...boxes.map(b => b.right)) + padding - left);
      const height = Math.ceil(Math.max(...boxes.map(b => b.bottom)) + padding - top);
      const footer = 60 + Math.ceil(types.length / 4) * 30;
      if (width * resolution > 32767 || (height + footer) * resolution > 32767 || width * (height + footer) * resolution ** 2 > 64000000) throw new Error("图幅过大，请选择 1× 清晰度或减少关系数后导出。");
      const { Network: VisNetwork } = await import("vis-network/standalone");
      const ratio = resolution / (window.devicePixelRatio || 1);
      scratch = document.createElement("div");
      scratch.style.cssText = `position:fixed;left:-100000px;top:0;width:${width * ratio}px;height:${height * ratio}px;pointer-events:none`;
      document.body.appendChild(scratch);
      exportNetwork = new VisNetwork(scratch, {
        nodes: renderData.current.nodes.map(node => ({ ...node, ...positions[node.id!], physics: false })), edges: renderData.current.edges,
      }, { physics: { enabled: false }, nodes: { font: { size: 16, face: "Arial", color: "#111827" }, widthConstraint: { maximum: 230 } }, edges: { font: { size: 13, background: "#ffffff", color: "#334155" } }, interaction: { dragNodes: false, dragView: false, zoomView: false } });
      exportNetwork.moveTo({ position: { x: left + width / 2, y: top + height / 2 }, scale: ratio, animation: false });
      exportNetwork.redraw();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const source = scratch.querySelector("canvas");
      if (!source) throw new Error("无法创建图谱画布。");
      const output = document.createElement("canvas");
      output.width = width * resolution; output.height = (height + footer) * resolution;
      const ctx = output.getContext("2d");
      if (!ctx) throw new Error("浏览器无法创建导出画布。");
      ctx.scale(resolution, resolution); ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, width, height + footer);
      ctx.drawImage(source, 0, 0, width, height);
      ctx.font = "bold 18px Arial"; ctx.fillStyle = "#111827";
      ctx.fillText(graph.sample_id ? `样本 ${graph.sample_id} · 最相关知识子图` : "LitKG 证据知识图谱", 24, height + 25);
      ctx.font = "14px Arial";
      types.forEach((type, index) => { const x = 24 + index % 4 * ((width - 48) / 4), y = height + 56 + Math.floor(index / 4) * 30; ctx.fillStyle = color(type); ctx.fillRect(x, y - 10, 12, 12); ctx.fillStyle = "#334155"; ctx.fillText(`${ENTITY_LABELS[type] || type} (${type})`, x + 20, y); });
      const blob = await new Promise<Blob>((resolve, reject) => output.toBlob(value => value ? resolve(value) : reject(new Error("PNG 编码失败，请降低清晰度。")), "image/png"));
      const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `litkg-${graph.sample_id || graph.document_id || "knowledge"}.png`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`已导出 ${output.width} × ${output.height} 完整白底 PNG。`);
    } catch (error) { setMessage((error as Error).message); }
    finally { exportNetwork?.destroy(); scratch?.remove(); setExporting(false); }
  }

  if (!graph.edges.length) return <div className="graph-loading"><CircleDot size={30}/><strong>{graph.sample_id ? "未匹配到该样本的相关知识关系" : "当前筛选范围没有可展示的关系"}</strong><span>可调整筛选条件，或为样本绑定实际证据后重试。</span></div>;
  return <div className="evidence-graph">
    <div className="evidence-graph-legend" aria-label="实体类别图例">{types.map(type => <span key={type} title={type}><i style={{ background: color(type) }}/>{ENTITY_LABELS[type] || type}<small>{type}</small><b>{graph.nodes.filter(node => (node.type || "Other") === type).length}</b></span>)}</div>
    <div className="evidence-graph-toolbar">
      <label>布局<select value={layout} onChange={e => setLayout(e.target.value as Layout)}><option value="force">力导向布局</option><option value="hierarchy">层次布局</option><option value="circle">环形布局</option></select></label>
      <label>节点间距<select value={spacing} onChange={e => setSpacing(Number(e.target.value))}><option value={220}>紧凑</option><option value={300}>标准</option><option value={460}>宽松</option></select></label>
      <button onClick={() => setArrangement(value => value + 1)} disabled={arranging || layout !== "force"}><RefreshCw size={13}/>{arranging ? "整理中…" : "重新整理"}</button>
      <button onClick={() => network.current?.fit({ animation: true })}><Maximize2 size={13}/>适应画布</button>
      <button aria-label="放大图谱" onClick={() => { const n = network.current; if (n) n.moveTo({ scale: n.getScale() * 1.25 }); }}><Plus size={13}/></button>
      <button aria-label="缩小图谱" onClick={() => { const n = network.current; if (n) n.moveTo({ scale: n.getScale() / 1.25 }); }}><Minus size={13}/></button>
      <label>清晰度<select value={resolution} onChange={e => setResolution(Number(e.target.value))}><option value={1}>1×</option><option value={2}>2×</option><option value={3}>3×</option></select></label>
      <button onClick={exportImage} disabled={exporting || arranging}><Download size={13}/>{exporting ? "导出中…" : "下载 PNG"}</button>
    </div>
    <div className="graph-workbench evidence-graph-workbench"><div ref={container} className="evidence-network" aria-label="可交互的证据知识图谱" tabIndex={0}/>
      <aside className="graph-inspector evidence-inspector">{node || selectedEdge !== null ? <>
        {node ? <><div className="node-type"><i style={{ background: color(node.type) }}/>{ENTITY_LABELS[node.type] || node.type} · {node.type}</div><h3>{node.label}</h3><p>{node.normalized_id || `实体 ${node.id}`}</p>{!!node.matched_features?.length && <p className="sample-match-tag">样本检测实体：{node.matched_features.join("、")}</p>}</> : <h3>关系详情</h3>}
        <h4>{relations.length} 条关联关系</h4><div className="relation-list">{relations.map(edge => <article key={edge.id}>
          <strong>{nodeMap.get(edge.source)?.label} → {nodeMap.get(edge.target)?.label}</strong><b style={{ color: edgeColor(edge) }}>{edge.predicate || edge.label}</b>
          {edgeFlags(edge) && <em>{edgeFlags(edge)}</em>}{edge.match_reasons && <div className="match-reasons"><strong>关联分 {edge.relevance_score}</strong>{edge.match_reasons.map(reason => <span key={reason}>{reason}</span>)}</div>}
          <p>{edge.evidence || edge.evidence_samples?.[0]?.sentence || "该关系的原句见下方来源。"}</p>
          <small>{edge.evidence_count || 0} 条证据 · {edge.document_count || 0} 篇文献 · 置信度 {edge.confidence == null ? "未提供" : Number(edge.confidence).toFixed(2)}</small>
          {!!edge.evidence_samples?.length && <details><summary>证据来源与原句</summary>{edge.evidence_samples.map((sample, i) => <div key={i}><strong>{sample.title || sample.filename || `文档 ${sample.document_id ?? "未知"}`}</strong><small>Claim {sample.claim_id ?? edge.claim_id ?? "—"} · 页码 {sample.page ?? "未提供"}</small>{sample.doi && <a target="_blank" rel="noreferrer" href={`https://doi.org/${encodeURI(sample.doi)}`}>DOI: {sample.doi}</a>}<p>{sample.sentence || "未提供原句"}</p></div>)}</details>}
          {edge.qualifiers && Object.keys(edge.qualifiers).length > 0 && <details><summary>限定条件</summary><pre>{JSON.stringify(edge.qualifiers, null, 2)}</pre></details>}
        </article>)}</div>
      </> : <div className="graph-empty"><CircleDot size={27}/><strong>选择实体或关系</strong><span>查看实体类别、原始证据、限定条件与样本匹配依据。粗边框标出样本检测实体。</span></div>}</aside>
    </div><div className="evidence-graph-status" role="status">{message}<span>实线：已陈述关系 · 虚线：推测／待审核 · 红色：否定 · 蓝色：不显著</span></div>
  </div>;
}
