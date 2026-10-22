"use client";

import { FormEvent, useEffect, useState } from "react";
import { Pencil, Trash2, X } from "lucide-react";
import { api, SampleSummary } from "@/lib/api";

export function SampleManagement({sample,onSaved,onDeleted}:{
  sample:SampleSummary;
  onSaved:(metadata:{name:string;notes:string})=>void;
  onDeleted:(sampleId:string)=>void;
}) {
  const [canManage,setCanManage]=useState(false);
  const [mode,setMode]=useState<"edit"|"delete"|null>(null);
  const [name,setName]=useState(sample.name||sample.sample_id);
  const [notes,setNotes]=useState(sample.notes||"");
  const [confirmation,setConfirmation]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  useEffect(()=>{
    let active=true;
    const refresh=()=>{
      if(!window.localStorage.getItem("wgs-auth-token")){setCanManage(false);return;}
      api.me().then(user=>{if(active)setCanManage(["admin","researcher"].includes(user.role))})
        .catch(()=>{if(active)setCanManage(false)});
    };
    refresh();window.addEventListener("wgs-auth-changed",refresh);
    return()=>{active=false;window.removeEventListener("wgs-auth-changed",refresh)};
  },[]);
  const running=["running","queued","uploading"].includes(sample.status)||sample.workflow?.state==="running";
  const open=(next:"edit"|"delete")=>{
    setMode(next);setName(sample.name||sample.sample_id);setNotes(sample.notes||"");
    setConfirmation("");setError("");setMessage("");
  };
  const save=async(event:FormEvent)=>{
    event.preventDefault();if(busy||!canManage)return;
    setBusy(true);setError("");
    try{const result=await api.editSample(sample.sample_id,{name,notes});onSaved({name:result.name,notes:result.notes});setMode(null);setMessage("样本信息已保存。")}
    catch(error){setError((error as Error).message)}finally{setBusy(false)}
  };
  const remove=async(event:FormEvent)=>{
    event.preventDefault();if(busy||!canManage||running||confirmation!==sample.sample_id)return;
    setBusy(true);setError("");
    try{await api.deleteSample(sample.sample_id);onDeleted(sample.sample_id)}
    catch(error){setError((error as Error).message)}finally{setBusy(false)}
  };
  return <section className="sample-management" aria-label="样本管理">
    <div className="sample-management-actions">
      <button className="button button-ghost" disabled={!canManage||busy} onClick={()=>open("edit")} title={!canManage?"请使用管理员或研究员账号登录":"编辑名称和备注"}><Pencil size={14}/>编辑样本</button>
      <button className="button button-danger" disabled={!canManage||busy||running} onClick={()=>open("delete")} title={running?"分析运行中，结束后可删除":!canManage?"请使用管理员或研究员账号登录":"永久删除样本及文件"}><Trash2 size={14}/>删除样本</button>
      {!canManage&&<span>登录管理员或研究员账号后可编辑、删除。</span>}
      {canManage&&running&&<span>分析运行中，暂不能删除。</span>}
    </div>
    {message&&<p className="notice" role="status">{message}</p>}
    {mode&&<form onSubmit={mode==="edit"?save:remove} className="sample-management-form">
      <div className="sample-management-heading"><strong>{mode==="edit"?"编辑样本信息":"永久删除样本"}</strong><button className="button button-ghost" type="button" disabled={busy} onClick={()=>setMode(null)} aria-label="关闭样本管理"><X size={14}/></button></div>
      {mode==="edit"?<>
        <label>样本 ID<input className="input" value={sample.sample_id} readOnly/></label>
        <label>样本名称<input className="input" maxLength={100} value={name} onChange={event=>setName(event.target.value)} placeholder={sample.sample_id}/></label>
        <label className="sample-notes-field">备注<textarea className="input" maxLength={2000} rows={3} value={notes} onChange={event=>setNotes(event.target.value)}/></label>
        <p>名称和备注可修改，样本 ID 保持不变。</p>
      </>:<>
        <p>将永久删除该样本的上传文件、分析产物、报告和任务记录，无法恢复。</p>
        <label>输入样本 ID「{sample.sample_id}」确认<input className="input" value={confirmation} onChange={event=>setConfirmation(event.target.value)} autoComplete="off" spellCheck={false}/></label>
      </>}
      {error&&<div className="error-banner" role="alert">{error}</div>}
      <div className="sample-management-buttons"><button type="button" className="button button-ghost" disabled={busy} onClick={()=>setMode(null)}>取消</button><button type="submit" className={`button ${mode==="delete"?"button-danger":"button-primary"}`} disabled={busy||!canManage||(mode==="delete"&&(running||confirmation!==sample.sample_id))}>{busy?"处理中…":mode==="edit"?"保存修改":"永久删除"}</button></div>
    </form>}
  </section>;
}
