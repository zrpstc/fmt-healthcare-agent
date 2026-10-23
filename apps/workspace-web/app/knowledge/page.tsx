"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowUpRight, BookOpen, CheckCircle2, CircleDot, Database, FileSearch, GitBranch, Link2, Network, RefreshCw, Search, Server, X } from "lucide-react";
import { api, SampleSummary, KnowledgeGraph, KnowledgeStats, LitkgDocument, LitkgStatus, Paper } from "@/lib/api";

import EvidenceGraph, { ENTITY_COLORS, ENTITY_LABELS } from "@/components/evidence-graph";

type Mode="graph"|"sample"|"interface"|"local";
export default function KnowledgePage(){
  const [mode,setMode]=useState<Mode>("graph"); const [status,setStatus]=useState<LitkgStatus|null>(null); const [documents,setDocuments]=useState<LitkgDocument[]>([]); const [graph,setGraph]=useState<KnowledgeGraph|null>(null);
  const [graphDocument,setGraphDocument]=useState(""); const [entityType,setEntityType]=useState(""); const [predicate,setPredicate]=useState(""); const [graphLoading,setGraphLoading]=useState(true);
  const [claimQuery,setClaimQuery]=useState(""); const [claims,setClaims]=useState<Array<Record<string,any>>>([]); const [claimLoading,setClaimLoading]=useState(false); const [sampleId,setSampleId]=useState(""); const [bindMessage,setBindMessage]=useState("");
  const [stats,setStats]=useState<KnowledgeStats|null>(null); const [papers,setPapers]=useState<Paper[]>([]); const [paperCount,setPaperCount]=useState(0); const [localQuery,setLocalQuery]=useState(""); const [selectedPaper,setSelectedPaper]=useState<Paper|null>(null);
  const [loading,setLoading]=useState(true); const [error,setError]=useState("");
  const [localError,setLocalError]=useState("");
  const [samples,setSamples]=useState<SampleSummary[]>([]);
  const [graphSampleId,setGraphSampleId]=useState("");
  const [sampleLimit,setSampleLimit]=useState(40);
  const [sampleGraph,setSampleGraph]=useState<KnowledgeGraph|null>(null);
  const [sampleLoading,setSampleLoading]=useState(false);
  const [sampleError,setSampleError]=useState("");
  const sampleRequest=useRef(0);
  const graphRequest=useRef(0);
  const [knownPredicates,setKnownPredicates]=useState<string[]>([]);
  const loadSampleGraph=async()=>{
    const request=++sampleRequest.current;
    setSampleLoading(true);setSampleError("");setSampleGraph(null);
    try{const result=await api.sampleKnowledgeGraph(graphSampleId,sampleLimit);if(request===sampleRequest.current)setSampleGraph(result)}
    catch(e){if(request===sampleRequest.current)setSampleError((e as Error).message)}
    finally{if(request===sampleRequest.current)setSampleLoading(false)}
  };
  const resetSampleGraph=()=>{sampleRequest.current++;setSampleGraph(null);setSampleError("");setSampleLoading(false)};
  const loadGraph=async(document=graphDocument,type=entityType,relation=predicate)=>{const request=++graphRequest.current;setGraphLoading(true);setError("");try{const result=await api.knowledgeGraph({limit:90,document_id:document?Number(document):undefined,entity_type:document?undefined:type,predicate:document?undefined:relation,min_document_count:1});if(request===graphRequest.current){setGraph(result);setKnownPredicates(previous=>[...new Set([...previous,...result.edges.map(edge=>edge.predicate||edge.label)])].sort())}}catch(e){if(request===graphRequest.current){setError((e as Error).message);setGraph(null)}}finally{if(request===graphRequest.current)setGraphLoading(false)}};
  useEffect(()=>{
    Promise.allSettled([
      api.litkgStatus().then(setStatus),
      api.litkgDocuments().then(result=>setDocuments(result.documents||[])),
      api.knowledgeStats().then(setStats).catch(e=>setLocalError(e.message)),
      api.papers({}).then(result=>{setPapers(result.papers);setPaperCount(result.count)}).catch(e=>setLocalError(e.message)),
      api.samples().then(result=>{const available=result.samples.filter(sample=>sample.artifacts.analysis?.exists||sample.artifacts.knowledge?.exists||sample.artifacts.structured?.exists);setSamples(available);if(available.length)setGraphSampleId(available[0].sample_id)}),
    ]).then(results=>{const errors=results.filter((result):result is PromiseRejectedResult=>result.status==="rejected");if(errors.length)setError(errors.map(result=>result.reason?.message||"部分数据加载失败").join("；"))}).finally(()=>setLoading(false));
    loadGraph();
  },[]);
  const types=useMemo(()=>[...new Set([...Object.keys(ENTITY_COLORS),...(graph?.nodes||[]).map(node=>node.type)])].sort(),[graph]);
  const predicates=knownPredicates;
  const searchClaims=async()=>{setClaimLoading(true);setBindMessage("");try{const data=await api.litkgClaims(claimQuery,30);setClaims(data.claims)}catch(e){setError((e as Error).message)}finally{setClaimLoading(false)}};
  const bindClaim=async(claim:Record<string,any>)=>{if(!sampleId.trim())return;if(!confirm(`将 ${claim.claim_id} 绑定到样本 ${sampleId}？`))return;try{await api.bindLitkgClaim(claim.raw_claim_id,sampleId.trim());setBindMessage(`已将接口 Claim 绑定到样本 ${sampleId.trim()}。`)}catch(e){setBindMessage((e as Error).message)}};
  const searchLocal=async()=>{try{const data=await api.papers({q:localQuery});setPapers(data.papers);setPaperCount(data.count)}catch(e){setError((e as Error).message)}};
  return <>
    <div className="page-intro"><div><p className="eyebrow">Evidence network</p><h1>证据知识库</h1></div><div className={`source-seal ${status?.available?"is-online":"is-offline"}`}><span className="source-pulse"/><div><strong>{status?.source.label||"LitKG 接口"}</strong><small>{status?.available?`接口在线 · ${status.source.endpoint}`:"接口暂不可用 · 已保留本地回退"}</small></div></div></div>
    <section className="remote-stats">{[
      [status?.document_count||0,"接口文献",BookOpen],[status?.claim_count||0,"结构化 Claims",GitBranch],[graph?.summary.node_count||0,"当前节点",CircleDot],[graph?.summary.relation_count||0,"当前关系",Network]
    ].map(([value,label,Icon]:any)=><article className="panel" key={label}><Icon size={17}/><strong>{loading?"—":value}</strong><span>{label}</span></article>)}</section>
    <div className="knowledge-modebar panel"><div>{([['graph','证据图谱',Network],['sample','样本关联子图',CircleDot],['interface','接口文献与 Claims',Server],['local','本地文献库',Database]] as [Mode,string,any][]).map(([id,label,Icon])=><button className={mode===id?"is-active":""} onClick={()=>setMode(id)} key={id}><Icon size={14}/>{label}</button>)}</div><span>{status?.available?<><CheckCircle2 size={13}/>数据来自接口实时响应</>:<><Activity size={13}/>接口异常时使用本地数据</>}</span></div>
    {error&&<div className="error-banner">{error}</div>}
    {mode==="graph"&&<><section className="panel graph-filterbar"><label><span>图谱范围</span><select className="select" value={graphDocument} onChange={e=>{setGraphDocument(e.target.value);setEntityType("");setPredicate("")}}><option value="">知识库关系（前 90 条）</option>{documents.filter(item=>item.status==="done").map(item=><option value={item.id} key={item.id}>文档 {item.id} · {item.title||item.filename}</option>)}</select></label><label><span>实体类型</span><select className="select" value={entityType} disabled={!!graphDocument} onChange={e=>setEntityType(e.target.value)}><option value="">全部实体</option>{types.map(value=><option value={value} key={value}>{ENTITY_LABELS[value]||value} · {value}</option>)}</select></label><label><span>关系类型</span><select className="select" value={predicate} disabled={!!graphDocument} onChange={e=>setPredicate(e.target.value)}><option value="">全部关系</option>{predicates.map(value=><option value={value} key={value}>{value}</option>)}</select></label><button className="button button-primary" disabled={graphLoading||!status?.available} onClick={()=>loadGraph()}><RefreshCw size={14} className={graphLoading?"spin":""}/>{graphLoading?"读取中":"刷新图谱"}</button></section><section className="panel graph-shell"><div className="graph-caption"><div><p className="eyebrow">Live graph response</p><h2>{graph?.document_id?`文档 ${graph.document_id} 的证据子图`:`知识库 ${graph?.knowledge_base_id||status?.source.knowledge_base_id||"—"} 关系图谱`}</h2></div><span>{graph?.summary.represented_document_count||0} 篇文档 · {graph?.edges.length||0} 条关系</span></div>{graphLoading?<div className="graph-loading"><Network size={31}/><strong>正在从接口读取图谱</strong><span>节点与边只使用 LitKG 实际返回的数据。</span></div>:graph?<EvidenceGraph graph={graph}/>:<div className="graph-loading"><Network size={31}/><strong>接口图谱暂不可用</strong><span>可以切换到本地文献库继续检索。</span></div>}</section></>}
    {mode==="sample"&&<>
      <section className="panel sample-graph-selector">
        <div><p className="eyebrow">Sample evidence network</p><h2>样本最相关知识子图</h2><p>优先匹配样本检测实体和异常项，并结合报告引用与已保存证据排序，保留真实 Claim 的方向、限定条件和来源。</p></div>
        <div className="sample-graph-controls"><label>选择样本<select className="select" value={graphSampleId} onChange={e=>{setGraphSampleId(e.target.value);resetSampleGraph()}} disabled={!samples.length}><option value="">{samples.length?"请选择样本":"暂无已分析或已绑定证据的样本"}</option>{samples.map(sample=><option key={sample.sample_id} value={sample.sample_id}>{sample.name||sample.sample_id}{sample.name&&sample.name!==sample.sample_id?` · ${sample.sample_id}`:""}</option>)}</select></label>
          <label>最多关系数<select className="select" value={sampleLimit} onChange={e=>{setSampleLimit(Number(e.target.value));resetSampleGraph()}}>{[20,40,80,150].map(value=><option value={value} key={value}>{value} 条</option>)}</select></label>
          <button className="button button-primary" onClick={loadSampleGraph} disabled={!graphSampleId||sampleLoading}><CircleDot size={14}/>{sampleLoading?"正在匹配证据…":"展示最相关子图"}</button>
        </div>
      </section>
      {sampleError&&<div className="error-banner" role="alert">{sampleError}</div>}
      {sampleGraph?.retrieval&&(sampleGraph.retrieval.status!=="complete"||sampleGraph.retrieval.scan_truncated)&&<div className="sample-graph-notice" role="status">{sampleGraph.retrieval.message||"本次检索达到扫描上限，结果仅代表已扫描的知识关系。"}</div>}
      <section className="panel graph-shell"><div className="graph-caption"><div><p className="eyebrow">Relevance-ranked evidence</p><h2>{sampleGraph?`样本 ${sampleGraph.sample_id} · 最相关子图`:"选择样本，查看关联知识"}</h2></div>{sampleGraph&&<span>{sampleGraph.selection?.matched_feature_count||0} 个检测实体匹配 · {sampleGraph.selection?.candidate_count||0} 条候选关系 · 展示 {sampleGraph.edges.length} 条</span>}</div>
        {sampleLoading?<div className="graph-loading" role="status"><Network size={31}/><strong>正在匹配该样本的检测实体与知识证据</strong><span>首次读取会分页检索知识库，最多约 45 秒。</span></div>:sampleGraph?<><div className="sample-graph-method">{sampleGraph.selection?.ranking} 已扫描 {sampleGraph.retrieval?.scanned_claims||0} 条 Claim。{sampleGraph.selection?.truncated?`当前仅显示前 ${sampleLimit} 条，可增加关系数。`:""}</div><EvidenceGraph graph={sampleGraph}/></>:<div className="graph-loading"><CircleDot size={31}/><strong>展示与该样本关联最强的真实知识关系</strong><span>选择样本后点击“展示最相关子图”，点击图中节点或边可查看匹配依据。</span></div>}
      </section>
    </>}
    {mode==="interface"&&<div className="remote-layout"><section className="panel document-panel"><div className="panel-head"><div><h2>接口文献</h2><span>{documents.length} 篇 · {status?.ready_count||0} 篇解析完成</span></div><Server size={16}/></div><div className="remote-documents">{documents.map(item=><button key={item.id} onClick={()=>{setGraphDocument(String(item.id));setMode("graph");loadGraph(String(item.id),"","")}}><span className={`doc-status ${item.status}`}/><span><strong>{item.title||item.filename}</strong><small>document:{item.id} · {item.chunk_done_count||0}/{item.chunk_count||0} chunks · {item.claim_count||0} Claims</small></span><ArrowUpRight size={14}/></button>)}</div></section><section className="panel claim-panel"><div className="panel-head"><div><h2>Claim 检索</h2><span>通过接口扫描并按关键词匹配</span></div><GitBranch size={16}/></div><div className="claim-search"><div className="query-main"><Search size={15}/><input value={claimQuery} onChange={e=>setClaimQuery(e.target.value)} onKeyDown={e=>e.key==="Enter"&&searchClaims()} placeholder="Akkermansia、type 2 diabetes…"/></div><button className="button button-primary" disabled={claimLoading} onClick={searchClaims}>{claimLoading?"检索中":"检索 Claims"}</button></div><div className="claim-bindbar"><input className="input" value={sampleId} onChange={e=>setSampleId(e.target.value)} placeholder="绑定到样本 ID（可选）"/>{bindMessage&&<span>{bindMessage}</span>}</div><div className="claim-results">{claims.map(claim=><article key={claim.claim_id}><div><span>{claim.claim_id}</span><em>{Number(claim.confidence||0).toFixed(2)}</em></div><h3>{claim.subject} <b>{claim.predicate}</b> {claim.object}</h3><p>{claim.evidence_text||"接口未返回证据原句。"}</p><footer><span>document:{claim.document_id} · {claim.filename}</span><button disabled={!sampleId.trim()} onClick={()=>bindClaim(claim)}><Link2 size={12}/>绑定证据</button></footer></article>)}{!claims.length&&!claimLoading&&<div className="list-empty">输入关键词后从 LitKG Claim 接口检索证据。</div>}</div></section></div>}
    {mode==="local"&&localError&&<div className="error-banner">{localError}</div>}
    {mode==="local"&&<div className="local-kb-layout"><section className="panel local-paper-panel"><div className="local-search"><div className="query-main"><Search size={15}/><input value={localQuery} onChange={e=>setLocalQuery(e.target.value)} onKeyDown={e=>e.key==="Enter"&&searchLocal()} placeholder="检索本地 SQLite 标题、摘要、期刊或 PMID"/></div><button className="button button-primary" onClick={searchLocal}>检索</button></div><div className="local-kb-note"><Database size={14}/><span>本地回退库 · {stats?.papers||0} 篇文献 · 当前匹配 {paperCount} 条</span></div><div className="paper-list">{papers.map(paper=><button className={`paper-card ${selectedPaper?.pmid===paper.pmid?"is-selected":""}`} key={paper.pmid} onClick={()=>setSelectedPaper(paper)}><div className="paper-meta"><span>PMID {paper.pmid}</span><span>{paper.publication_year||"年份未知"}</span>{paper.full_text_available?<span className="fulltext">全文</span>:null}</div><h3>{paper.title}</h3><p>{paper.abstract||"该记录暂无摘要。"}</p><div className="paper-foot"><span>{paper.journal_name||"期刊未知"}</span>{paper.target_disease_name&&<b>{paper.target_disease_name}</b>}</div></button>)}</div></section><aside className="panel local-paper-detail">{selectedPaper?<><button className="plain-icon" onClick={()=>setSelectedPaper(null)}><X size={14}/></button><p className="eyebrow">Local evidence</p><h2>{selectedPaper.title}</h2><div className="detail-tags"><span>PMID {selectedPaper.pmid}</span><span>{selectedPaper.journal_name}</span><span>{selectedPaper.publication_year}</span></div><h3>摘要</h3><p>{selectedPaper.abstract||"该记录暂无摘要。"}</p><a href={`https://pubmed.ncbi.nlm.nih.gov/${selectedPaper.pmid}/`} target="_blank" rel="noreferrer">打开 PubMed <ArrowUpRight size={13}/></a></>:<div className="evidence-empty"><FileSearch size={28}/><strong>选择一篇本地文献</strong><span>本地库用于接口中断时继续检索。</span></div>}</aside></div>}
  </>;
}
