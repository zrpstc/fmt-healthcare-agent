"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, Box, Check, ChevronRight, Container, KeyRound, Network, Plus, Save, Settings2, ShieldCheck, Sparkles, Trash2, UserCircle, X } from "lucide-react";
import { AgentConfig, api, RiskLevel, Skill, ToolInfo } from "@/lib/api";
import { SettingsSection, WorkspaceSettingsPanel } from "@/components/workspace-settings";

const blankAgent: AgentConfig = { id:"", name:"循证整理助手",kind:"subagent",parent_agent_id:"fmt-researcher", description:"", model:"", system_prompt:"", skill_ids:[], color:"ocean", enabled:true };
const blankSkill: Skill = { id:"", name:"", description:"", category:"自定义", tool_names:[], instructions:"", risk_level:"read", enabled:true };
type SettingsTab=SettingsSection|"skills";

export default function SettingsPage() {
  const [agents,setAgents]=useState<AgentConfig[]>([]); const [skills,setSkills]=useState<Skill[]>([]); const [tools,setTools]=useState<ToolInfo[]>([]);
  const [models,setModels]=useState<string[]>([]); const [selectedId,setSelectedId]=useState(""); const [draft,setDraft]=useState<AgentConfig>(blankAgent);
  const [skillDraft,setSkillDraft]=useState<Skill|null>(null); const [saving,setSaving]=useState(false); const [message,setMessage]=useState("");
  const [tab,setTab]=useState<SettingsTab>("user");

  const load=async()=>{ const [a,s,t,m]=await Promise.all([api.agents(true),api.skills(),api.tools(),api.models()]); setAgents(a);setSkills(s);setTools(t);setModels(m.models); const id=selectedId||a[0]?.id||""; setSelectedId(id); const found=a.find(x=>x.id===id); if(found)setDraft(found); };
  useEffect(()=>{load().catch(e=>setMessage(e.message));},[]);
  const selected=useMemo(()=>agents.find(a=>a.id===selectedId),[agents,selectedId]);
  const choose=(agent:AgentConfig)=>{setSelectedId(agent.id);setDraft({...agent});setMessage("")};
    const saveAgent=async()=>{setSaving(true);setMessage("");try{ selected?await api.updateAgent(selected.id,draft):await api.createAgent(draft);await load();setMessage("Agent配置已保存");}catch(e){setMessage((e as Error).message)}finally{setSaving(false)}};
  const removeAgent=async()=>{if(!selected||!confirm(`删除 ${selected.name}？`))return;await api.deleteAgent(selected.id);setSelectedId("");await load()};
  const saveSkill=async()=>{if(!skillDraft)return;setSaving(true);try{const exists=skills.some(s=>s.id===skillDraft.id);exists?await api.updateSkill(skillDraft.id,skillDraft):await api.createSkill(skillDraft);setSkillDraft(null);await load();setMessage("Skill配置已保存");}catch(e){setMessage((e as Error).message)}finally{setSaving(false)}};
  const removeSkill=async()=>{if(!skillDraft||!skills.some(s=>s.id===skillDraft.id)||!confirm(`删除 ${skillDraft.name}？`))return;await api.deleteSkill(skillDraft.id);setSkillDraft(null);await load()};
  const toggleSkill=(id:string)=>setDraft({...draft,skill_ids:draft.skill_ids.includes(id)?draft.skill_ids.filter(x=>x!==id):[...draft.skill_ids,id]});
  const toggleTool=(name:string)=>skillDraft&&setSkillDraft({...skillDraft,tool_names:skillDraft.tool_names.includes(name)?skillDraft.tool_names.filter(x=>x!==name):[...skillDraft.tool_names,name]});

  return <>
    <div className="page-intro"><div><p className="eyebrow">Control center</p><h1>设置中心</h1></div></div>
    <nav className="settings-tabs" aria-label="设置分类">
      <button className={tab==="user"?"is-active":""} onClick={()=>setTab("user")}><UserCircle size={15}/>用户界面</button>
      <button className={tab==="model"?"is-active":""} onClick={()=>setTab("model")}><KeyRound size={15}/>模型设置</button>
      <button className={tab==="mcp"?"is-active":""} onClick={()=>setTab("mcp")}><Network size={15}/>MCP 与知识库</button>
      <button className={tab==="sandbox"?"is-active":""} onClick={()=>setTab("sandbox")}><Container size={15}/>沙箱与工作区</button>
      <button className={tab==="skills"?"is-active":""} onClick={()=>setTab("skills")}><Sparkles size={15}/>Skills 功能库</button>
    </nav>
    {message&&<div className={message.includes("保存")?"notice":"error-banner"}>{message}</div>}
    {tab!=="skills"&&<WorkspaceSettingsPanel section={tab}/>} 
    {tab==="skills"&&<div className="settings-grid">
      <section className="panel agent-panel"><div className="panel-head"><div><h2>Agent 与 subagent</h2><span>1 个主 Agent · 循证整理按需委派</span></div><Bot size={17}/></div><div className="agent-list">
        {agents.map(agent=><button key={agent.id} className={`agent-card ${agent.id===selectedId?"is-selected":""}`} onClick={()=>choose(agent)}><span className={`agent-avatar ${agent.color}`}><Bot size={16}/></span><span><strong>{agent.name}</strong><small>{agent.description||"尚未填写说明"}</small><span className="agent-state">{agent.kind==="subagent"?"↳ subagent · ":"主 Agent · "}{agent.enabled?"● 已启用":"○ 已停用"}</span></span></button>)}
      </div></section>

      <section className="panel"><div className="panel-head"><div><h2>{draft.kind==="subagent"?"编辑 subagent":"编辑主 Agent"}</h2><span>{draft.id||"未命名配置"}</span></div><Settings2 size={17}/></div><div className="form-body">
        <div className="form-section"><h3 className="form-section-title"><span><Bot size={13}/></span>基本信息</h3><div className="field-grid">
          <label className="field"><span className="field-label">显示名称</span><input className="input" value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label>
          <label className="field"><span className="field-label">唯一 ID</span><input className="input" disabled={!!selected} value={draft.id} onChange={e=>setDraft({...draft,id:e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g,"-")})}/></label>
          <label className="field full"><span className="field-label">用途说明</span><input className="input" value={draft.description} onChange={e=>setDraft({...draft,description:e.target.value})} placeholder="这个Agent适合完成什么任务？"/></label>
          <label className="field"><span className="field-label">推理模型 <small>留空时自动选择</small></span><select className="select" value={draft.model} onChange={e=>setDraft({...draft,model:e.target.value})}><option value="">自动选择可用模型</option>{models.map(m=><option key={m}>{m}</option>)}</select></label>
          <label className="field"><span className="field-label">视觉标识</span><select className="select" value={draft.color} onChange={e=>setDraft({...draft,color:e.target.value})}><option value="ocean">深海蓝</option><option value="coral">珊瑚红</option><option value="teal">生物绿</option><option value="violet">证据紫</option><option value="amber">提醒橙</option></select></label>
        </div></div>
        <div className="form-section"><h3 className="form-section-title"><span><Sparkles size={13}/></span>角色指令</h3><label className="field"><span className="field-label">System Prompt <small>{draft.system_prompt.length}/12000</small></span><textarea className="textarea" value={draft.system_prompt} onChange={e=>setDraft({...draft,system_prompt:e.target.value})} placeholder="定义目标、专业边界、输出格式和判断原则…"/></label></div>
        <div className="form-section"><h3 className="form-section-title"><span><Box size={13}/></span>绑定 Skills</h3><div className="check-row">{skills.map(skill=><label key={skill.id} className={`check-card ${draft.skill_ids.includes(skill.id)?"is-checked":""}`}><input type="checkbox" checked={draft.skill_ids.includes(skill.id)} onChange={()=>toggleSkill(skill.id)}/><span><strong>{skill.name}</strong><br/><span style={{color:"var(--muted)"}}>{skill.description}</span></span></label>)}</div></div>
      </div><div className="form-actions"><button className="button button-danger" disabled={!selected||selected.id==="fmt-researcher"} onClick={removeAgent}><Trash2 size={14}/>删除</button><div className="actions-right"><label className="check-card" style={{padding:"8px 10px"}}><input type="checkbox" checked={draft.enabled} disabled={draft.id==="fmt-researcher"} onChange={e=>setDraft({...draft,enabled:e.target.checked})}/>启用</label><button className="button button-primary" disabled={saving||!draft.name||!draft.id} onClick={saveAgent}><Save size={14}/>{saving?"保存中":"保存配置"}</button></div></div></section>

      <section className="panel skills-panel"><div className="panel-head"><div><h2>Skills 能力库</h2><span>组合白名单工具与领域规则</span></div><button className="button button-ghost icon-button" onClick={()=>setSkillDraft({...blankSkill,id:`skill-${Date.now().toString().slice(-6)}`})}><Plus size={15}/></button></div><div className="skill-list">
        {skills.map(skill=><div className="skill-card" key={skill.id} onClick={()=>setSkillDraft({...skill})}><div className="skill-top"><span className="skill-icon"><ShieldCheck size={15}/></span><ChevronRight size={14}/></div><h3>{skill.name}</h3><p>{skill.description}</p><div className="skill-meta"><span className={`pill ${skill.risk_level}`}>{skill.risk_level==="read"?"只读":skill.risk_level==="confirm"?"需要确认":"敏感分析"}</span><span className="pill">{skill.tool_names.length} 个工具</span></div></div>)}
      </div></section>
    </div>}

    {skillDraft&&<div className="modal-backdrop"><div className="modal"><div className="modal-head"><h2>{skills.some(s=>s.id===skillDraft.id)?"编辑 Skill":"创建 Skill"}</h2><button className="button button-ghost icon-button" onClick={()=>setSkillDraft(null)}><X size={15}/></button></div><div className="modal-body"><div className="field-grid">
      <label className="field"><span className="field-label">Skill 名称</span><input className="input" value={skillDraft.name} onChange={e=>setSkillDraft({...skillDraft,name:e.target.value})}/></label>
      <label className="field"><span className="field-label">唯一 ID</span><input className="input" disabled={skills.some(s=>s.id===skillDraft.id)} value={skillDraft.id} onChange={e=>setSkillDraft({...skillDraft,id:e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g,"-")})}/></label>
      <label className="field"><span className="field-label">分类</span><input className="input" value={skillDraft.category} onChange={e=>setSkillDraft({...skillDraft,category:e.target.value})}/></label>
      <label className="field"><span className="field-label">风险级别</span><select className="select" value={skillDraft.risk_level} onChange={e=>setSkillDraft({...skillDraft,risk_level:e.target.value as RiskLevel})}><option value="read">只读</option><option value="sensitive">敏感分析</option><option value="confirm">需要确认</option></select></label>
      <label className="field full"><span className="field-label">说明</span><input className="input" value={skillDraft.description} onChange={e=>setSkillDraft({...skillDraft,description:e.target.value})}/></label>
      <label className="field full"><span className="field-label">Skill 指令</span><textarea className="textarea" value={skillDraft.instructions} onChange={e=>setSkillDraft({...skillDraft,instructions:e.target.value})}/></label>
      <div className="field full"><span className="field-label">选择已注册工具 <small>{skillDraft.tool_names.length}项</small></span><div className="tool-picker">{tools.map(tool=><label key={tool.name} className={`check-card ${skillDraft.tool_names.includes(tool.name)?"is-checked":""}`}><input type="checkbox" checked={skillDraft.tool_names.includes(tool.name)} onChange={()=>toggleTool(tool.name)}/><span><strong>{tool.name}</strong><br/><span style={{color:"var(--muted)"}}>{tool.description}</span></span></label>)}</div></div>
    </div></div><div className="modal-actions">{skills.some(s=>s.id===skillDraft.id)&&<button className="button button-danger" onClick={removeSkill}><Trash2 size={14}/>删除</button>}<button className="button button-ghost" onClick={()=>setSkillDraft(null)}>取消</button><button className="button button-primary" disabled={saving||!skillDraft.name||!skillDraft.id} onClick={saveSkill}><Check size={14}/>保存 Skill</button></div></div></div>}
  </>;
}
