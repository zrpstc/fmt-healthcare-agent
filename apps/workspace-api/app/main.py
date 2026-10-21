"""FastAPI surface for the reusable Agent/Skill workspace."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent_chat import TOOLS, _atomic_text_write, _audit, _sandbox_canvas_item, _sandbox_dir, execute_confirmed_action, run_agent_turn
from wgs_agent.pipeline.upload_workflow import get_workflow_status, submit_uploaded_sample
from app.local_chat import LocalChatError, list_models
from wgs_agent.tools.knowledge_tools import claim_record_to_reference
from wgs_fmt_platform.config import get_settings
from wgs_fmt_platform.knowledge.litkg_catalog import (
    normalize_knowledge_bases,
    parse_knowledge_base_ids,
    select_knowledge_bases,
)
from wgs_fmt_platform.infrastructure.api import router as infrastructure_router
from wgs_fmt_platform.infrastructure.api import ensure_local_user
from wgs_fmt_platform.infrastructure.database import Conversation, Message, SessionLocal, create_schema


ROOT = Path(__file__).resolve().parents[3]
STORE = Path(os.environ.get("WGS_AGENT_CONFIG_DIR", ROOT / "data" / "agent-config"))
AGENTS_FILE = STORE / "agents.json"
SKILLS_FILE = STORE / "skills.json"
SETTINGS_FILE = STORE / "workspace-settings.json"
PENDING_FILE = STORE / "pending-actions.json"
LOCK = Lock()
SAFE_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
TOOL_NAMES = {item["function"]["name"] for item in TOOLS}
RESULTS_DIR = Path(os.environ.get("WGS_RESULTS_DIR", ROOT / "data" / "results"))
KNOWLEDGE_DB = Path(os.environ.get("WGS_KNOWLEDGE_DB", ROOT / "knowledge_base" / "kb.db"))
RUNNER_STATUS = Path(os.environ.get(
    "WGS_RUNNER_STATUS",
    "/storage/main/users/zhangrongpeng/data/fmt/postfmt_processed/status/runner_status.tsv",
))
SAMPLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


DEFAULT_SKILLS = [
    {
        "id": "sample-observer", "name": "样本状态观察", "description": "查询样本、Pipeline进度和报告产物。",
        "category": "数据访问", "tool_names": ["list_samples", "get_sample_status", "pipeline_check", "get_report_status"],
        "instructions": "先检查样本是否存在，再区分已完成、运行中和缺失产物。", "risk_level": "read", "enabled": True,
    },
    {
        "id": "microbiome-analysis", "name": "菌群分析", "description": "分析物种、肠型、通路和代谢潜能。",
        "category": "领域分析", "tool_names": ["load_species_data", "compare_reference", "analyze_enterotype", "analyze_pathways", "analyze_metabolites"],
        "instructions": "将观测值、参考范围与推断严格分开陈述。", "risk_level": "read", "enabled": True,
    },
    {
        "id": "evidence-retrieval", "name": "循证检索", "description": "组合本地知识库和PubMed证据。",
        "category": "知识检索", "tool_names": ["search_knowledge_base", "search_pubmed"],
        "instructions": "优先返回可追溯来源，不将关联性表述为因果。", "risk_level": "read", "enabled": True,
    },
    {
        "id": "clinical-association", "name": "疾病与药物关联", "description": "只读分析疾病和药物关联。",
        "category": "敏感分析", "tool_names": ["analyze_drugs", "analyze_diseases"],
        "instructions": "必须附带科研用途声明，禁止给出诊疗或用药指令。", "risk_level": "sensitive", "enabled": True,
    },
    {
        "id": "controlled-actions", "name": "受控执行", "description": "申请Pipeline运行或报告生成，执行前必须确认。",
        "category": "操作", "tool_names": ["request_pipeline_run", "request_report_generation"],
        "instructions": "只创建待确认动作，不得声称操作已经执行。", "risk_level": "confirm", "enabled": True,
    },
]

DEFAULT_AGENTS = [
    {
        "id": "fmt-researcher", "name": "FMT科研助手", "description": "面向宏基因组与FMT研究的综合分析智能体。",
        "model": "", "system_prompt": "围绕样本数据形成可核验的分析结论，清楚标注证据层级与不确定性。",
        "skill_ids": ["sample-observer", "microbiome-analysis", "evidence-retrieval", "controlled-actions"],
        "color": "ocean", "enabled": True, "created_at": _now(), "updated_at": _now(),
    },
    {
        "id": "evidence-curator", "name": "循证整理助手", "description": "聚焦知识库、PubMed与报告证据链。",
        "model": "", "system_prompt": "优先检索和交叉验证来源，输出简洁的证据摘要与引用。",
        "skill_ids": ["sample-observer", "evidence-retrieval"], "color": "coral", "enabled": True,
        "created_at": _now(), "updated_at": _now(),
    },
]


class SkillPayload(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="自定义", max_length=40)
    tool_names: list[str] = Field(default_factory=list, max_length=30)
    instructions: str = Field(default="", max_length=5000)
    risk_level: str = Field(default="read", pattern="^(read|sensitive|confirm)$")
    enabled: bool = True


class AgentPayload(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    system_prompt: str = Field(default="", max_length=12000)
    skill_ids: list[str] = Field(default_factory=list, max_length=50)
    color: str = Field(default="ocean", pattern="^(ocean|coral|violet|teal|amber)$")
    enabled: bool = True


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=30000)


class ChatPayload(BaseModel):
    agent_id: str
    message: str = Field(min_length=1, max_length=30000)
    sample_id: str = Field(default="", max_length=80)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)
    conversation_id: str = Field(default="", max_length=36)


class CanvasWritePayload(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=2 * 1024 * 1024)
    confirmed: bool = False


class ReportGeneratePayload(BaseModel):
    confirmed: bool = False


class EvidenceBindPayload(BaseModel):
    sample_id: str = Field(min_length=1, max_length=128)


class LitKGAskPayload(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    knowledge_base_ids: list[int] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=12, ge=1, le=30)
    hops: int = Field(default=1, ge=0, le=2)
    generate: bool = True


class ModelServicePayload(BaseModel):
    provider: str = Field(default="openai-compatible", pattern="^(openai-compatible|local)$")
    base_url: str = Field(default="http://127.0.0.1:11434/v1", max_length=500)
    api_key: str = Field(default="", max_length=1000)
    local_model: str = Field(default="", max_length=200)
    default_model: str = Field(default="", max_length=200)


class McpServerPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    transport: str = Field(default="stdio", pattern="^(stdio|http|sse)$")
    command_or_url: str = Field(default="", max_length=1000)
    enabled: bool = True


class WorkspaceSettingsPayload(BaseModel):
    display_name: str = Field(default="研究员", max_length=80)
    model_service: ModelServicePayload = Field(default_factory=ModelServicePayload)
    mcp_servers: list[McpServerPayload] = Field(default_factory=list, max_length=20)
    knowledge_base_path: str = Field(default="knowledge_base/kb.db", max_length=1000)
    role_prompt: str = Field(default="", max_length=12000)
    response_style: str = Field(default="balanced", pattern="^(concise|balanced|detailed)$")
    language: str = Field(default="zh-CN", max_length=20)
    max_agent_steps: int = Field(default=8, ge=1, le=30)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    tool_timeout_s: int = Field(default=120, ge=5, le=1800)
    loop_repeat_limit: int = Field(default=2, ge=1, le=10)
    confirm_dangerous_actions: bool = True
    audit_enabled: bool = True
    allow_sensitive_analysis: bool = False
    sandbox_mode: str = Field(default="process", pattern="^(process|docker)$")
    sandbox_workspace: str = Field(default="workspaces/default", max_length=1000)
    sandbox_allowed_commands: list[str] = Field(default_factory=lambda: ["python", "python3", "bash", "sh"], max_length=50)
    sandbox_timeout_s: int = Field(default=300, ge=5, le=7200)
    sandbox_cpu_limit: float = Field(default=2.0, ge=0.1, le=64)
    sandbox_memory_mb: int = Field(default=4096, ge=128, le=262144)
    sandbox_network_enabled: bool = False
    docker_image: str = Field(default="python:3.12-slim", max_length=300)
    docker_workspace: str = Field(default="/workspace", max_length=300)
    docker_read_only_root: bool = True
    canvas_enabled: bool = True
    canvas_agent_access: bool = True
    canvas_max_file_mb: int = Field(default=20, ge=1, le=200)


class ModelTestPayload(BaseModel):
    model_service: ModelServicePayload


class ConfirmActionPayload(BaseModel):
    action_id: str = Field(min_length=8, max_length=64)
    confirmed: bool = True


class SandboxTestPayload(BaseModel):
    settings: WorkspaceSettingsPayload


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean[:48] or f"item-{uuid.uuid4().hex[:8]}"


def _read(path: Path, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else default
    except (OSError, ValueError):
        return default


def _write(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _read_object(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def _default_settings() -> dict[str, Any]:
    return WorkspaceSettingsPayload().model_dump()


def _settings(*, masked: bool = False) -> dict[str, Any]:
    value = _read_object(SETTINGS_FILE, _default_settings())
    merged = WorkspaceSettingsPayload.model_validate(value).model_dump()
    merged["artifact_sandbox_root"] = str(
        Path(
            os.environ.get(
                "WGS_AGENT_SANDBOX_ROOT",
                "/storage/main/users/zhangrongpeng/data/fmt/wgs-fmt-agent-v2-data/sandboxes",
            )
        ).resolve()
    )
    key = merged["model_service"].get("api_key", "")
    if masked and key:
        merged["model_service"]["api_key"] = f"••••{key[-4:]}"
        merged["model_service"]["has_api_key"] = True
    elif masked:
        merged["model_service"]["has_api_key"] = False
    return merged


def _bootstrap() -> None:
    with LOCK:
        if not SKILLS_FILE.exists():
            _write(SKILLS_FILE, DEFAULT_SKILLS)
        if not AGENTS_FILE.exists():
            _write(AGENTS_FILE, DEFAULT_AGENTS)
        if not SETTINGS_FILE.exists():
            _write_object(SETTINGS_FILE, _default_settings())
        if not PENDING_FILE.exists():
            _write_object(PENDING_FILE, {})
    create_schema()
    with SessionLocal() as session:
        ensure_local_user(session)
        session.commit()


def _valid_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise HTTPException(422, "ID仅允许小写字母、数字、短横线和下划线。")
    return value


app = FastAPI(title="WGS-FMT Agent Workspace API", version="1.0.0")
app.include_router(infrastructure_router, prefix="/api/backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_bootstrap()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-workspace-api"}


@app.get("/api/models")
def models() -> dict[str, Any]:
    try:
        return {"models": list_models(), "available": True}
    except LocalChatError as exc:
        return {"models": [], "available": False, "message": str(exc)}


@app.get("/api/settings")
def get_workspace_settings() -> dict[str, Any]:
    return _settings(masked=True)


@app.put("/api/settings")
def update_workspace_settings(payload: WorkspaceSettingsPayload) -> dict[str, Any]:
    value = payload.model_dump()
    # Destructive operations are always confirmed in the Web workspace. This
    # server-side invariant cannot be disabled by a forged browser payload.
    value["confirm_dangerous_actions"] = True
    allowed_root = Path(os.environ.get("WGS_SANDBOX_ALLOWED_ROOT", ROOT)).resolve()
    workspace = Path(value["sandbox_workspace"])
    workspace = (ROOT / workspace).resolve() if not workspace.is_absolute() else workspace.resolve()
    if not workspace.is_relative_to(allowed_root):
        raise HTTPException(422, f"沙箱工作区必须位于允许根目录内：{allowed_root}")
    if any(not re.fullmatch(r"[A-Za-z0-9_.+-]+", command) for command in value["sandbox_allowed_commands"]):
        raise HTTPException(422, "命令白名单包含非法名称。")
    value["sandbox_workspace"] = str(workspace)
    current = _settings()
    submitted_key = value["model_service"].get("api_key", "")
    if not submitted_key or submitted_key.startswith("••••"):
        value["model_service"]["api_key"] = current["model_service"].get("api_key", "")
    with LOCK:
        _write_object(SETTINGS_FILE, value)
    return _settings(masked=True)


@app.post("/api/settings/model-test")
def test_model_service(payload: ModelTestPayload) -> dict[str, Any]:
    config = payload.model_service.model_dump()
    if not config["api_key"] or config["api_key"].startswith("••••"):
        config["api_key"] = _settings()["model_service"].get("api_key", "")
    model = config["default_model"] or config["local_model"]
    if not model:
        raise HTTPException(422, "请先填写默认模型或本地模型名称。")
    url = config["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {config['api_key'] or 'local-no-key-required'}"}
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 8, "temperature": 0}
    started = datetime.now(UTC)
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=20.0)
        response.raise_for_status()
        latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return {"ok": True, "model": model, "latency_ms": latency}
    except Exception as exc:
        raise HTTPException(502, f"模型服务连接失败：{exc}") from exc


@app.post("/api/settings/sandbox-test")
def test_sandbox(payload: SandboxTestPayload) -> dict[str, Any]:
    config = payload.settings
    allowed_root = Path(os.environ.get("WGS_SANDBOX_ALLOWED_ROOT", ROOT)).resolve()
    workspace = Path(config.sandbox_workspace)
    workspace = (ROOT / workspace).resolve() if not workspace.is_absolute() else workspace.resolve()
    if not workspace.is_relative_to(allowed_root):
        raise HTTPException(422, f"工作区越出允许根目录：{allowed_root}")
    if config.sandbox_mode == "docker":
        binary = shutil.which("docker")
        if not binary:
            return {"ok": False, "mode": "docker", "workspace": str(workspace), "message": "当前运行环境未安装 Docker。"}
        try:
            subprocess.run([binary, "info"], check=True, capture_output=True, text=True, timeout=10)
        except Exception as exc:
            return {"ok": False, "mode": "docker", "workspace": str(workspace), "message": f"Docker 不可用：{exc}"}
    return {"ok": True, "mode": config.sandbox_mode, "workspace": str(workspace), "allowed_root": str(allowed_root), "network_enabled": config.sandbox_network_enabled}


@app.get("/api/tools")
def tools() -> list[dict[str, Any]]:
    return [{"name": item["function"]["name"], "description": item["function"].get("description", "")} for item in TOOLS]


@app.get("/api/skills")
def get_skills() -> list[dict[str, Any]]:
    return _read(SKILLS_FILE, DEFAULT_SKILLS)


@app.post("/api/skills")
def create_skill(payload: SkillPayload) -> dict[str, Any]:
    data = payload.model_dump()
    data["id"] = _valid_id(data.get("id") or _slug(payload.name))
    unknown = set(data["tool_names"]) - TOOL_NAMES
    if unknown:
        raise HTTPException(422, f"未注册工具: {', '.join(sorted(unknown))}")
    with LOCK:
        items = _read(SKILLS_FILE, DEFAULT_SKILLS)
        if any(item["id"] == data["id"] for item in items):
            raise HTTPException(409, "Skill ID已存在。")
        items.append(data); _write(SKILLS_FILE, items)
    return data


@app.put("/api/skills/{skill_id}")
def update_skill(skill_id: str, payload: SkillPayload) -> dict[str, Any]:
    skill_id = _valid_id(skill_id)
    data = {**payload.model_dump(), "id": skill_id}
    unknown = set(data["tool_names"]) - TOOL_NAMES
    if unknown:
        raise HTTPException(422, f"未注册工具: {', '.join(sorted(unknown))}")
    with LOCK:
        items = _read(SKILLS_FILE, DEFAULT_SKILLS)
        index = next((i for i, item in enumerate(items) if item["id"] == skill_id), None)
        if index is None: raise HTTPException(404, "Skill不存在。")
        items[index] = data; _write(SKILLS_FILE, items)
    return data


@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: str) -> dict[str, bool]:
    skill_id = _valid_id(skill_id)
    with LOCK:
        items = _read(SKILLS_FILE, DEFAULT_SKILLS)
        kept = [item for item in items if item["id"] != skill_id]
        if len(kept) == len(items): raise HTTPException(404, "Skill不存在。")
        _write(SKILLS_FILE, kept)
        agents = _read(AGENTS_FILE, DEFAULT_AGENTS)
        for agent in agents:
            agent["skill_ids"] = [value for value in agent.get("skill_ids", []) if value != skill_id]
        _write(AGENTS_FILE, agents)
    return {"deleted": True}


@app.get("/api/agents")
def get_agents() -> list[dict[str, Any]]:
    return _read(AGENTS_FILE, DEFAULT_AGENTS)


@app.post("/api/agents")
def create_agent(payload: AgentPayload) -> dict[str, Any]:
    data = payload.model_dump(); data["id"] = _valid_id(data.get("id") or _slug(payload.name))
    skills = {item["id"] for item in _read(SKILLS_FILE, DEFAULT_SKILLS)}
    if set(data["skill_ids"]) - skills: raise HTTPException(422, "Agent引用了不存在的Skill。")
    data.update(created_at=_now(), updated_at=_now())
    with LOCK:
        items = _read(AGENTS_FILE, DEFAULT_AGENTS)
        if any(item["id"] == data["id"] for item in items): raise HTTPException(409, "Agent ID已存在。")
        items.append(data); _write(AGENTS_FILE, items)
    return data


@app.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, payload: AgentPayload) -> dict[str, Any]:
    agent_id = _valid_id(agent_id)
    skills = {item["id"] for item in _read(SKILLS_FILE, DEFAULT_SKILLS)}
    if set(payload.skill_ids) - skills: raise HTTPException(422, "Agent引用了不存在的Skill。")
    with LOCK:
        items = _read(AGENTS_FILE, DEFAULT_AGENTS)
        index = next((i for i, item in enumerate(items) if item["id"] == agent_id), None)
        if index is None: raise HTTPException(404, "Agent不存在。")
        data = {**payload.model_dump(), "id": agent_id, "created_at": items[index].get("created_at", _now()), "updated_at": _now()}
        items[index] = data; _write(AGENTS_FILE, items)
    return data


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str) -> dict[str, bool]:
    agent_id = _valid_id(agent_id)
    with LOCK:
        items = _read(AGENTS_FILE, DEFAULT_AGENTS)
        kept = [item for item in items if item["id"] != agent_id]
        if len(kept) == len(items): raise HTTPException(404, "Agent不存在。")
        _write(AGENTS_FILE, kept)
    return {"deleted": True}


@app.post("/api/chat")
def chat(payload: ChatPayload) -> dict[str, Any]:
    agents = _read(AGENTS_FILE, DEFAULT_AGENTS)
    agent = next((item for item in agents if item["id"] == payload.agent_id and item.get("enabled", True)), None)
    if agent is None: raise HTTPException(404, "Agent不存在或未启用。")
    skills_by_id = {item["id"]: item for item in _read(SKILLS_FILE, DEFAULT_SKILLS)}
    selected = [skills_by_id[sid] for sid in agent.get("skill_ids", []) if sid in skills_by_id and skills_by_id[sid].get("enabled", True)]
    allowed = sorted({name for skill in selected for name in skill.get("tool_names", []) if name in TOOL_NAMES})
    skill_context = "\n\n".join(f"Skill：{skill['name']}\n{skill.get('instructions', '')}" for skill in selected)
    workspace = _settings()
    if workspace.get("canvas_enabled") and workspace.get("canvas_agent_access"):
        allowed.append("open_in_canvas")
    allowed.extend(["list_sandbox_files", "read_sandbox_file", "create_sandbox_markdown", "request_delete_sandbox_file"])
    allowed = sorted(set(allowed))
    service = workspace["model_service"]
    model = agent.get("model", "") or service.get("default_model", "") or service.get("local_model", "")
    if not model:
        try: model = list_models()[0]
        except LocalChatError as exc: raise HTTPException(503, str(exc)) from exc
    with SessionLocal() as session:
        conversation = session.get(Conversation, payload.conversation_id) if payload.conversation_id else None
        if payload.conversation_id and conversation is None:
            raise HTTPException(404, "会话不存在。")
        if conversation is None:
            user = ensure_local_user(session)
            conversation = Conversation(user_id=user.id, agent_id=payload.agent_id, title=payload.message.strip()[:48] or "新对话")
            session.add(conversation)
            session.flush()
        stored_history = [{"role": row.role, "content": row.content} for row in conversation.messages[-30:]]
        session.add(Message(conversation_id=conversation.id, role="user", content=payload.message))
        conversation.agent_id = payload.agent_id
        if conversation.title == "新对话":
            conversation.title = payload.message.strip()[:48] or "新对话"
        session.commit()
        conversation_id = conversation.id
        sandbox_user_id = conversation.user_id
    try:
        result = run_agent_turn(
            model=model,
            history=stored_history or [item.model_dump() for item in payload.history],
            prompt=payload.message,
            current_sample_id=payload.sample_id,
            allowed_tools=allowed,
            extra_system_prompt=(
                f"\n当前Agent配置：\n{agent.get('system_prompt', '')}"
                f"\n\n工作区角色提示：\n{workspace.get('role_prompt', '')}"
                f"\n\n回答语言：{workspace.get('language')}；详细程度：{workspace.get('response_style')}"
                f"\n\n已启用Skills：\n{skill_context}"
            ),
            base_url=service.get("base_url", ""),
            api_key=service.get("api_key", ""),
            max_steps=workspace["max_agent_steps"],
            max_tool_calls=workspace["max_tool_calls"],
            tool_timeout_s=workspace["tool_timeout_s"],
            loop_repeat_limit=workspace["loop_repeat_limit"],
            allow_sensitive=workspace["allow_sensitive_analysis"],
            audit_enabled=workspace["audit_enabled"],
            sandbox_user_id=sandbox_user_id,
            sandbox_conversation_id=conversation_id,
        )
        if result.get("pending_actions"):
            with LOCK:
                pending = _read_object(PENDING_FILE, {})
                for action in result["pending_actions"]:
                    pending[action["id"]] = {**action, "created_at": _now(), "agent_id": payload.agent_id}
                _write_object(PENDING_FILE, pending)
        with SessionLocal() as session:
            conversation = session.get(Conversation, conversation_id)
            session.add(Message(conversation_id=conversation_id, role="assistant", content=result.get("answer", ""), model=result.get("model", ""), trace={"events": result.get("trace", []), "canvas_items": result.get("canvas_items", []), "pending_actions": result.get("pending_actions", [])}))
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)
            session.commit()
        return {**result, "conversation_id": conversation_id}
    except LocalChatError as exc:
        raise HTTPException(502, str(exc)) from exc


def _canvas_path(value: str) -> Path:
    if not value or "\x00" in value:
        raise HTTPException(422, "Canvas 文件路径无效。")
    if value.startswith("sandbox://"):
        parts = value[len("sandbox://"):].split("/", 2)
        if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item) for item in parts[:2]):
            raise HTTPException(422, "Canvas 沙盒路径无效。")
        sandbox_root = Path(os.environ.get("WGS_AGENT_SANDBOX_ROOT", "/storage/main/users/zhangrongpeng/data/fmt/wgs-fmt-agent-v2-data/sandboxes")).resolve()
        scope_root = (sandbox_root / parts[0] / parts[1]).resolve()
        path = (scope_root / parts[2]).resolve()
        try:
            path.relative_to(scope_root)
        except ValueError as exc:
            raise HTTPException(403, "Canvas 沙盒路径越界。") from exc
        if path.is_symlink():
            raise HTTPException(403, "Canvas 不读取沙盒符号链接。")
    else:
        path = (ROOT / value).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError as exc:
            raise HTTPException(403, "Canvas 只能访问项目工作区或当前会话沙盒。") from exc
    if not path.is_file():
        raise HTTPException(404, "Canvas 文件不存在。")
    settings = _settings()
    limit = int(settings.get("canvas_max_file_mb", 20)) * 1024 * 1024
    if path.stat().st_size > limit:
        raise HTTPException(413, "Canvas 文件超过大小限制。")
    return path


@app.get("/api/canvas/file")
def canvas_file(path: str = Query(min_length=1, max_length=1000)) -> FileResponse:
    if not _settings().get("canvas_enabled", True):
        raise HTTPException(403, "Canvas 功能未启用。")
    target = _canvas_path(path)
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@app.put("/api/canvas/file")
def update_canvas_file(payload: CanvasWritePayload) -> dict[str, Any]:
    if not payload.confirmed:
        raise HTTPException(409, "覆盖文件前需要明确确认。")
    if not payload.path.startswith("sandbox://"):
        raise HTTPException(403, "Canvas 只能编辑当前会话沙盒中的文件。")
    parts = payload.path[len("sandbox://"):].split("/", 2)
    if len(parts) != 3:
        raise HTTPException(422, "Canvas 沙盒路径无效。")
    user_id, conversation_id, _ = parts
    with SessionLocal() as session:
        user = ensure_local_user(session)
        conversation = session.get(Conversation, conversation_id)
        if user.id != user_id or conversation is None or conversation.user_id != user.id:
            raise HTTPException(404, "会话不存在。")
    target = _canvas_path(payload.path)
    editable = {".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".py", ".js", ".ts", ".tsx", ".css", ".html", ".yaml", ".yml"}
    if target.suffix.lower() not in editable:
        raise HTTPException(415, "该文件类型不支持在线编辑。")
    _atomic_text_write(target, payload.content)
    base = _sandbox_dir(user_id, conversation_id)
    item = _sandbox_canvas_item(base, target)
    _audit("sandbox.file_edited", {"path": target.relative_to(base).as_posix(), "bytes": target.stat().st_size, "user_id": user_id, "conversation_id": conversation_id})
    return {"status": "saved", "canvas": item}


@app.get("/api/conversations/{conversation_id}/sandbox/files")
def conversation_sandbox_files(conversation_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        user = ensure_local_user(session)
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(404, "会话不存在。")
        base = _sandbox_dir(conversation.user_id, conversation.id)

    files: list[dict[str, Any]] = []
    for section in ("output", "workspace", "input"):
        section_root = base / section
        for target in section_root.rglob("*"):
            if not target.is_file() or target.is_symlink():
                continue
            item = _sandbox_canvas_item(base, target)
            item["modified_at"] = datetime.fromtimestamp(target.stat().st_mtime, UTC).isoformat()
            files.append(item)
    files.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"conversation_id": conversation_id, "count": len(files), "files": files[:200]}


@app.post("/api/actions/confirm")
def confirm_action(payload: ConfirmActionPayload) -> dict[str, Any]:
    if not payload.confirmed:
        return {"status": "cancelled", "action_id": payload.action_id}
    with LOCK:
        pending = _read_object(PENDING_FILE, {})
        action = pending.get(payload.action_id)
    if not isinstance(action, dict):
        raise HTTPException(404, "待确认操作不存在或已经处理。")
    try:
        result = execute_confirmed_action(action)
    except Exception as exc:
        raise HTTPException(500, f"操作执行失败：{exc}") from exc
    with LOCK:
        pending = _read_object(PENDING_FILE, {})
        pending.pop(payload.action_id, None)
        _write_object(PENDING_FILE, pending)
    return {"status": "completed", **result}


def _safe_sample_id(value: str) -> str:
    if not SAMPLE_ID.fullmatch(value):
        raise HTTPException(422, "样本 ID 格式不合法。")
    return value


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def _runner_states() -> dict[str, str]:
    states: dict[str, str] = {}
    if not RUNNER_STATUS.is_file():
        return states
    try:
        rows = RUNNER_STATUS.read_text(encoding="utf-8", errors="replace").splitlines()
        header = rows[0].split("\t") if rows else []
        sid_index = next((i for i, name in enumerate(header) if name.lower() in {"sample_id", "sample", "id"}), 0)
        state_index = next((i for i, name in enumerate(header) if name.lower() in {"status", "state"}), None)
        for row in rows[1:]:
            fields = row.split("\t")
            if sid_index < len(fields) and SAMPLE_ID.fullmatch(fields[sid_index]):
                states[fields[sid_index]] = fields[state_index] if state_index is not None and state_index < len(fields) else "known"
    except OSError:
        return {}
    return states


def _fmt_plot_path(sample_id: str) -> Path:
    """Resolve both historical and report-builder FMT plot locations."""
    direct = RESULTS_DIR / f"{sample_id}_fmt_tsne.png"
    nested = RESULTS_DIR / "figures" / f"{sample_id}_fmt_tsne.png"
    return direct if direct.is_file() or not nested.is_file() else nested


def _sample_artifacts(sample_id: str) -> dict[str, dict[str, Any]]:
    paths = {
        "analysis": RESULTS_DIR / f"{sample_id}_analysis.json",
        "knowledge": RESULTS_DIR / f"{sample_id}_knowledge.json",
        "markdown": RESULTS_DIR / f"{sample_id}_health_report.md",
        "pdf": RESULTS_DIR / f"{sample_id}_health_report.pdf",
        "fmt_plot": _fmt_plot_path(sample_id),
        "evidence": RESULTS_DIR / f"{sample_id}_report_evidence.json",
    }
    return {
        name: {
            "exists": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else 0,
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat() if path.is_file() else None,
        }
        for name, path in paths.items()
    }


def _sample_summary(sample_id: str, runner_state: str = "") -> dict[str, Any]:
    analysis_path = RESULTS_DIR / f"{sample_id}_analysis.json"
    analysis = _json_object(analysis_path)
    species = analysis.get("species") if isinstance(analysis.get("species"), dict) else {}
    enterotype = analysis.get("enterotype") if isinstance(analysis.get("enterotype"), dict) else {}
    pathways = analysis.get("pathways") if isinstance(analysis.get("pathways"), dict) else {}
    reports = _sample_artifacts(sample_id)
    state = runner_state or ("analyzed" if reports["analysis"]["exists"] else "known")
    return {
        "sample_id": sample_id,
        "status": state,
        "updated_at": reports["analysis"]["updated_at"] or reports["pdf"]["updated_at"],
        "species_total": species.get("n_total", 0),
        "species_high": species.get("n_high", 0),
        "species_low": species.get("n_low", 0),
        "enterotype": enterotype.get("enterotype", "未分析"),
        "pathway_total": pathways.get("n_total_pathways", 0),
        "artifacts": reports,
    }


@app.get("/api/samples")
def samples(q: str = "", limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
    states = _runner_states()
    sample_ids = set(states)
    if RESULTS_DIR.is_dir():
        suffixes = ("_analysis.json", "_knowledge.json", "_health_report.md", "_health_report.pdf", "_fmt_tsne.png")
        for path in RESULTS_DIR.iterdir():
            for suffix in suffixes:
                if path.name.endswith(suffix):
                    sample_ids.add(path.name[:-len(suffix)])
                    break
    needle = q.strip().lower()
    ordered = sorted(sid for sid in sample_ids if not needle or needle in sid.lower())[:limit]
    items = [_sample_summary(sid, states.get(sid, "")) for sid in ordered]
    counts: dict[str, int] = {}
    for item in items:
        state = str(item["status"]).lower()
        key = "complete" if state in {"complete", "completed", "done", "success", "analyzed", "has_results"} else state
        counts[key] = counts.get(key, 0) + 1
    return {"count": len(sample_ids), "filtered_count": len(items), "status_counts": counts, "samples": items}


@app.post("/api/samples/upload", status_code=202)
def upload_sample(
    sample_id: str = Form(...),
    layout: str = Form(default="paired"),
    read1: UploadFile = File(...),
    read2: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    """Store FASTQ files and launch the existing resumable analysis worker."""
    try:
        return submit_uploaded_sample(
            sample_id=sample_id,
            layout=layout,
            read1=read1.file,
            read1_name=read1.filename or "",
            read2=read2.file if read2 is not None else None,
            read2_name=read2.filename if read2 is not None else None,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        read1.file.close()
        if read2 is not None:
            read2.file.close()


@app.get("/api/samples/{sample_id}/workflow")
def sample_workflow(sample_id: str) -> dict[str, Any]:
    try:
        return get_workflow_status(sample_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/samples/{sample_id}")
def sample_detail(sample_id: str) -> dict[str, Any]:
    sample_id = _safe_sample_id(sample_id)
    analysis_path = RESULTS_DIR / f"{sample_id}_analysis.json"
    if not analysis_path.is_file():
        raise HTTPException(404, "该样本尚无结构化分析结果。")
    analysis = _json_object(analysis_path)
    return {"summary": _sample_summary(sample_id, _runner_states().get(sample_id, "")), "analysis": analysis}


@app.get("/api/samples/{sample_id}/plot")
def sample_plot(sample_id: str) -> FileResponse:
    sample_id = _safe_sample_id(sample_id)
    path = _fmt_plot_path(sample_id)
    if not path.is_file():
        raise HTTPException(404, "该样本暂无 FMT 投影图。")
    return FileResponse(path, media_type="image/png", filename=path.name)


def _report_rows() -> list[dict[str, Any]]:
    sample_ids: set[str] = set()
    if RESULTS_DIR.is_dir():
        for path in RESULTS_DIR.iterdir():
            for suffix in ("_analysis.json", "_knowledge.json", "_health_report.md", "_health_report.pdf"):
                if path.name.endswith(suffix):
                    sample_ids.add(path.name[:-len(suffix)])
                    break
    rows = []
    for sample_id in sample_ids:
        artifacts = _sample_artifacts(sample_id)
        latest = max((item["updated_at"] or "" for item in artifacts.values()), default="") or None
        rows.append({"sample_id": sample_id, "updated_at": latest, "artifacts": artifacts})
    return sorted(rows, key=lambda item: item["updated_at"] or "", reverse=True)


@app.get("/api/reports")
def reports(response: Response, q: str = "") -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    needle = q.strip().lower()
    rows = [item for item in _report_rows() if not needle or needle in item["sample_id"].lower()]
    return {
        "count": len(rows),
        "pdf_count": sum(1 for item in rows if item["artifacts"]["pdf"]["exists"]),
        "markdown_count": sum(1 for item in rows if item["artifacts"]["markdown"]["exists"]),
        "reports": rows,
    }


@app.get("/api/reports/{sample_id}/{kind}")
def report_file(sample_id: str, kind: str) -> FileResponse:
    sample_id = _safe_sample_id(sample_id)
    mapping = {
        "pdf": (RESULTS_DIR / f"{sample_id}_health_report.pdf", "application/pdf"),
        "markdown": (RESULTS_DIR / f"{sample_id}_health_report.md", "text/markdown; charset=utf-8"),
        "analysis": (RESULTS_DIR / f"{sample_id}_analysis.json", "application/json"),
        "knowledge": (RESULTS_DIR / f"{sample_id}_knowledge.json", "application/json"),
        "evidence": (RESULTS_DIR / f"{sample_id}_report_evidence.json", "application/json"),
    }
    if kind not in mapping:
        raise HTTPException(404, "不支持的报告产物类型。")
    path, media_type = mapping[kind]
    if not path.is_file():
        raise HTTPException(404, "报告产物不存在。")
    return FileResponse(path, media_type=media_type, filename=path.name, headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/reports/{sample_id}/figures/{filename}")
def report_figure(sample_id: str, filename: str) -> FileResponse:
    sample_id = _safe_sample_id(sample_id)
    # A fixed per-sample prefix and basename prohibit traversal/cross-sample reads.
    if not re.fullmatch(re.escape(sample_id) + r"_[A-Za-z0-9_-]+\.png", filename):
        raise HTTPException(404, "不支持的图表文件名。")
    root = RESULTS_DIR.resolve()
    for path in (RESULTS_DIR / "figures" / filename, RESULTS_DIR / filename):
        if path.is_file() and path.resolve().is_relative_to(root):
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store, max-age=0"})
    raise HTTPException(404, "图表不存在。")


@app.post("/api/reports/{sample_id}/generate")
def generate_report(sample_id: str, payload: ReportGeneratePayload) -> dict[str, Any]:
    sample_id = _safe_sample_id(sample_id)
    if not payload.confirmed:
        raise HTTPException(409, "重新生成会写入报告文件，需要明确确认。")
    try:
        result = execute_confirmed_action({
            "id": uuid.uuid4().hex,
            "kind": "generate_report",
            "params": {"sample_id": sample_id},
        })
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if result.get("is_error"):
        raise HTTPException(502, str(result.get("content", "报告生成失败。")))
    return {"status": "complete", "sample_id": sample_id, "artifacts": _sample_artifacts(sample_id)}


def _kb_connect() -> sqlite3.Connection:
    if not KNOWLEDGE_DB.is_file():
        raise HTTPException(503, "知识库文件尚未就绪。")
    connection = sqlite3.connect(str(KNOWLEDGE_DB))
    connection.row_factory = sqlite3.Row
    return connection


@app.get("/api/knowledge/stats")
def knowledge_stats() -> dict[str, Any]:
    with _kb_connect() as connection:
        def count(table: str, expression: str = "*") -> int:
            return int(connection.execute(f"SELECT COUNT({expression}) FROM {table}").fetchone()[0])
        year_range = connection.execute("SELECT MIN(publication_year), MAX(publication_year) FROM papers").fetchone()
        diseases = [dict(row) for row in connection.execute(
            "SELECT target_disease_name AS name, COUNT(*) AS count FROM papers "
            "WHERE target_disease_name IS NOT NULL GROUP BY target_disease_name ORDER BY count DESC LIMIT 8"
        ).fetchall()]
        return {
            "papers": count("papers"),
            "full_text": int(connection.execute("SELECT COUNT(*) FROM papers WHERE full_text_available = 1").fetchone()[0]),
            "pathways": count("functional_pathways", "DISTINCT pathway_name"),
            "metabolites": count("metabolites", "DISTINCT metabolite_name"),
            "microbes": count("key_microbes", "DISTINCT scientific_name"),
            "year_min": year_range[0], "year_max": year_range[1], "diseases": diseases,
        }


@app.get("/api/knowledge/papers")
def knowledge_papers(
    q: str = "", year_from: int | None = None, year_to: int | None = None,
    disease: str = "", full_text: bool | None = None,
    limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    where: list[str] = ["1=1"]
    params: list[Any] = []
    if q.strip():
        where.append("(title LIKE ? OR abstract LIKE ? OR journal_name LIKE ? OR pmid LIKE ?)")
        term = f"%{q.strip()}%"; params.extend([term, term, term, term])
    if year_from is not None: where.append("publication_year >= ?"); params.append(year_from)
    if year_to is not None: where.append("publication_year <= ?"); params.append(year_to)
    if disease.strip(): where.append("target_disease_name LIKE ?"); params.append(f"%{disease.strip()}%")
    if full_text is not None: where.append("full_text_available = ?"); params.append(1 if full_text else 0)
    clause = " AND ".join(where)
    with _kb_connect() as connection:
        total = int(connection.execute(f"SELECT COUNT(*) FROM papers WHERE {clause}", params).fetchone()[0])
        rows = connection.execute(
            f"SELECT id, pmid, doi, title, abstract, journal_name, impact_factor, publication_year, "
            f"sequencing_strategy, sequencing_platform, sample_source, target_disease_code, "
            f"target_disease_name, pmc_id, full_text_available FROM papers WHERE {clause} "
            "ORDER BY publication_year DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return {"count": total, "papers": [dict(row) for row in rows]}


@app.get("/api/knowledge/papers/{pmid}")
def knowledge_paper(pmid: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", pmid):
        raise HTTPException(422, "PMID 格式不合法。")
    with _kb_connect() as connection:
        paper = connection.execute("SELECT * FROM papers WHERE pmid = ?", (pmid,)).fetchone()
        if paper is None: raise HTTPException(404, "未找到该文献。")
        result = dict(paper); paper_id = result["id"]
        for key, table in {
            "accessions": "accessions", "microbes": "key_microbes", "pathways": "functional_pathways",
            "metabolites": "metabolites", "treatments": "treatments", "drug_interactions": "drug_microbe_interactions",
        }.items():
            result[key] = [dict(row) for row in connection.execute(f"SELECT * FROM {table} WHERE paper_id = ?", (paper_id,)).fetchall()]
    return result


@app.post("/api/knowledge/papers/{pmid}/bind")
def bind_paper_to_sample(pmid: str, payload: EvidenceBindPayload) -> dict[str, Any]:
    sample_id = _safe_sample_id(payload.sample_id)
    paper = knowledge_paper(pmid)
    claim = {
        "claim_id": f"PMID:{paper['pmid']}", "document_id": paper["id"], "filename": paper.get("title", ""),
        "subject": paper.get("target_disease_name") or "肠道微生物组", "predicate": "参考证据",
        "object": paper.get("title", ""), "evidence_text": paper.get("abstract", ""),
        "confidence": 1.0, "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/",
        "knowledge_version": "sqlite-current",
    }
    knowledge_path = RESULTS_DIR / f"{sample_id}_knowledge.json"
    knowledge = _json_object(knowledge_path) or {"matched_docs": [], "pubmed_results": []}
    matched = [item for item in knowledge.get("matched_docs", []) if isinstance(item, dict)]
    by_id = {str(item.get("claim_id")): item for item in matched if item.get("claim_id")}
    existed = claim["claim_id"] in by_id; by_id[claim["claim_id"]] = claim
    knowledge["matched_docs"] = list(by_id.values()); knowledge["knowledge_version"] = "sqlite-current"
    _atomic_json(knowledge_path, knowledge)
    analysis_path = RESULTS_DIR / f"{sample_id}_analysis.json"
    if analysis_path.is_file():
        analysis = _json_object(analysis_path); analysis["knowledge"] = knowledge; _atomic_json(analysis_path, analysis)
    return {"bound": True, "created": not existed, "sample_id": sample_id, "claim": claim}


async def _litkg_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    headers = {"Accept": "application/json"}
    if settings.claim_api_token:
        headers["Authorization"] = f"Bearer {settings.claim_api_token}"
    try:
        async with httpx.AsyncClient(
            base_url=settings.claim_api_url.rstrip("/"),
            headers=headers,
            timeout=max(10.0, settings.claim_api_timeout),
        ) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"LitKG 接口暂不可用：{exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, "LitKG 接口返回了无法识别的数据格式。")
    return payload


async def _litkg_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    headers = {"Accept": "application/json"}
    if settings.claim_api_token:
        headers["Authorization"] = f"Bearer {settings.claim_api_token}"
    try:
        async with httpx.AsyncClient(
            base_url=settings.claim_api_url.rstrip("/"),
            headers=headers,
            timeout=max(90.0, settings.claim_api_timeout),
        ) as client:
            response = await client.post(path, json=body)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"LitKG 接口暂不可用：{exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, "LitKG 接口返回了无法识别的数据格式。")
    return payload


async def _litkg_selection(requested_ids: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    settings = get_settings()
    payload = await _litkg_get("/knowledge-bases")
    try:
        available = normalize_knowledge_bases(payload)
    except ValueError as exc:
        raise HTTPException(502, f"LitKG 知识库目录格式错误：{exc}") from exc
    selected = select_knowledge_bases(
        available,
        requested_ids=requested_ids,
        configured_ids=settings.claim_api_knowledge_base_ids,
    )
    requested = parse_knowledge_base_ids(requested_ids)
    if requested and not selected:
        raise HTTPException(404, "所选 LitKG 知识库不存在或已经被删除。")
    return available, selected


def _litkg_source(selected: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_settings()
    ids = [int(item["id"]) for item in selected]
    names = [str(item.get("name") or f"Knowledge Base {item['id']}") for item in selected]
    return {
        "kind": "litkg-rest-api",
        "label": f"LitKG · {names[0]}" if len(names) == 1 else f"LitKG · {len(names)} 个知识库",
        "knowledge_base_id": ids[0] if len(ids) == 1 else None,
        "knowledge_base_ids": ids,
        "knowledge_base_names": names,
        "endpoint": settings.claim_api_url.rstrip("/"),
    }


@app.get("/api/knowledge/remote/knowledge-bases")
async def litkg_knowledge_bases(
    knowledge_base_ids: str = Query(default="", max_length=1000),
) -> dict[str, Any]:
    available, selected = await _litkg_selection(knowledge_base_ids)
    selected_ids = {int(item["id"]) for item in selected}
    return {
        "knowledge_bases": [{**item, "selected": int(item["id"]) in selected_ids} for item in available],
        "selected_knowledge_base_ids": sorted(selected_ids),
        "source": _litkg_source(selected),
    }


@app.get("/api/knowledge/remote/status")
async def litkg_status(
    knowledge_base_ids: str = Query(default="", max_length=1000),
) -> dict[str, Any]:
    try:
        available, selected = await _litkg_selection(knowledge_base_ids)
        all_documents: list[dict[str, Any]] = []
        all_batches: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for knowledge_base in selected:
            kb = int(knowledge_base["id"])
            try:
                documents = await _litkg_get(f"/knowledge-bases/{kb}/documents", {"limit": 500, "offset": 0})
                batches = await _litkg_get(f"/knowledge-bases/{kb}/batches", {"limit": 50})
                all_documents.extend(
                    {**item, "knowledge_base_id": kb, "knowledge_base_name": knowledge_base["name"]}
                    for item in documents.get("documents", []) if isinstance(item, dict)
                )
                all_batches.extend(
                    {**item, "knowledge_base_id": kb, "knowledge_base_name": knowledge_base["name"]}
                    for item in batches.get("batches", []) if isinstance(item, dict)
                )
            except HTTPException as exc:
                errors.append({"knowledge_base_id": kb, "message": str(exc.detail)})
        all_batches.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        selected_ids = {int(item["id"]) for item in selected}
        return {
            "available": bool(selected) and len(errors) < len(selected),
            "source": _litkg_source(selected),
            "knowledge_bases": [{**item, "selected": int(item["id"]) in selected_ids} for item in available],
            "selected_knowledge_base_ids": sorted(selected_ids),
            "document_count": len(all_documents),
            "claim_count": sum(int(item.get("claim_count") or 0) for item in selected),
            "relation_count": sum(int(item.get("relation_count") or 0) for item in selected),
            "ready_count": sum(1 for item in all_documents if item.get("status") == "done"),
            "batch_count": len(all_batches),
            "latest_batch": all_batches[0] if all_batches else None,
            "errors": errors,
            "message": "未发现可用知识库。" if not selected else None,
        }
    except HTTPException as exc:
        return {
            "available": False,
            "source": _litkg_source([]),
            "knowledge_bases": [], "selected_knowledge_base_ids": [],
            "document_count": 0, "claim_count": 0, "ready_count": 0, "batch_count": 0,
            "message": str(exc.detail),
        }


@app.get("/api/knowledge/remote/documents")
async def litkg_documents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    knowledge_base_ids: str = Query(default="", max_length=1000),
) -> dict[str, Any]:
    _, selected = await _litkg_selection(knowledge_base_ids)
    documents: list[dict[str, Any]] = []
    for knowledge_base in selected:
        kb = int(knowledge_base["id"])
        payload = await _litkg_get(f"/knowledge-bases/{kb}/documents", {"limit": limit, "offset": offset})
        documents.extend(
            {**item, "knowledge_base_id": kb, "knowledge_base_name": knowledge_base["name"]}
            for item in payload.get("documents", []) if isinstance(item, dict)
        )
    return {
        "knowledge_base_ids": [int(item["id"]) for item in selected],
        "documents": documents,
        "source": _litkg_source(selected),
    }


@app.get("/api/knowledge/remote/claims")
async def litkg_claims(
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=30, ge=1, le=100),
    knowledge_base_ids: str = Query(default="", max_length=1000),
) -> dict[str, Any]:
    settings = get_settings()
    _, selected = await _litkg_selection(knowledge_base_ids)
    scan_limit = min(1000, max(limit * 10, 200))
    terms = [term.casefold() for term in q.split() if term]
    ranked: list[tuple[int, float, dict[str, Any]]] = []
    for knowledge_base in selected:
        kb = int(knowledge_base["id"])
        payload = await _litkg_get(f"/knowledge-bases/{kb}/claims", {"limit": scan_limit, "offset": 0})
        raw = payload.get("claims", []) if isinstance(payload.get("claims"), list) else []
        for item in raw:
            if not isinstance(item, dict):
                continue
            haystack = " ".join(str(item.get(key, "")) for key in (
                "subject_text", "subject_type", "predicate", "object_text", "object_type",
                "evidence_text", "section_title", "filename",
            )).casefold()
            score = sum(term in haystack for term in terms) if terms else 1
            if score:
                reference = claim_record_to_reference(
                    item,
                    base_url=settings.claim_api_url,
                    knowledge_base_id=kb,
                    query=q,
                    retrieval_score=score,
                )
                reference["knowledge_base_name"] = knowledge_base["name"]
                ranked.append((score, float(item.get("confidence") or 0), reference))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    results = [item for _, _, item in ranked[:limit]]
    return {"count": len(results), "claims": results, "source": _litkg_source(selected)}


@app.post("/api/knowledge/remote/ask")
async def litkg_ask(payload: LitKGAskPayload) -> dict[str, Any]:
    requested_ids = ",".join(str(item) for item in payload.knowledge_base_ids)
    _, selected = await _litkg_selection(requested_ids)
    answers: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    warnings: list[str] = []
    for knowledge_base in selected:
        kb = int(knowledge_base["id"])
        try:
            result = await _litkg_post(
                f"/knowledge-bases/{kb}/ask",
                {
                    "question": payload.question.strip(),
                    "limit": payload.limit,
                    "hops": payload.hops,
                    "generate": payload.generate,
                },
            )
        except HTTPException as exc:
            warnings.append(f"KB {kb} ({knowledge_base['name']}): {exc.detail}")
            continue
        answer = {
            **result,
            "knowledge_base_id": kb,
            "knowledge_base_name": knowledge_base["name"],
        }
        answers.append(answer)
        citations.extend(
            {**item, "knowledge_base_id": kb, "knowledge_base_name": knowledge_base["name"]}
            for item in result.get("citations", []) if isinstance(item, dict)
        )
        facts.extend(
            {**item, "knowledge_base_id": kb, "knowledge_base_name": knowledge_base["name"]}
            for item in result.get("facts", []) if isinstance(item, dict)
        )
        warnings.extend(str(item) for item in result.get("warnings", []) if item)
    if not answers:
        raise HTTPException(502, "所选知识库均未能完成证据问答。" + (f" {'; '.join(warnings)}" if warnings else ""))
    if len(answers) == 1:
        combined_answer = str(answers[0].get("answer") or "")
    else:
        combined_answer = "\n\n".join(
            f"## {item['knowledge_base_name']}（KB {item['knowledge_base_id']}）\n\n{item.get('answer') or '未生成答案。'}"
            for item in answers
        )
    return {
        "status": "answered" if any(item.get("status") == "answered" for item in answers) else "evidence_only",
        "answer": combined_answer,
        "answers": answers,
        "citations": citations,
        "facts": facts,
        "warnings": list(dict.fromkeys(warnings)),
        "source": _litkg_source(selected),
    }


@app.post("/api/knowledge/remote/claims/{claim_id}/bind")
async def bind_litkg_claim(
    claim_id: int,
    payload: EvidenceBindPayload,
    knowledge_base_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    sample_id = _safe_sample_id(payload.sample_id)
    settings = get_settings()
    _, selected = await _litkg_selection(str(knowledge_base_id or ""))
    raw: dict[str, Any] | None = None
    matched_base: dict[str, Any] | None = None
    for knowledge_base in selected:
        kb = int(knowledge_base["id"])
        result = await _litkg_get(f"/knowledge-bases/{kb}/claims", {"limit": 1000, "offset": 0})
        claims = result.get("claims", []) if isinstance(result.get("claims"), list) else []
        raw = next((item for item in claims if isinstance(item, dict) and int(item.get("id") or -1) == claim_id), None)
        if raw is not None:
            matched_base = knowledge_base
            break
    if raw is None:
        raise HTTPException(404, "接口知识库中未找到该 Claim。")
    kb = int(matched_base["id"])
    claim = claim_record_to_reference(
        raw,
        base_url=settings.claim_api_url,
        knowledge_base_id=kb,
    )
    claim["knowledge_base_name"] = matched_base["name"]
    knowledge_path = RESULTS_DIR / f"{sample_id}_knowledge.json"
    knowledge = _json_object(knowledge_path) or {"matched_docs": [], "pubmed_results": []}
    matched = [item for item in knowledge.get("matched_docs", []) if isinstance(item, dict)]
    by_id = {str(item.get("claim_id")): item for item in matched if item.get("claim_id")}
    existed = str(claim["claim_id"]) in by_id; by_id[str(claim["claim_id"])] = claim
    knowledge["matched_docs"] = list(by_id.values()); knowledge["knowledge_version"] = claim["knowledge_version"]
    _atomic_json(knowledge_path, knowledge)
    analysis_path = RESULTS_DIR / f"{sample_id}_analysis.json"
    if analysis_path.is_file():
        analysis = _json_object(analysis_path); analysis["knowledge"] = knowledge; _atomic_json(analysis_path, analysis)
    return {"bound": True, "created": not existed, "sample_id": sample_id, "claim": claim}


@app.get("/api/knowledge/remote/graph")
async def litkg_graph(
    limit: int = Query(default=90, ge=1, le=250),
    document_id: int | None = Query(default=None, ge=1),
    entity_type: str = Query(default="", max_length=80),
    predicate: str = Query(default="", max_length=120),
    min_document_count: int = Query(default=1, ge=1, le=100),
    include_negated: bool = False,
    include_speculative: bool = True,
    q: str = Query(default="", max_length=200),
    knowledge_base_ids: str = Query(default="", max_length=1000),
) -> dict[str, Any]:
    _, selected = await _litkg_selection(knowledge_base_ids)
    params: dict[str, Any] = {"limit": limit, "evidence_limit": 2}
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_id: dict[str, dict[str, Any]] = {}
    represented_document_count = 0
    if document_id is None:
        params.update({
            "min_document_count": min_document_count,
            "include_negated": include_negated,
            "include_speculative": include_speculative,
        })
        if entity_type.strip(): params["entity_type"] = entity_type.strip()
        if predicate.strip(): params["predicate"] = predicate.strip()
        if q.strip(): params["query"] = q.strip()
        targets = [(int(item["id"]), f"/knowledge-bases/{int(item['id'])}/graph") for item in selected]
    else:
        targets = [(int(selected[0]["id"]) if selected else 0, f"/documents/{document_id}/graph")]
    for kb, path in targets:
        payload = await _litkg_get(path, params)
        for node in payload.get("nodes", []) if isinstance(payload.get("nodes"), list) else []:
            if isinstance(node, dict): nodes_by_id[str(node.get("id"))] = node
        for edge in payload.get("edges", []) if isinstance(payload.get("edges"), list) else []:
            if not isinstance(edge, dict): continue
            edge_key = str(edge.get("id"))
            current = edges_by_id.get(edge_key)
            if current is None:
                edges_by_id[edge_key] = {**edge, "knowledge_base_ids": [kb]}
            elif kb not in current["knowledge_base_ids"]:
                current["knowledge_base_ids"].append(kb)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        represented_document_count += int(summary.get("represented_document_count") or 0)
    nodes = list(nodes_by_id.values())
    edges = list(edges_by_id.values())
    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {"node_count": len(nodes), "relation_count": len(edges), "represented_document_count": represented_document_count or (1 if document_id else 0)},
        "knowledge_base_id": int(selected[0]["id"]) if len(selected) == 1 else None,
        "knowledge_base_ids": [int(item["id"]) for item in selected],
        "document_id": document_id,
        "source": _litkg_source(selected),
    }
