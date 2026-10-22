export type RiskLevel = "read" | "sensitive" | "confirm";

export interface Skill {
  id: string; name: string; description: string; category: string; tool_names: string[];
  instructions: string; risk_level: RiskLevel; enabled: boolean;
}
export interface AgentConfig {
  id: string; name: string; description: string; model: string; system_prompt: string;
  skill_ids: string[]; color: string; enabled: boolean; created_at?: string; updated_at?: string;
}
export interface ToolInfo { name: string; description: string }
export interface TraceEvent { type: string; step?: number; content?: string; name?: string; params?: Record<string, unknown>; status?: "running"|"completed"|"failed" }
export interface PendingAction { id:string; kind:string; label:string; risk:string; params:Record<string,unknown> }
export interface CanvasItem { id:string;title:string;path:string;kind:"image"|"pdf"|"table"|"json"|"text";bytes:number;modified_at?:string }
export interface ChatTurn { answer: string; trace: TraceEvent[]; pending_actions: PendingAction[]; canvas_items:CanvasItem[]; model: string; run_id:string; tool_call_count:number;conversation_id:string }
export interface StoredMessage { id:string;role:"user"|"assistant";content:string;model:string;trace:{events?:TraceEvent[];canvas_items?:CanvasItem[];pending_actions?:PendingAction[]};created_at:string }
export interface Conversation { id:string;user_id:string;title:string;agent_id:string;status:string;created_at:string;updated_at:string;message_count:number;messages?:StoredMessage[] }
export interface AuthUser { id:string;username:string;email:string;display_name:string;role:"admin"|"researcher"|"viewer";is_active:boolean;created_at:string }
export interface AuthResult { access_token:string;token_type:string;expires_in:number;user:AuthUser }
export interface ModelServiceSettings { provider:"openai-compatible"|"local";base_url:string;api_key:string;has_api_key?:boolean;local_model:string;default_model:string }
export interface McpServerSettings { name:string;transport:"stdio"|"http"|"sse";command_or_url:string;enabled:boolean }
export interface WorkspaceSettings {
  display_name:string;model_service:ModelServiceSettings;mcp_servers:McpServerSettings[];knowledge_base_path:string;
  role_prompt:string;response_style:"concise"|"balanced"|"detailed";language:string;max_agent_steps:number;
  max_tool_calls:number;tool_timeout_s:number;loop_repeat_limit:number;confirm_dangerous_actions:boolean;
  audit_enabled:boolean;allow_sensitive_analysis:boolean;
  sandbox_mode:"process"|"docker";sandbox_workspace:string;sandbox_allowed_commands:string[];sandbox_timeout_s:number;
  sandbox_cpu_limit:number;sandbox_memory_mb:number;sandbox_network_enabled:boolean;docker_image:string;
  docker_workspace:string;docker_read_only_root:boolean;
  artifact_sandbox_root?:string;
  canvas_enabled:boolean;canvas_agent_access:boolean;canvas_max_file_mb:number;
}
export interface ArtifactInfo { exists: boolean; bytes: number; updated_at?: string | null }
export interface WorkflowSummary {
  state: string; progress: number; submitted_at?: string | null; artifacts: Record<string, boolean>;
}
export interface SampleSummary {
  sample_id: string; status: string; updated_at?: string | null; species_total: number;
  name?: string; notes?: string; metadata_updated_at?: string | null;
  species_high: number; species_low: number; enterotype: string; pathway_total: number;
  artifacts: Record<string, ArtifactInfo>;
  workflow?: WorkflowSummary | null;
}
export interface SampleList { count: number; filtered_count: number; status_counts: Record<string, number>; samples: SampleSummary[] }
export interface SampleDetail { summary: SampleSummary; analysis: Record<string, any> }
export interface ReportRow { sample_id: string; name?: string; updated_at?: string | null; artifacts: Record<string, ArtifactInfo>; status?: "report_ready"|"report_partial"|"analysis_ready"|"bioinformatics_complete"|"missing_analysis" }
export interface ReportList { count: number; pdf_count: number; markdown_count: number; reports: ReportRow[] }
export interface KnowledgeStats {
  papers: number; full_text: number; pathways: number; metabolites: number; microbes: number;
  year_min?: number; year_max?: number; diseases: Array<{name:string;count:number}>;
}
export interface Paper {
  id:number; pmid:string; doi?:string; title:string; abstract?:string; journal_name?:string;
  impact_factor?:number; publication_year?:number; sequencing_strategy?:string; sequencing_platform?:string;
  sample_source?:string; target_disease_code?:string; target_disease_name?:string; pmc_id?:string;
  full_text_available?:number; [key:string]:any;
}
export interface LitkgSource { kind:string; label:string; knowledge_base_id:number; endpoint:string }
export interface LitkgStatus {
  available:boolean; source:LitkgSource; document_count:number; claim_count:number; ready_count:number;
  batch_count:number; latest_batch?:Record<string,any>|null; message?:string;
}
export interface LitkgDocument {
  id:number; filename:string; title?:string; status:string; error?:string|null; created_at?:string; updated_at?:string;
  chunk_count?:number; chunk_done_count?:number; chunk_failed_count?:number; claim_count?:number;
}
export interface GraphNode { id:number|string; label:string; type:string; normalized_id?:string|null }
export interface GraphEvidence { claim_id?:number|string; document_id?:number; filename?:string; section?:string; sentence?:string; confidence?:number }
export interface GraphEdge {
  id:number|string; source:number|string; target:number|string; label:string; predicate?:string; confidence?:number;
  max_confidence?:number; negated?:boolean; speculative?:boolean; evidence_count?:number; document_count?:number;
  evidence?:string; evidence_samples?:GraphEvidence[]; qualifiers?:Record<string,any>;
}
export interface KnowledgeGraph {
  nodes:GraphNode[]; edges:GraphEdge[]; summary:{node_count:number;relation_count:number;represented_document_count:number};
  knowledge_base_id:number; document_id?:number|null; source:LitkgSource;
}

