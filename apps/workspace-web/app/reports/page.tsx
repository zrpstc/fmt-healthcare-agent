"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useEffect, useMemo, useRef, useState } from "react";
import { Archive, BarChart3, CheckCircle2, Download, FileJson, FileText, MessageSquare, RefreshCw, Search, ShieldAlert, Wrench } from "lucide-react";
import { api, backendUrl, InteractiveReport, InteractiveReportChart, ReportRow } from "@/lib/api";

const bytes=(value=0)=>value>1024*1024?`${(value/1024/1024).toFixed(1)} MB`:value>1024?`${(value/1024).toFixed(1)} KB`:`${value} B`;
const date=(value?:string|null)=>value?new Date(value).toLocaleString("zh-CN"):"暂无更新时间";

function MarkdownPreview({source,sampleId,revision}:{source:string;sampleId:string;revision:string}){
  return <div className="markdown-preview markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{img:({src,alt})=>{
    const name=typeof src==="string"?src.split("/").pop()||"":"";
    if(!name.startsWith(sampleId+"_")||!name.endsWith(".png"))return <span>图表来源不可用</span>;
    return <img src={backendUrl(`/reports/${encodeURIComponent(sampleId)}/figures/${encodeURIComponent(name)}?v=${encodeURIComponent(revision)}`)} alt={alt||"分析图表"} style={{maxWidth:"100%",height:"auto"}}/>;
  }}}>{source}</ReactMarkdown></div>;
}

function InteractiveChart({chart}:{chart:InteractiveReportChart}){
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{let disposed=false;let instance:import("echarts").ECharts|undefined;let observer:ResizeObserver|undefined;void import("echarts").then(echarts=>{if(disposed||!ref.current)return;instance=echarts.init(ref.current,undefined,{renderer:"canvas"});const items=chart.items.slice(0,20).reverse();instance.setOption({animationDuration:500,grid:{left:190,right:34,top:18,bottom:42},tooltip:{trigger:"axis",axisPointer:{type:"shadow"},formatter:(rows:any[])=>{const row=rows?.[0];const item=items[row?.dataIndex];return `${item?.label||""}<br/>数值 ${Number(item?.value||0).toPrecision(5)} ${item?.unit||""}<br/>证据 ${item?.evidence_id||""}`}},xAxis:{type:"value",name:items.some(item=>item.unit)?items.find(item=>item.unit)?.unit:"",nameLocation:"middle",nameGap:27},yAxis:{type:"category",data:items.map(item=>item.label),axisLabel:{width:170,overflow:"truncate",fontSize:10}},series:[{type:"bar",data:items.map(item=>({value:item.value,itemStyle:{color:item.status==="high"?"#d46a54":item.status==="low"?"#6e83b7":"#2b8294"}})),barMaxWidth:22}]});observer=new ResizeObserver(()=>instance?.resize());observer.observe(ref.current)});return()=>{disposed=true;observer?.disconnect();instance?.dispose()}},[chart]);
  return <section className="interactive-chart"><div><h3>{chart.title}</h3><p>{chart.boundary}</p></div>{chart.items.length?<div ref={ref} className="report-echart"/>:<div className="interactive-empty">当前产物没有该模块的可视化数据。</div>}</section>;
}

function InteractivePreview({payload}:{payload:InteractiveReport}){
  const [module,setModule]=useState(payload.available_modules[0]||payload.charts[0]?.id||"");
  useEffect(()=>setModule(payload.available_modules[0]||payload.charts[0]?.id||""),[payload.sample_id,payload.generated_at]);
  const current=payload.charts.find(item=>item.id===module)||payload.charts[0];
  return <div className="interactive-report"><div className="interactive-summary"><div><span>样本</span><strong>{payload.sample_id}</strong></div><div><span>肠型</span><strong>{String(payload.summary.enterotype||"未提供")}</strong></div><div><span>FMT 状态</span><strong>{String(payload.summary.fmt_status||"未运行")}</strong></div><div><span>数据规范</span><strong>{payload.schema_version}</strong></div></div><div className="report-module-tabs">{payload.charts.map(chart=><button key={chart.id} className={module===chart.id?"is-active":""} onClick={()=>setModule(chart.id)} disabled={!chart.items.length}>{chart.title}<em>{chart.items.length}</em></button>)}</div>{current&&<InteractiveChart chart={current}/>}<p className="interactive-disclaimer"><ShieldAlert size={14}/>{payload.disclaimer}</p></div>;
}

