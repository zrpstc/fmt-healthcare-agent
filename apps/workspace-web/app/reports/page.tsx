"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Children, isValidElement, useEffect, useMemo, useState, type ReactNode } from "react";
import tableWidths from "./word-report-tables.json";
import "./word-report.css";
import { Archive, CheckCircle2, Download, FileJson, FileText, MessageSquare, RefreshCw, Search, ShieldAlert } from "lucide-react";
import { api, backendUrl, ReportRow } from "@/lib/api";

const bytes=(value=0)=>value>1024*1024?`${(value/1024/1024).toFixed(1)} MB`:value>1024?`${(value/1024).toFixed(1)} KB`:`${value} B`;
const date=(value?:string|null)=>value?new Date(value).toLocaleString("zh-CN"):"暂无更新时间";
const headingId=(children:ReactNode)=>Children.toArray(children).map(child=>typeof child==="string"||typeof child==="number"?String(child):"").join("").toLowerCase().replace(/\s+/g,"-");
const nodeText=(node:ReactNode):string=>Children.toArray(node).map(child=>typeof child==="string"||typeof child==="number"?String(child):isValidElement<{children?:ReactNode}>(child)?nodeText(child.props.children):"").join("");
function WordTable({children}:{children?:ReactNode}){
  const head=Children.toArray(children).find(child=>isValidElement(child)&&child.type==="thead");
  const key=nodeText(head).replace(/\s+/g,"");
  const widths=(tableWidths as Record<string,number[]>)[key];
  const total=widths?.reduce((a,b)=>a+b,0)||1;
  return <table className={key==="综合健康分失衡分模型肠龄"?"word-score-table":undefined}>{widths&&<colgroup>{widths.map((width,index)=><col style={{width:`${100*width/total}%`}} key={index}/>)}</colgroup>}{children}</table>;
}

function MarkdownPreview({source,sampleId,revision}:{source:string;sampleId:string;revision:string}){
  return <div className="markdown-preview markdown-body word-template-report"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{
    table:({children})=><WordTable>{children}</WordTable>,
    h2:({children})=><h2 id={headingId(children)} style={{scrollMarginTop:"1rem"}}>{children}</h2>,
    h3:({children})=><h3 id={headingId(children)} style={{scrollMarginTop:"1rem"}}>{children}</h3>,
    img:({src,alt})=>{
    const name=typeof src==="string"?src.split("/").pop()||"":"";
    if(!name.startsWith(sampleId+"_")||!name.endsWith(".png"))return <span>图表来源不可用</span>;
    return <img src={backendUrl(`/reports/${encodeURIComponent(sampleId)}/figures/${encodeURIComponent(name)}?v=${encodeURIComponent(revision)}`)} alt={alt||"分析图表"} style={{maxWidth:"100%",height:"auto"}}/>;
  }}}>{source}</ReactMarkdown></div>;
}