const BASE = "/backend/api";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const token=typeof window!=="undefined"?window.localStorage.getItem("wgs-auth-token"):null;
  const response = await fetch(`${BASE}${path}`, { ...init, headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...(token?{Authorization:`Bearer ${token}`}:{ }), ...(init?.headers || {}) } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}
export const api = {
  register: (value:{username:string;email:string;password:string;display_name:string}) => request<AuthResult>("/backend/auth/register",{method:"POST",body:JSON.stringify({...value,role:"researcher"})}),
  login: (identity:string,password:string) => request<AuthResult>("/backend/auth/login",{method:"POST",body:JSON.stringify({identity,password})}),
  me: () => request<AuthUser>("/backend/auth/me"),
  logout: () => request<{logged_out:boolean}>("/backend/auth/logout",{method:"POST"}),
  authUsers: () => request<{users:AuthUser[];count:number}>("/backend/auth/users"),
  updateUserRole: (id:string,role:AuthUser["role"]) => request<AuthUser>(`/backend/auth/users/${encodeURIComponent(id)}/role`,{method:"PATCH",body:JSON.stringify({role})}),
  agents: () => request<AgentConfig[]>("/agents"),
  createAgent: (value: Partial<AgentConfig>) => request<AgentConfig>("/agents", { method: "POST", body: JSON.stringify(value) }),
  updateAgent: (id: string, value: Partial<AgentConfig>) => request<AgentConfig>(`/agents/${id}`, { method: "PUT", body: JSON.stringify(value) }),
  deleteAgent: (id: string) => request(`/agents/${id}`, { method: "DELETE" }),
  skills: () => request<Skill[]>("/skills"),
  tools: () => request<ToolInfo[]>("/tools"),
  createSkill: (value: Partial<Skill>) => request<Skill>("/skills", { method: "POST", body: JSON.stringify(value) }),
  updateSkill: (id: string, value: Partial<Skill>) => request<Skill>(`/skills/${id}`, { method: "PUT", body: JSON.stringify(value) }),
  deleteSkill: (id: string) => request(`/skills/${id}`, { method: "DELETE" }),
  models: () => request<{models: string[]; available: boolean; message?: string}>("/models"),
  settings: () => request<WorkspaceSettings>("/settings"),
  saveSettings: (value:WorkspaceSettings) => request<WorkspaceSettings>("/settings",{method:"PUT",body:JSON.stringify(value)}),
  testModel: (model_service:ModelServiceSettings) => request<{ok:boolean;model:string;latency_ms:number}>("/settings/model-test",{method:"POST",body:JSON.stringify({model_service})}),
  testSandbox: (settings:WorkspaceSettings) => request<{ok:boolean;mode:string;workspace:string;message?:string}>("/settings/sandbox-test",{method:"POST",body:JSON.stringify({settings})}),
  chat: (value: unknown) => request<ChatTurn>("/chat", { method: "POST", body: JSON.stringify(value) }),
  confirmAction: (actionId:string) => request<Record<string,unknown>>("/actions/confirm",{method:"POST",body:JSON.stringify({action_id:actionId,confirmed:true})}),
  saveCanvasFile: (path:string,content:string) => request<{status:string;canvas:CanvasItem}>("/canvas/file",{method:"PUT",body:JSON.stringify({path,content,confirmed:true})}),
  conversations: () => request<{conversations:Conversation[];count:number;database:string}>("/backend/conversations"),
  conversation: (id:string) => request<Conversation>(`/backend/conversations/${encodeURIComponent(id)}`),
  sandboxFiles: (id:string) => request<{conversation_id:string;count:number;files:CanvasItem[]}>(`/conversations/${encodeURIComponent(id)}/sandbox/files`),
  createConversation: (agentId:string) => request<Conversation>("/backend/conversations",{method:"POST",body:JSON.stringify({agent_id:agentId,title:"新对话"})}),
  deleteConversation: (id:string) => request(`/backend/conversations/${encodeURIComponent(id)}`,{method:"DELETE"}),
  samples: (q="") => request<SampleList>(`/samples?q=${encodeURIComponent(q)}`,{cache:"no-store"}),
  uploadSample: (value:{sampleId:string;layout:"single"|"paired";read1:File;read2?:File|null}) => {
    const form=new FormData(); form.set("sample_id",value.sampleId); form.set("layout",value.layout); form.set("read1",value.read1);
    if(value.read2)form.set("read2",value.read2);
    return request<Record<string,any>>("/samples/upload",{method:"POST",body:form});
  },
  sampleWorkflow: (id:string) => request<Record<string,any>>(`/samples/${encodeURIComponent(id)}/workflow`),
  sample: (id:string) => request<SampleDetail>(`/samples/${encodeURIComponent(id)}`),
  editSample: (id:string,value:{name:string;notes:string}) => request<{status:string;sample_id:string;name:string;notes:string}>(`/samples/${encodeURIComponent(id)}`,{method:"PATCH",body:JSON.stringify(value)}),
  deleteSample: (id:string) => request<{status:string;sample_id:string;removed_paths:number}>(`/samples/${encodeURIComponent(id)}`,{method:"DELETE",body:JSON.stringify({confirmed:true,confirm_sample_id:id})}),
  reports: (q="") => request<ReportList>(`/reports?q=${encodeURIComponent(q)}`),
  generateReport: (id:string) => request<{status:string;sample_id:string;artifacts:Record<string,ArtifactInfo>;llm_status?:string;llm_accepted_topics?:number}>(`/reports/${encodeURIComponent(id)}/generate`, {method:"POST",body:JSON.stringify({confirmed:true})}),
  knowledgeStats: () => request<KnowledgeStats>("/knowledge/stats"),
  papers: (params:Record<string,string|number|boolean|undefined>) => {
    const query=new URLSearchParams(); Object.entries(params).forEach(([key,value])=>{if(value!==undefined&&value!=="")query.set(key,String(value))});
    return request<{count:number;papers:Paper[]}>(`/knowledge/papers?${query.toString()}`);
  },
  paper: (pmid:string) => request<Paper>(`/knowledge/papers/${encodeURIComponent(pmid)}`),
  bindPaper: (pmid:string,sampleId:string) => request(`/knowledge/papers/${encodeURIComponent(pmid)}/bind`, {method:"POST",body:JSON.stringify({sample_id:sampleId})}),
  litkgStatus: () => request<LitkgStatus>("/knowledge/remote/status"),
  litkgDocuments: () => request<{knowledge_base_id:number;documents:LitkgDocument[];source:LitkgSource}>("/knowledge/remote/documents"),
  litkgClaims: (q:string,limit=30) => request<{count:number;claims:Array<Record<string,any>>;source:LitkgSource}>(`/knowledge/remote/claims?q=${encodeURIComponent(q)}&limit=${limit}`),
  bindLitkgClaim: (claimId:number|string,sampleId:string) => request(`/knowledge/remote/claims/${encodeURIComponent(String(claimId))}/bind`, {method:"POST",body:JSON.stringify({sample_id:sampleId})}),
  knowledgeGraph: (params:Record<string,string|number|boolean|undefined>) => {
    const query=new URLSearchParams(); Object.entries(params).forEach(([key,value])=>{if(value!==undefined&&value!=="")query.set(key,String(value))});
    return request<KnowledgeGraph>(`/knowledge/remote/graph?${query.toString()}`);
  },
};

export const backendUrl=(path:string)=>`/backend/api${path}`;
export const canvasFileUrl=(path:string)=>backendUrl(`/canvas/file?path=${encodeURIComponent(path)}`);
export async function canvasText(path:string):Promise<string>{
  const response=await fetch(canvasFileUrl(path));
  if(!response.ok){const payload=await response.json().catch(()=>({}));throw new Error(payload.detail||`文件读取失败 (${response.status})`)}
  return response.text();
}