export default function ReportsPage(){
  const [reports,setReports]=useState<ReportRow[]>([]); const [stats,setStats]=useState({count:0,pdf:0,markdown:0}); const [query,setQuery]=useState(""); const [selected,setSelected]=useState("");
  const [preview,setPreview]=useState(""); const [loading,setLoading]=useState(true); const [generating,setGenerating]=useState(false); const [message,setMessage]=useState("");
  const [refreshKey,setRefreshKey]=useState(0);
  const [layer,setLayer]=useState<"main"|"technical"|"interactive">("main");
  const [technical,setTechnical]=useState(""); const [interactive,setInteractive]=useState<InteractiveReport|null>(null);
  const load=async(q=query,clearMessage=true)=>{setLoading(true);try{const data=await api.reports(q);setReports(data.reports);setStats({count:data.count,pdf:data.pdf_count,markdown:data.markdown_count});const requested=typeof window!=="undefined"?new URLSearchParams(window.location.search).get("sample")||"":"";setSelected(current=>current&&data.reports.some(item=>item.sample_id===current)?current:(data.reports.find(item=>item.sample_id===requested)?.sample_id||data.reports[0]?.sample_id||""));if(clearMessage)setMessage("")}catch(e){setMessage((e as Error).message)}finally{setLoading(false)}};
  useEffect(()=>{load("")},[]);
  const current=useMemo(()=>reports.find(item=>item.sample_id===selected),[reports,selected]);
  const revision=`${current?.artifacts.markdown?.updated_at||""}-${refreshKey}`;
  const reportVersion=preview.match(/^报告版本[：:]\s*(.+)$/m)?.[1]||"旧版／未标注版本";
  useEffect(()=>{
    setPreview("");setTechnical("");setInteractive(null);setLayer("main");
    if(!current)return;
    const controller=new AbortController();
    const loads:Promise<void>[]=[];
    if(current.artifacts.markdown?.exists)loads.push(fetch(backendUrl(`/reports/${encodeURIComponent(current.sample_id)}/markdown?v=${encodeURIComponent(revision)}`),{cache:"no-store",signal:controller.signal}).then(response=>response.ok?response.text():Promise.reject(new Error("主报告读取失败"))).then(text=>{if(!controller.signal.aborted)setPreview(text)}));
    if(current.artifacts.technical?.exists)loads.push(fetch(backendUrl(`/reports/${encodeURIComponent(current.sample_id)}/technical?v=${encodeURIComponent(revision)}`),{cache:"no-store",signal:controller.signal}).then(response=>response.ok?response.text():Promise.reject(new Error("技术附录读取失败"))).then(text=>{if(!controller.signal.aborted)setTechnical(text)}));
    if(current.artifacts.interactive?.exists)loads.push(fetch(backendUrl(`/reports/${encodeURIComponent(current.sample_id)}/interactive?v=${encodeURIComponent(revision)}`),{cache:"no-store",signal:controller.signal}).then(response=>response.ok?response.json():Promise.reject(new Error("交互报告读取失败"))).then(value=>{if(!controller.signal.aborted)setInteractive(value as InteractiveReport)}));
    Promise.all(loads).catch(e=>{if(e.name!=="AbortError")setMessage(e.message)});
    return ()=>controller.abort();
  },[current,revision]);
  const generate=async()=>{if(!current||!confirm(`重新生成 ${current.sample_id} 的报告？现有同名报告可能被覆盖。`))return;setGenerating(true);setMessage("");try{await api.generateReport(current.sample_id);await load(query,false);setRefreshKey(Date.now());setMessage("报告已重新生成，正在读取最新正文。旧版已下载文件不会自动更新，请重新下载。");}catch(e){setMessage((e as Error).message)}finally{setGenerating(false)}};
  return <>
    <div className="page-intro"><div><p className="eyebrow">Report archive</p><h1>报告中心</h1></div><button className="button button-primary" disabled={!current||generating} onClick={generate}><RefreshCw size={15} className={generating?"spin":""}/>{generating?"生成中":"重新生成报告"}</button></div>
    <section className="report-ledger panel"><div><Archive size={18}/><strong>{stats.count}</strong><span>样本档案</span></div><div><FileText size={18}/><strong>{stats.pdf}</strong><span>PDF 报告</span></div><div><FileJson size={18}/><strong>{stats.markdown}</strong><span>Markdown 报告</span></div><p><ShieldAlert size={15}/>报告用于科研与教育，不构成诊断、治疗或临床决策建议。</p></section>
    {message&&<div className={message.startsWith("报告已")?"notice":"error-banner"}>{message}</div>}
    <div className="report-layout">
      <section className="panel report-index"><div className="panel-head"><div><h2>报告档案</h2><span>按最近更新时间排列</span></div><FileText size={16}/></div><div className="search-box"><Search size={14}/><input value={query} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>e.key==="Enter"&&load()} placeholder="搜索样本 ID"/></div><div className="report-list">{loading?<div className="list-empty">正在读取报告索引…</div>:reports.map(item=>{const ready=item.artifacts.pdf?.exists||item.artifacts.markdown?.exists;return <button className={`report-row ${selected===item.sample_id?"is-selected":""}`} onClick={()=>setSelected(item.sample_id)} key={item.sample_id}><span className={`report-icon ${ready?"ready":"draft"}`}><FileText size={15}/></span><span><strong>{item.sample_id}</strong><small>{date(item.updated_at)}</small></span><em>{ready?"可下载":"仅分析"}</em></button>})}</div></section>
      <section className="panel report-reader">{current?<><div className="report-head"><div><p className="eyebrow">Selected report</p><h2>{current.sample_id}</h2><span>{date(current.updated_at)}</span>{preview&&<p>当前预览版本：<strong>{reportVersion}</strong></p>}</div><Link className="button button-ghost" href={`/chat?sample=${encodeURIComponent(current.sample_id)}`}><MessageSquare size={14}/>围绕报告提问</Link></div><div className="report-layer-tabs"><button className={layer==="main"?"is-active":""} onClick={()=>setLayer("main")}><FileText size={14}/>主报告</button><button className={layer==="technical"?"is-active":""} onClick={()=>setLayer("technical")} disabled={!current.artifacts.technical?.exists}><Wrench size={14}/>技术附录</button><button className={layer==="interactive"?"is-active":""} onClick={()=>setLayer("interactive")} disabled={!current.artifacts.interactive?.exists}><BarChart3 size={14}/>交互展示</button></div><div className="artifact-ribbon">{[
        ["pdf","主报告 PDF"],["markdown","主报告 MD"],["technical","技术附录"],["interactive","交互 JSON"],["analysis","分析 JSON"],["evidence","证据 JSON"]
      ].map(([kind,label])=>{const artifact=current.artifacts[kind];return <div className={artifact?.exists?"is-ready":""} key={kind}><span><CheckCircle2 size={13}/>{label}</span><strong>{artifact?.exists?bytes(artifact.bytes):"未生成"}</strong>{artifact?.exists?<a href={backendUrl(`/reports/${encodeURIComponent(current.sample_id)}/${kind}?v=${encodeURIComponent(artifact.updated_at||revision)}`)} download><Download size={13}/>下载</a>:<small>等待产物</small>}</div>})}</div><div className="report-paper">{layer==="main"?(preview?<MarkdownPreview source={preview} sampleId={current.sample_id} revision={revision}/>:<div className="report-empty"><FileText size={31}/><strong>{current.artifacts.markdown?.exists?"正在载入主报告":"暂无主报告"}</strong><span>保留现有分析结果后，可使用右上角按钮生成报告。</span></div>):layer==="technical"?(technical?<MarkdownPreview source={technical} sampleId={current.sample_id} revision={revision}/>:<div className="report-empty"><Wrench size={31}/><strong>正在载入技术附录</strong></div>):interactive?<InteractivePreview payload={interactive}/>:<div className="report-empty"><BarChart3 size={31}/><strong>正在载入交互报告</strong></div>}</div></>:<div className="report-empty"><Archive size={32}/><strong>尚未选择报告</strong><span>从左侧选择一个样本档案查看产物。</span></div>}</section>
    </div>
  </>;
}