export default function ReportsPage(){
  const [reports,setReports]=useState<ReportRow[]>([]); const [stats,setStats]=useState({count:0,pdf:0,markdown:0}); const [query,setQuery]=useState(""); const [selected,setSelected]=useState("");
  const [preview,setPreview]=useState(""); const [loading,setLoading]=useState(true); const [generating,setGenerating]=useState(false); const [message,setMessage]=useState("");
  const [refreshKey,setRefreshKey]=useState(0);
  const load=async(q=query,clearMessage=true)=>{setLoading(true);try{const data=await api.reports(q);setReports(data.reports);setStats({count:data.count,pdf:data.pdf_count,markdown:data.markdown_count});const requested=typeof window!=="undefined"?new URLSearchParams(window.location.search).get("sample")||"":"";setSelected(current=>current&&data.reports.some(item=>item.sample_id===current)?current:(data.reports.find(item=>item.sample_id===requested)?.sample_id||data.reports[0]?.sample_id||""));if(clearMessage)setMessage("")}catch(e){setMessage((e as Error).message)}finally{setLoading(false)}};
  useEffect(()=>{load("")},[]);
  const current=useMemo(()=>reports.find(item=>item.sample_id===selected),[reports,selected]);
  const hasReport=Boolean(current?.artifacts.markdown?.exists||current?.artifacts.pdf?.exists);
  const revision=`${current?.artifacts.markdown?.updated_at||""}-${refreshKey}`;
  const reportVersion=preview.match(/^报告版本[：:]\s*(.+)$/m)?.[1]||"旧版／未标注版本";
  useEffect(()=>{
    setPreview("");
    if(!current?.artifacts.markdown?.exists)return;
    const controller=new AbortController();
    fetch(backendUrl(`/reports/${encodeURIComponent(current.sample_id)}/markdown?v=${encodeURIComponent(revision)}`),{cache:"no-store",signal:controller.signal})
      .then(response=>response.ok?response.text():Promise.reject(new Error("Markdown 报告读取失败")))
      .then(text=>{if(!controller.signal.aborted)setPreview(text)})
      .catch(e=>{if(e.name!=="AbortError")setMessage(e.message)});
    return ()=>controller.abort();
  },[current,revision]);
  const generate=async()=>{if(!current||!confirm(hasReport?`重新生成 ${current.sample_id} 的报告？现有同名报告可能被覆盖。`:`生成 ${current.sample_id} 的报告？系统将复用已有生信结果，无需重新分析测序文件。`))return;setGenerating(true);setMessage("");try{const result=await api.generateReport(current.sample_id);await load(query,false);setRefreshKey(Date.now());const detail=["not_configured","fallback","no_eligible_data"].includes(result.llm_status||"")?"本次以检测数据和固定说明呈现，尚无可用模型解读。":result.llm_status==="partial"?"部分板块已生成模型解读，其余保留数据说明。":"正在读取最新正文。";setMessage(`报告已${hasReport?"重新生成":"生成"}。${detail}${hasReport?"旧版已下载文件不会自动更新，请重新下载。":""}`);}catch(e){setMessage((e as Error).message)}finally{setGenerating(false)}};
  return <>
    <div className="page-intro"><div><p className="eyebrow">Report archive</p><h1>报告中心</h1></div><button className="button button-primary" disabled={!current||generating} onClick={generate}><RefreshCw size={15} className={generating?"spin":""}/>{generating?"生成中":hasReport?"重新生成报告":"生成报告"}</button></div>
    <section className="report-ledger panel"><div><Archive size={18}/><strong>{stats.count}</strong><span>样本档案</span></div><div><FileText size={18}/><strong>{stats.pdf}</strong><span>PDF 报告</span></div><div><FileJson size={18}/><strong>{stats.markdown}</strong><span>Markdown 报告</span></div><p><ShieldAlert size={15}/>报告用于科研与教育，不构成诊断、治疗或临床决策建议。</p></section>
    {message&&<div className={message.startsWith("报告已")?"notice":"error-banner"}>{message}</div>}
    <div className="report-layout">
      <section className="panel report-index"><div className="panel-head"><div><h2>报告档案</h2><span>按最近更新时间排列</span></div><FileText size={16}/></div><div className="search-box"><Search size={14}/><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>e.key==="Enter"&&load()} placeholder="搜索样本 ID 或名称"/></div><div className="report-list">{loading?<div className="list-empty">正在读取报告索引…</div>:reports.map(item=>{const ready=item.artifacts.pdf?.exists||item.artifacts.markdown?.exists;return <button className={`report-row ${selected===item.sample_id?"is-selected":""}`} onClick={()=>setSelected(item.sample_id)} key={item.sample_id}><span className={`report-icon ${ready?"ready":"draft"}`}><FileText size={15}/></span><span><strong>{item.name||item.sample_id}</strong><small>{item.name&&item.name!==item.sample_id?`${item.sample_id} · `:""}{date(item.updated_at)}</small></span><em>{ready?"可下载":item.artifacts.analysis?.exists?"分析完成":"待生成"}</em></button>})}{!loading&&!reports.length&&<div className="list-empty">暂无报告档案。生信任务完成后，样本会出现在这里，可选择并生成报告。</div>}</div></section>
      <section className="panel report-reader">{current?<><div className="report-head"><div><p className="eyebrow">Selected report</p><h2>{current.name||current.sample_id}</h2><span>样本 ID：{current.sample_id} · {date(current.updated_at)}</span>{preview&&<p>当前预览版本：<strong>{reportVersion}</strong></p>}</div><Link className="button button-ghost" href={`/chat?sample=${encodeURIComponent(current.sample_id)}`}><MessageSquare size={14}/>围绕报告提问</Link></div><div className="artifact-ribbon">{[
        ["pdf","PDF","application/pdf"],["markdown","Markdown","text/markdown"],["structured","结构化报告","application/json"],["analysis","分析 JSON","application/json"],["knowledge","知识 JSON","application/json"],["evidence","报告证据 JSON","application/json"]
      ].map(([kind,label])=>{const artifact=current.artifacts[kind];return <div className={artifact?.exists?"is-ready":""} key={kind}><span><CheckCircle2 size={13}/>{label}</span><strong>{artifact?.exists?bytes(artifact.bytes):"未生成"}</strong>{artifact?.exists?<a href={backendUrl(`/reports/${encodeURIComponent(current.sample_id)}/${kind}?v=${encodeURIComponent(artifact.updated_at||revision)}`)} download><Download size={13}/>下载</a>:<small>等待产物</small>}</div>})}</div><div className="report-paper">{preview?<MarkdownPreview source={preview} sampleId={current.sample_id} revision={revision}/>:<div className="report-empty"><FileText size={31}/><strong>{current.artifacts.markdown?.exists?"正在载入报告预览":"暂无 Markdown 报告"}</strong><span>{current.artifacts.pdf?.exists?"可以直接下载 PDF，或确认后重新生成完整报告。":current.artifacts.analysis?.exists?"结构化分析已完成，可使用右上角按钮生成报告。":"生信处理已完成，可使用右上角按钮生成分析和报告，无需重新上传。"}</span></div>}</div></>:<div className="report-empty"><Archive size={32}/><strong>尚未选择报告</strong><span>从左侧选择一个样本档案查看产物。</span></div>}</section>
    </div>
  </>;
}
