"use client";

import Link from "next/link";
import { SampleManagement } from "@/components/sample-management";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Activity, ArrowUpRight, BarChart3, Beaker, CheckCircle2, Dna, FileText, Search, Sparkles, TestTube2, UploadCloud } from "lucide-react";
import { api, backendUrl, SampleDetail, SampleSummary } from "@/lib/api";

type View="overview"|"species"|"function"|"fmt";
type SpeciesRow={species:string;chinese_name?:string;abundance:number;status:string;status_cn?:string;deviation?:number;p5?:number;p95?:number};
type NamedValue={name:string;abundance:number};

const number=(value:unknown,digits=0)=>Number(value||0).toLocaleString("zh-CN",{maximumFractionDigits:digits});
const date=(value?:string|null)=>value?new Date(value).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}):"暂无更新时间";
const statusLabel=(value:string)=>({complete:"生信完成",completed:"生信完成",done:"生信完成",success:"生信完成",analyzed:"已分析",has_results:"已有结果",running:"运行中",queued:"已排队",uploading:"上传中",uploaded:"已上传",failed:"失败",pending:"等待中",deleting:"删除中",delete_failed:"删除未完成"}[value.toLowerCase()]||value);

const sampleStatus=(item:SampleSummary)=>item.artifacts.pdf?.exists&&item.artifacts.markdown?.exists?"报告已生成":item.artifacts.analysis?.exists?"分析已完成":statusLabel(item.status);

export default function SamplesPage(){
  const [samples,setSamples]=useState<SampleSummary[]>([]); const [total,setTotal]=useState(0); const [counts,setCounts]=useState<Record<string,number>>({});
  const [selected,setSelected]=useState(""); const [detail,setDetail]=useState<SampleDetail|null>(null); const [query,setQuery]=useState("");
  const [page,setPage]=useState(1); const [pageSize,setPageSize]=useState(12);
  const [view,setView]=useState<View>("overview"); const [loading,setLoading]=useState(true); const [error,setError]=useState("");
  const [indexError,setIndexError]=useState(""); const [detailError,setDetailError]=useState(""); const [refreshToken,setRefreshToken]=useState(0);
  const [uploadOpen,setUploadOpen]=useState(false); const [uploading,setUploading]=useState(false); const [uploadMessage,setUploadMessage]=useState("");
  const [uploadSampleId,setUploadSampleId]=useState(""); const [layout,setLayout]=useState<"single"|"paired">("paired"); const [read1,setRead1]=useState<File|null>(null); const [read2,setRead2]=useState<File|null>(null);
  const submitUpload=async(event:FormEvent)=>{
    event.preventDefault();
    if(!uploadSampleId.trim()||!read1||(layout==="paired"&&!read2)||uploading)return;
    setUploading(true);setError("");setUploadMessage("");
    try{
      const result=await api.uploadSample({sampleId:uploadSampleId.trim(),layout,read1,read2});
      setUploadMessage(`样本 ${result.sample_id} 已提交，后台分析状态：${statusLabel(result.state||"running")}`);
      setSelected(result.sample_id);setQuery("");setPage(1);
    }catch(e){setError((e as Error).message)}
    finally{setUploading(false);setRefreshToken(value=>value+1)}
  };
  useEffect(()=>{
    let active=true;let inFlight=false;
    const refresh=async(initial=false)=>{
      if(!active||inFlight)return;
      inFlight=true;if(initial)setLoading(true);
      try{
        const data=await api.samples(query);
        if(!active)return;
        setSamples(data.samples);setTotal(data.count);setCounts(data.status_counts);
        setSelected(current=>current&&data.samples.some(item=>item.sample_id===current)?current:(data.samples.find(item=>item.status==="running")?.sample_id||data.samples.find(item=>item.species_total>0)?.sample_id||data.samples.find(item=>item.artifacts.analysis?.exists)?.sample_id||data.samples[0]?.sample_id||""));
        setIndexError("");
      }catch(e){if(active)setIndexError((e as Error).message)}
      finally{inFlight=false;if(active)setLoading(false)}
    };
    const timer=setTimeout(()=>{void refresh(true)},220);
    const interval=setInterval(()=>{if(document.visibilityState==="visible")void refresh()},5000);
    return()=>{active=false;clearTimeout(timer);clearInterval(interval)};
  },[query,refreshToken]);
  const selectedSummary=useMemo(()=>samples.find(item=>item.sample_id===selected),[samples,selected]);
  const hasAnalysis=Boolean(selectedSummary?.artifacts.analysis?.exists);
  const analysisUpdatedAt=selectedSummary?.artifacts.analysis?.updated_at;
  useEffect(()=>{
    let active=true;setDetail(null);setDetailError("");
    if(selected&&hasAnalysis){
      api.sample(selected).then(value=>{if(active)setDetail(value)}).catch(e=>{if(active)setDetailError(e.message)});
    }
    return()=>{active=false};
  },[selected,hasAnalysis,analysisUpdatedAt]);
  const analysis=detail?.analysis||{}; const species:SpeciesRow[]=Array.isArray(analysis.species?.species_list)?analysis.species.species_list:[];
  const abnormal:SpeciesRow[]=Array.isArray(analysis.compare?.abnormal_species)?analysis.compare.abnormal_species:(Array.isArray(analysis.species?.abnormal_species)?analysis.species.abnormal_species:[]);
  const pathways:NamedValue[]=Array.isArray(analysis.pathways?.pathways)?analysis.pathways.pathways:[]; const metabolites:NamedValue[]=Array.isArray(analysis.metabolites?.metabolites)?analysis.metabolites.metabolites:[];
  const diseases=Array.isArray(analysis.diseases?.diseases)?analysis.diseases.diseases:[]; const fmt=analysis.fmt_matching||{}; const donors=Array.isArray(fmt.top_k_matches)?fmt.top_k_matches:[]; const fmtAudit=fmt.feature_audit||{};
  const maxSpecies=Math.max(...species.slice(0,12).map(item=>Number(item.abundance)||0),1); const maxPathway=Math.max(...pathways.slice(0,10).map(item=>Number(item.abundance)||0),1);
  const workflow=selectedSummary?.workflow;
  const pageCount=Math.max(1,Math.ceil(samples.length/pageSize)); const pageStart=(page-1)*pageSize;
  const visibleSamples=useMemo(()=>samples.slice(pageStart,pageStart+pageSize),[samples,pageStart,pageSize]);
  useEffect(()=>{setPage(current=>Math.min(current,pageCount))},[pageCount]);
  return <>
    <div className="page-intro"><div><p className="eyebrow">Sample observatory</p><h1>样本与分析</h1></div><div className="sample-actions"><button className="button button-coral" onClick={()=>setUploadOpen(value=>!value)}><UploadCloud size={15}/>上传测序文件</button><Link className="button button-primary" href={`/chat?sample=${encodeURIComponent(selected)}`}><Sparkles size={15}/>交给 Agent 分析</Link></div></div>
    {uploadOpen&&<form className="panel sample-upload" onSubmit={submitUpload}><div className="sample-upload-copy"><p className="eyebrow">Manual FASTQ intake</p><h2>上传患者 Shotgun 宏基因组样本</h2><p>文件会进入独立工作区，并沿用现有可恢复流程执行质控、去宿主、物种谱、功能分析及 FMT 供体排序。结果仅用于科研分析。</p></div><label><span>样本 ID</span><input className="input" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,79}" value={uploadSampleId} onChange={e=>setUploadSampleId(e.target.value)} placeholder="PATIENT_001"/></label><label><span>测序布局</span><select className="select" value={layout} onChange={e=>setLayout(e.target.value as "single"|"paired")}><option value="paired">双端 paired-end</option><option value="single">单端 single-end</option></select></label><label><span>{layout==="paired"?"R1 · 必填":"FASTQ · 必填"}</span><input required type="file" accept=".fastq.gz,.fq.gz,.fastq,.fq" onChange={e=>setRead1(e.target.files?.[0]||null)}/></label>{layout==="paired"&&<label><span>R2 · 必填</span><input required type="file" accept=".fastq.gz,.fq.gz,.fastq,.fq" onChange={e=>setRead2(e.target.files?.[0]||null)}/></label>}<button className="button button-primary" disabled={uploading||!read1||!uploadSampleId.trim()||(layout==="paired"&&!read2)} type="submit">{uploading?"正在上传…":"上传并开始分析"}</button>{uploadMessage&&<div className="success-banner">{uploadMessage}</div>}</form>}
    <section className="sample-hero panel"><div><span className="hero-index">{String(total).padStart(2,"0")}</span><p>已纳入工作台的样本</p></div><div className="hero-flow"><span><CheckCircle2 size={15}/>完成或已有结果 <b>{counts.complete||0}</b></span><span><Activity size={15}/>正在运行 <b>{counts.running||0}</b></span><span><TestTube2 size={15}/>结构化分析 <b>{samples.filter(item=>item.artifacts.analysis?.exists).length}</b></span></div></section>
    {(error||indexError||detailError)&&<div className="error-banner">{error||indexError||detailError}</div>}
    <div className="sample-layout">
      <section className="panel sample-browser"><div className="panel-head"><div><h2>样本索引</h2><span>{samples.length} 条当前结果</span></div><Dna size={17}/></div><div className="search-box"><Search size={14}/><input value={query} onChange={e=>{setQuery(e.target.value);setPage(1)}} placeholder="按样本 ID 或名称查找"/></div><div className="sample-list">
        {loading?<div className="list-empty">正在读取样本索引…</div>:visibleSamples.map(item=><button key={item.sample_id} className={`sample-row ${selected===item.sample_id?"is-selected":""}`} onClick={()=>{setSelected(item.sample_id);setView("overview")}}><span className={`sample-state ${item.status.toLowerCase()}`}/><span><strong>{item.name||item.sample_id}</strong><small>{item.name&&item.name!==item.sample_id?`${item.sample_id} · `:""}{sampleStatus(item)} · {date(item.updated_at)}</small></span><b>{item.species_total?number(item.species_total):"—"}</b></button>)}
        {!loading&&!samples.length&&<div className="list-empty">没有匹配的样本。清空关键词查看全部数据。</div>}
      </div>{!loading&&samples.length>0&&<nav className="sample-pagination" aria-label="样本索引分页"><span>{pageStart+1}–{Math.min(pageStart+pageSize,samples.length)} / {samples.length}</span><label>每页<select value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1)}}><option value={8}>8</option><option value={12}>12</option><option value={20}>20</option></select></label><button aria-label="上一页" disabled={page<=1} onClick={()=>setPage(value=>Math.max(1,value-1))}>‹</button><strong>第 {page} / {pageCount} 页</strong><button aria-label="下一页" disabled={page>=pageCount} onClick={()=>setPage(value=>Math.min(pageCount,value+1))}>›</button></nav>}</section>
      <section className="panel sample-detail">
        <div className="sample-title"><div><p className="eyebrow">Current sample</p><h2>{selectedSummary?.name||selected||"选择样本"}</h2>{selectedSummary?.name&&selectedSummary.name!==selected&&<small>样本 ID：{selected}</small>}{selectedSummary?.notes&&<p className="sample-notes">{selectedSummary.notes}</p>}<span>{selectedSummary?`${sampleStatus(selectedSummary)} · ${date(selectedSummary.updated_at)}`:"从左侧选择一个已有分析结果的样本"}</span></div><div className="sample-links"><Link className="button button-ghost" href={`/reports?sample=${encodeURIComponent(selected)}`}><FileText size={14}/>{selectedSummary?.artifacts.markdown?.exists||selectedSummary?.artifacts.pdf?.exists?"查看报告":"生成报告"}</Link><Link className="button button-coral" href={`/chat?sample=${encodeURIComponent(selected)}`}><ArrowUpRight size={14}/>继续追问</Link></div></div>
        {selectedSummary&&<SampleManagement key={selectedSummary.sample_id} sample={selectedSummary}
          onSaved={metadata=>{setSamples(items=>items.map(item=>item.sample_id===selectedSummary.sample_id?{...item,...metadata}:item));setRefreshToken(value=>value+1)}}
          onDeleted={sampleId=>{setSamples(items=>items.filter(item=>item.sample_id!==sampleId));setSelected(current=>current===sampleId?"":current);setTotal(value=>Math.max(0,value-1));setRefreshToken(value=>value+1)}}/>}
        {detail?<><div className="metric-strip"><div><span>检测物种</span><strong>{number(detail.summary.species_total)}</strong><small>species</small></div><div><span>偏高 / 偏低</span><strong>{detail.summary.species_high} / {detail.summary.species_low}</strong><small>reference</small></div><div><span>肠型判断</span><strong className="metric-text">{detail.summary.enterotype}</strong><small>{number(analysis.enterotype?.confidence,1)}% confidence</small></div><div><span>功能通路</span><strong>{number(detail.summary.pathway_total)}</strong><small>pathways</small></div></div>
          <div className="analysis-tabs">{([['overview','分析摘要'],['species','物种丰度'],['function','功能与关联'],['fmt','FMT 配型']] as [View,string][]).map(([id,label])=><button className={view===id?"is-active":""} key={id} onClick={()=>setView(id)}>{label}</button>)}</div>
          <div className="analysis-canvas">
            {view==="overview"&&<div className="overview-grid"><article className="insight-card"><div className="card-kicker"><Beaker size={14}/>关键偏差</div><h3>{abnormal.length?`${abnormal.length} 条物种偏差信号`:`当前结果未记录物种偏差信号`}</h3><p>{abnormal[0]?`${abnormal[0].species} 的丰度为 ${number(abnormal[0].abundance,3)}%，相对参考范围偏差最突出。`:"可在物种丰度页核查原始结构化结果。"}</p><div className="signal-list">{abnormal.slice(0,5).map((item,index)=><div key={`${item.species}-${index}`}><span>{item.chinese_name||item.species}</span><b className={item.status}>{item.status_cn||item.status}</b></div>)}</div></article><article className="insight-card"><div className="card-kicker"><BarChart3 size={14}/>功能轮廓</div><h3>{pathways.length?pathways[0].name:"尚无通路结果"}</h3><p>{pathways.length?`共记录 ${number(analysis.pathways?.n_total_pathways)} 条通路；下方列出当前丰度最高的功能信号。`:"该样本的 HUMAnN 功能结果尚未写入分析文件。"}</p><div className="mini-bars">{pathways.slice(0,5).map(item=><div key={item.name}><span>{item.name}</span><i style={{width:`${Math.max(4,(item.abundance/maxPathway)*100)}%`}}/></div>)}</div></article><article className="insight-card evidence-accent"><div className="card-kicker"><Dna size={14}/>关联提示</div><h3>{diseases.length?`${diseases.length} 个疾病关联条目`:"未记录疾病关联"}</h3><p>关联评分仅用于科研筛查，不代表诊断或临床风险。</p>{diseases.slice(0,4).map((item:any)=><div className="risk-line" key={item.disease}><span>{item.disease}</span><b>{number(item.risk_score,1)}</b></div>)}</article></div>}
            {view==="species"&&<div className="chart-table"><div className="bar-chart"><h3>物种相对丰度 Top 12</h3>{species.slice(0,12).map((item,index)=><div className="bar-row" key={`${item.species}-${index}`}><span title={item.species}>{item.chinese_name||item.species}</span><div><i className={item.status} style={{width:`${Math.max(2,(item.abundance/maxSpecies)*100)}%`}}/></div><b>{number(item.abundance,3)}%</b></div>)}</div><div className="data-table-wrap"><table className="data-table"><thead><tr><th>物种</th><th>丰度</th><th>参考范围</th><th>状态</th></tr></thead><tbody>{species.slice(0,30).map((item,index)=><tr key={`${item.species}-${index}`}><td><strong>{item.chinese_name||item.species}</strong><small>{item.chinese_name?item.species:""}</small></td><td>{number(item.abundance,4)}%</td><td>{item.status!=="unknown"&&typeof item.p5==="number"&&typeof item.p95==="number"&&Number.isFinite(item.p5)&&Number.isFinite(item.p95)&&item.p95>item.p5?`${number(item.p5,3)}–${number(item.p95,3)}`:"未建立参考"}</td><td><span className={`status-tag ${item.status}`}>{item.status_cn||item.status}</span></td></tr>)}</tbody></table></div></div>}
            {view==="function"&&<div className="function-grid"><article className="rank-card"><h3>高丰度功能通路</h3>{pathways.slice(0,12).map((item,index)=><div className="rank-row" key={item.name}><b>{String(index+1).padStart(2,"0")}</b><span>{item.name}<i style={{width:`${Math.max(3,(item.abundance/maxPathway)*100)}%`}}/></span><strong>{number(item.abundance,1)}</strong></div>)}</article><article className="rank-card"><h3>预测代谢物</h3>{metabolites.slice(0,12).map((item,index)=><div className="rank-row violet" key={item.name}><b>{String(index+1).padStart(2,"0")}</b><span>{item.name}</span><strong>{number(item.abundance,1)}</strong></div>)}</article></div>}
            {view==="fmt"&&<div className="fmt-grid"><article className="fmt-visual">{detail.summary.artifacts.fmt_plot?.exists?<img src={backendUrl(`/samples/${encodeURIComponent(selected)}/plot`)} alt={`${selected} FMT 模型嵌入投影`}/>:<div className="visual-empty"><Dna size={32}/><strong>{fmt.status==="degraded"?"FMT 特征覆盖不足":"暂无 FMT 投影图"}</strong><span>{fmt.message||"候选供体列表仍可独立查看。"}</span></div>}</article><article className="donor-card"><div><p className="eyebrow">Donor ranking · {fmt.model_version||"model unavailable"}</p><h3>{fmt.message||"候选供体"}</h3>{fmtAudit.feature_name_coverage!==undefined&&<small>名称覆盖 {number(Number(fmtAudit.feature_name_coverage)*100,1)}% · 丰度覆盖 {number(Number(fmtAudit.abundance_coverage)*100,1)}% · 候选库 {number(fmt.candidate_count)}</small>}</div>{fmt.warnings?.map((warning:string)=><div className="error-banner" key={warning}>{warning}</div>)}{donors.slice(0,10).map((item:any,index:number)=><div className="donor-row" key={`${item.donor_id}-${index}`}><b>{item.rank||index+1}</b><span><strong>{item.donor_id}</strong><small>距离 {number(item.distance,3)} · 历史 {number(item.known_outcome_count)} 例{item.historical_response_rate!==null&&item.historical_response_rate!==undefined?` · 响应率 ${number(Number(item.historical_response_rate)*100,1)}%`:""}</small></span><em>{number(Number(item.score)*100,2)}%</em></div>)}{!donors.length&&<div className="list-empty">{fmt.message||"尚未生成候选供体排序。"}</div>}</article></div>}
          </div></>:workflow?<div className="detail-empty" role="status"><Activity size={32}/><strong>{selected} · {statusLabel(workflow.state)}</strong><progress aria-label="分析进度" value={workflow.progress} max={100} style={{width:"min(100%, 320px)"}}/><span>分析进度 {workflow.progress}% · {workflow.artifacts.functions?"功能分析结果已生成":workflow.artifacts.taxonomy?"物种谱已生成":workflow.artifacts.quality_control?"质控、去宿主与物种分析阶段":"测序文件已接收"}</span><span>{workflow.state==="running"?"任务正在后台执行，无需重复上传。页面每 5 秒自动更新。":workflow.state==="failed"?"分析任务已失败，请检查任务日志后重试。":workflow.state==="complete"?"生信处理已完成，报告尚未生成。点击上方“生成报告”，复用现有结果生成分析和报告。":"任务状态将自动更新。"}</span></div>:<div className="detail-empty"><TestTube2 size={32}/><strong>{selected?"该样本暂无结构化分析":"尚未选择样本"}</strong><span>请选择带有分析产物的样本，或在智能体对话中检查流程缺口。</span></div>}
      </section>
    </div>
  </>;
}
