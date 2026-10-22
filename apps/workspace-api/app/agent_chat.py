"""Controlled agent for the Next.js research workspace.

The language model may autonomously call read-only, domain-specific tools. Any
operation that starts computation or writes a report is converted into a
pending action and can only run after an explicit UI confirmation.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from wgs_agent.pipeline.upload_workflow import get_workflow_status, validate_sample_id
from wgs_agent.tools.domain_tools import (
    CompareReferenceTool,
    DiseaseAnalyzerTool,
    DrugAnalyzerTool,
    EnterotypeAnalyzerTool,
    LoadSpeciesDataTool,
    MetaboliteAnalyzerTool,
    PathwayAnalyzerTool,
    ReportGeneratorTool,
)
from wgs_agent.tools.knowledge_tools import KnowledgeSearchTool, PubmedSearchTool
from wgs_agent.tools.pipeline_runner import PipelineCheckTool, PipelineRunStepTool
from app.local_chat import LocalChatError, base_url as configured_base_url
from wgs_fmt_platform.paths import runner_status_path, runtime_path


MAX_AGENT_STEPS = 6
MAX_TOOL_OUTPUT = 18_000
_SAMPLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


SYSTEM_PROMPT = """你是 WGS-FMT-Agent 的受控科研智能体。你的职责是把用户问题转化为可核验的平台操作。

工作原则：
1. 需要平台数据时必须调用工具，不得声称读取了未调用工具的数据。
2. 先用一句简短的话说明计划，然后调用完成任务所需的最少工具。
3. 查询状态、读取结果、统计分析和知识检索可以自主执行。
4. 启动 Pipeline、生成或覆盖报告、覆盖或删除沙盒文件只能创建待确认动作；绝不能声称待确认动作已经执行。
5. 不编造样本、文件、数值或文献。工具失败时说明失败原因和可行的下一步。
6. 回答使用中文，清楚区分观测事实、文献证据和推断。
7. 涉及疾病、药物或 FMT 的内容仅供科研教育参考，不能替代临床诊疗。
8. 不提供或执行 Shell 命令，不尝试访问工具范围以外的路径。
9. 文献汇总、分析笔记等 Markdown 应使用 create_sandbox_markdown 保存；不要声称没有创建文件的能力。
10. 沙盒中新建文件可自主执行；覆盖、删除、导出或执行文件必须等待用户确认。
11. 需要向用户直观展示文件时，调用 open_in_canvas；只打开与任务直接相关的文件，并说明展示目的。
"""


def _function(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_SID = {"sample_id": {"type": "string", "description": "平台样本 ID"}}

TOOLS = [
    _function("list_samples", "列出平台已知样本及其状态摘要。", {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 30}}),
    _function("get_sample_status", "读取上传样本的实际 Pipeline 状态、进度和产物。", _SID, ["sample_id"]),
    _function("pipeline_check", "只读检查样本旧版 WGS Pipeline 各步骤产物缺口。", _SID, ["sample_id"]),
    _function("load_species_data", "读取 MetaPhlAn 物种丰度和统计摘要。", _SID, ["sample_id"]),
    _function("compare_reference", "将样本物种丰度与健康参考范围比较。", {**_SID, "species_name": {"type": "string", "description": "可选物种名"}}, ["sample_id"]),
    _function("analyze_enterotype", "分析样本肠型及判定依据。", _SID, ["sample_id"]),
    _function("analyze_pathways", "读取并分析 HUMAnN 代谢通路。", _SID, ["sample_id"]),
    _function("analyze_metabolites", "分析可用的代谢物数据或代谢潜能。", _SID, ["sample_id"]),
    _function("analyze_drugs", "只读分析药物与微生物组关联；结果不构成用药建议。", _SID, ["sample_id"]),
    _function("analyze_diseases", "只读分析疾病关联；结果不构成诊断。", _SID, ["sample_id"]),
    _function("search_knowledge_base", "搜索本地 LitKG/文献知识库。", {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8}}, ["query"]),
    _function("search_pubmed", "检索 PubMed 生物医学文献。", {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}, ["query"]),
    _function("get_report_status", "检查样本分析 JSON、知识 JSON、Markdown 和 PDF 报告是否存在。", _SID, ["sample_id"]),
    _function("list_sandbox_files", "列出当前会话沙盒中的文件。", {"directory": {"type": "string", "description": "相对于会话沙盒的目录，默认根目录"}}),
    _function("read_sandbox_file", "读取当前会话沙盒中的 UTF-8 文本文件。", {"path": {"type": "string", "description": "相对于会话沙盒的文件路径"}}, ["path"]),
    _function("create_sandbox_markdown", "在当前会话沙盒 output 目录中新建 Markdown；若目标已存在则创建待确认覆盖动作。", {"path": {"type": "string", "description": "相对于 output 的 .md 路径"}, "content": {"type": "string", "description": "完整 Markdown 内容"}, "title": {"type": "string", "description": "Canvas 展示标题"}}, ["path", "content"]),
    _function("request_delete_sandbox_file", "创建删除当前会话沙盒文件的待确认动作。", {"path": {"type": "string", "description": "相对于会话沙盒的文件路径"}}, ["path"]),
    _function("open_in_canvas", "在对话右侧 Canvas 中打开项目内文件供用户直观查看。支持文本、代码、JSON、CSV、图片和 PDF。", {"path": {"type": "string", "description": "相对于项目根目录的文件路径"}, "title": {"type": "string", "description": "Canvas 中显示的标题"}}, ["path"]),
    _function("request_pipeline_run", "创建执行指定 Pipeline 步骤的待确认动作，不直接运行。", {**_SID, "start_step": {"type": "integer", "minimum": 1, "maximum": 7}, "steps": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 7}, "maxItems": 7}}, ["sample_id", "start_step"]),
    _function("request_report_generation", "创建生成或覆盖样本报告的待确认动作，不直接写文件。", _SID, ["sample_id"]),
]


_READ_TOOLS = {
    "pipeline_check": PipelineCheckTool,
    "load_species_data": LoadSpeciesDataTool,
    "compare_reference": CompareReferenceTool,
    "analyze_enterotype": EnterotypeAnalyzerTool,
    "analyze_pathways": PathwayAnalyzerTool,
    "analyze_metabolites": MetaboliteAnalyzerTool,
    "analyze_drugs": DrugAnalyzerTool,
    "analyze_diseases": DiseaseAnalyzerTool,
    "search_knowledge_base": KnowledgeSearchTool,
    "search_pubmed": PubmedSearchTool,
}


def _results_dir() -> Path:
    return runtime_path("WGS_RESULTS_DIR", "results")


def _audit_path() -> Path:
    directory = runtime_path("WGS_AGENT_AUDIT_DIR", "agent-audit")
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"


def _audit(event: str, payload: dict[str, Any]) -> None:
    record = {"ts": datetime.now(UTC).isoformat(), "event": event, **payload}
    with _audit_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _sandbox_root() -> Path:
    root = runtime_path("WGS_AGENT_SANDBOX_ROOT", "sandboxes")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _safe_scope_id(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError(f"{label} 不合法。")
    return value


def _sandbox_dir(user_id: str, conversation_id: str) -> Path:
    base = _sandbox_root() / _safe_scope_id(user_id, "用户 ID") / _safe_scope_id(conversation_id, "会话 ID")
    for directory in (base, base / "input", base / "workspace", base / "output", base / "tmp"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
    return base.resolve()


def _sandbox_path(base: Path, value: str, *, output_only: bool = False) -> Path:
    if not value or "\x00" in value:
        raise ValueError("沙盒路径无效。")
    raw = Path(value)
    if raw.is_absolute():
        raise PermissionError("沙盒不允许绝对路径。")
    anchor = base / "output" if output_only else base
    candidate = (anchor / raw).resolve()
    try:
        candidate.relative_to(anchor.resolve())
    except ValueError as exc:
        raise PermissionError("路径越出会话沙盒。") from exc
    return candidate


def _sandbox_token(base: Path, path: Path) -> str:
    relative = path.resolve().relative_to(base.resolve()).as_posix()
    user_id, conversation_id = base.parts[-2:]
    return f"sandbox://{user_id}/{conversation_id}/{relative}"


def _sandbox_canvas_item(base: Path, path: Path, title: str = "") -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"沙盒文件不存在：{path.name}")
    suffix = path.suffix.lower()
    kind = "image" if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} else "pdf" if suffix == ".pdf" else "table" if suffix in {".csv", ".tsv"} else "json" if suffix in {".json", ".jsonl"} else "text"
    return {"id": uuid.uuid4().hex, "title": title.strip()[:120] or path.name, "path": _sandbox_token(base, path), "kind": kind, "bytes": path.stat().st_size}


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _list_sandbox(base: Path, directory: str = "") -> dict[str, Any]:
    target = _sandbox_path(base, directory or ".")
    if not target.is_dir():
        raise FileNotFoundError("沙盒目录不存在。")
    files = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and not path.is_symlink():
            files.append({"path": path.relative_to(base).as_posix(), "bytes": path.stat().st_size, "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()})
            if len(files) >= 200:
                break
    return {"sandbox": _sandbox_token(base, base / "workspace").split("/workspace", 1)[0], "count": len(files), "files": files}


def _read_sandbox(base: Path, value: str) -> dict[str, Any]:
    path = _sandbox_path(base, value)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("沙盒文件不存在或不可读取。")
    limit = int(os.environ.get("WGS_SANDBOX_READ_MAX_BYTES", str(512 * 1024)))
    if path.stat().st_size > limit:
        raise ValueError(f"文件超过读取上限（{limit // 1024} KB）。")
    return {"path": path.relative_to(base).as_posix(), "content": path.read_text(encoding="utf-8"), "bytes": path.stat().st_size}


def _sample_id(params: dict[str, Any]) -> str:
    from wgs_agent.pipeline.sample_registry import require_active

    value = validate_sample_id(str(params.get("sample_id", "")))
    if not _SAMPLE_RE.fullmatch(value):
        raise ValueError("样本 ID 不合法。")
    require_active(value)
    return value


def _list_samples(limit: int = 30) -> dict[str, Any]:
    from wgs_agent.pipeline.sample_registry import is_deleted
    from wgs_agent.pipeline.upload_workflow import list_uploaded_workflows

    samples: dict[str, str] = {}
    results = _results_dir()
    if results.is_dir():
        for path in results.iterdir():
            for suffix in ("_analysis.json", "_knowledge.json", "_health_report.md", "_health_report.pdf"):
                if path.name.endswith(suffix):
                    samples.setdefault(path.name[: -len(suffix)], "has_results")
                    break

    status_file = runner_status_path()
    if status_file.is_file():
        try:
            lines = status_file.read_text(encoding="utf-8", errors="replace").splitlines()
            header = lines[0].split("\t") if lines else []
            sid_col = next((i for i, key in enumerate(header) if key.lower() in {"sample_id", "sample", "id"}), 0)
            state_col = next((i for i, key in enumerate(header) if key.lower() in {"status", "state"}), None)
            for line in lines[1:]:
                fields = line.split("\t")
                if sid_col < len(fields) and _SAMPLE_RE.fullmatch(fields[sid_col]):
                    state = fields[state_col] if state_col is not None and state_col < len(fields) else "known"
                    samples[fields[sid_col]] = state
        except OSError:
            pass
    samples.update({sid: workflow["state"] for sid, workflow in list_uploaded_workflows().items()})
    samples = {sid: state for sid, state in samples.items() if not is_deleted(sid)}
    ordered = [{"sample_id": sid, "status": state} for sid, state in sorted(samples.items())[: max(1, min(int(limit), 200))]]
    return {"count": len(samples), "samples": ordered}


def _report_status(sample_id: str) -> dict[str, Any]:
    root = _results_dir()
    files = {
        "analysis_json": root / f"{sample_id}_analysis.json",
        "knowledge_json": root / f"{sample_id}_knowledge.json",
        "markdown_report": root / f"{sample_id}_health_report.md",
        "pdf_report": root / f"{sample_id}_health_report.pdf",
    }
    return {
        "sample_id": sample_id,
        "artifacts": {name: {"exists": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0} for name, path in files.items()},
    }


def _canvas_item(path_value: str, title: str = "") -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    raw = Path(path_value)
    path = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Canvas 只能打开项目工作区内的文件。") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Canvas 文件不存在：{relative}")
    max_bytes = int(os.environ.get("WGS_CANVAS_MAX_BYTES", str(20 * 1024 * 1024)))
    if path.stat().st_size > max_bytes:
        raise ValueError(f"文件超过 Canvas 大小限制（{max_bytes // 1024 // 1024} MB）。")
    suffix = path.suffix.lower()
    kind = "image" if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} else "pdf" if suffix == ".pdf" else "table" if suffix in {".csv", ".tsv"} else "json" if suffix in {".json", ".jsonl"} else "text"
    return {"id": uuid.uuid4().hex, "title": title.strip()[:120] or path.name, "path": relative.as_posix(), "kind": kind, "bytes": path.stat().st_size}


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def _create_sandbox_markdown(base: Path, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    value = str(params.get("path", "")).strip()
    if not value.lower().endswith(".md"):
        raise ValueError("沙盒 Markdown 文件必须使用 .md 扩展名。")
    content = str(params.get("content", ""))
    limit = int(os.environ.get("WGS_SANDBOX_WRITE_MAX_BYTES", str(512 * 1024)))
    if len(content.encode("utf-8")) > limit:
        raise ValueError(f"Markdown 内容超过写入上限（{limit // 1024} KB）。")
    target = _sandbox_path(base, value, output_only=True)
    title = str(params.get("title", ""))[:120]
    if target.exists():
        action_id = uuid.uuid4().hex
        draft = _sandbox_path(base, f"tmp/pending-{action_id}.md")
        _atomic_text_write(draft, content)
        action = {"id": action_id, "kind": "overwrite_sandbox_markdown", "label": f"覆盖沙盒文件 output/{value}", "params": {"user_id": base.parts[-2], "conversation_id": base.parts[-1], "path": f"output/{value}", "draft_path": draft.relative_to(base).as_posix(), "title": title}, "risk": "将覆盖当前会话沙盒中的已有 Markdown 文件；原内容可能无法恢复。"}
        _audit("action.requested", {"action": {**action, "params": {**action["params"], "draft_path": "[sandbox draft]"}}})
        return {"status": "awaiting_confirmation", "action": action}, action
    _atomic_text_write(target, content)
    item = _sandbox_canvas_item(base, target, title)
    _audit("sandbox.file_created", {"path": target.relative_to(base).as_posix(), "bytes": target.stat().st_size, "user_id": base.parts[-2], "conversation_id": base.parts[-1]})
    return {"status": "created", "path": target.relative_to(base).as_posix(), "canvas": item}, None


def _pending(name: str, params: dict[str, Any], sandbox: Path | None = None) -> dict[str, Any]:
    if name == "request_delete_sandbox_file":
        if sandbox is None:
            raise PermissionError("当前工具没有会话沙盒上下文。")
        target = _sandbox_path(sandbox, str(params.get("path", "")))
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError("待删除的沙盒文件不存在。")
        action = {"id": uuid.uuid4().hex, "kind": "delete_sandbox_file", "label": f"删除沙盒文件 {target.relative_to(sandbox)}", "params": {"user_id": sandbox.parts[-2], "conversation_id": sandbox.parts[-1], "path": target.relative_to(sandbox).as_posix()}, "risk": "将永久删除当前会话沙盒中的文件。"}
        _audit("action.requested", {"action": action})
        return action
    sid = _sample_id(params)
    if name == "request_pipeline_run":
        start = int(params.get("start_step", 1))
        if not 1 <= start <= 7:
            raise ValueError("start_step 必须在 1 到 7 之间。")
        steps = [int(v) for v in params.get("steps", [])] or [start]
        if any(v < 1 or v > 7 for v in steps):
            raise ValueError("Pipeline 步骤必须在 1 到 7 之间。")
        action = {"id": uuid.uuid4().hex, "kind": "pipeline_run", "label": f"执行 {sid} 的 Pipeline 步骤 {steps}", "params": {"sample_id": sid, "start_step": start, "steps": steps}, "risk": "将启动计算任务，可能运行数小时。"}
    else:
        action = {"id": uuid.uuid4().hex, "kind": "generate_report", "label": f"生成或覆盖 {sid} 的健康分析报告", "params": {"sample_id": sid}, "risk": "将写入或覆盖该样本的报告文件。"}
    _audit("action.requested", {"action": action})
    return action


def _invoke_tool(
    name: str,
    params: dict[str, Any],
    pending_actions: list[dict[str, Any]],
    canvas_items: list[dict[str, Any]] | None = None,
    *,
    timeout_s: float = 120.0,
    sandbox_user_id: str = "",
    sandbox_conversation_id: str = "",
) -> str:
    if "sample_id" in params:
        params = {**params, "sample_id": _sample_id(params)}
    sandbox = _sandbox_dir(sandbox_user_id, sandbox_conversation_id) if sandbox_user_id and sandbox_conversation_id else None
    if name == "list_samples":
        result: Any = _list_samples(int(params.get("limit", 30)))
    elif name == "get_sample_status":
        result = get_workflow_status(params["sample_id"])
    elif name == "get_report_status":
        result = _report_status(params["sample_id"])
    elif name == "list_sandbox_files":
        if sandbox is None: raise PermissionError("当前会话没有沙盒上下文。")
        result = _list_sandbox(sandbox, str(params.get("directory", "")))
    elif name == "read_sandbox_file":
        if sandbox is None: raise PermissionError("当前会话没有沙盒上下文。")
        result = _read_sandbox(sandbox, str(params.get("path", "")))
    elif name == "create_sandbox_markdown":
        if sandbox is None: raise PermissionError("当前会话没有沙盒上下文。")
        result, action = _create_sandbox_markdown(sandbox, params)
        if action is not None:
            pending_actions.append(action)
        elif canvas_items is not None and result.get("canvas"):
            canvas_items.append(result["canvas"])
    elif name == "open_in_canvas":
        path_value = str(params.get("path", ""))
        if path_value.startswith("sandbox://"):
            if sandbox is None: raise PermissionError("当前会话没有沙盒上下文。")
            prefix = f"sandbox://{sandbox.parts[-2]}/{sandbox.parts[-1]}/"
            if not path_value.startswith(prefix): raise PermissionError("不能打开其他用户或会话的沙盒文件。")
            item = _sandbox_canvas_item(sandbox, _sandbox_path(sandbox, path_value[len(prefix):]), str(params.get("title", "")))
        else:
            item = _canvas_item(path_value, str(params.get("title", "")))
        if canvas_items is not None:
            canvas_items.append(item)
        result = {"status": "opened_in_canvas", "canvas": item}
    elif name in {"request_pipeline_run", "request_report_generation", "request_delete_sandbox_file"}:
        action = _pending(name, params, sandbox)
        pending_actions.append(action)
        result = {"status": "awaiting_confirmation", "action": action}
    elif name in _READ_TOOLS:
        tool_result = _run_async(
            asyncio.wait_for(_READ_TOOLS[name]().invoke(params), timeout=timeout_s)
        )
        result = {"is_error": tool_result.is_error, "content": tool_result.content}
    else:
        raise ValueError(f"未授权工具: {name}")
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text[:MAX_TOOL_OUTPUT] + ("\n[工具输出已截断]" if len(text) > MAX_TOOL_OUTPUT else "")


def _audit_params(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Keep generated file contents out of traces and audit logs."""
    if name != "create_sandbox_markdown" or "content" not in params:
        return params
    content = str(params.get("content", ""))
    return {**params, "content": f"[Markdown content: {len(content.encode('utf-8'))} bytes]"}


def run_agent_turn(
    *,
    model: str,
    history: list[dict[str, Any]],
    prompt: str,
    current_sample_id: str = "",
    allowed_tools: list[str] | None = None,
    extra_system_prompt: str = "",
    base_url: str = "",
    api_key: str = "",
    max_steps: int = MAX_AGENT_STEPS,
    max_tool_calls: int = 20,
    tool_timeout_s: float = 120.0,
    loop_repeat_limit: int = 2,
    allow_sensitive: bool = False,
    audit_enabled: bool = True,
    sandbox_user_id: str = "",
    sandbox_conversation_id: str = "",
) -> dict[str, Any]:
    """Run one bounded plan/tool/observe turn and return UI-ready trace data."""
    client = OpenAI(
        api_key=api_key or os.environ.get("WGS_LOCAL_LLM_API_KEY", "local-no-key-required"),
        base_url=base_url or configured_base_url(),
        timeout=180.0,
    )
    context = f"\n当前侧边栏样本 ID：{current_sample_id}" if current_sample_id else "\n当前未在侧边栏指定样本 ID。"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT + context + extra_system_prompt}
    ]
    allowed = set(allowed_tools) if allowed_tools is not None else None
    exposed_tools = [
        item for item in TOOLS
        if allowed is None or item["function"]["name"] in allowed
    ]
    if not allow_sensitive:
        exposed_tools = [
            item for item in exposed_tools
            if item["function"]["name"] not in {"analyze_drugs", "analyze_diseases"}
        ]
    for item in history[-12:]:
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            messages.append({"role": item["role"], "content": str(item["content"])})
    messages.append({"role": "user", "content": prompt})

    trace: list[dict[str, Any]] = []
    pending_actions: list[dict[str, Any]] = []
    canvas_items: list[dict[str, Any]] = []
    final_text = ""
    run_id = uuid.uuid4().hex
    tool_call_count = 0
    repeated_calls: dict[str, int] = {}
    trace.append({"type": "understanding", "step": 0, "content": prompt[:1000], "status": "completed"})
    if audit_enabled:
        _audit("turn.started", {"run_id": run_id, "model": model, "prompt": prompt[:1000]})
    try:
        for step in range(1, max_steps + 1):
            trace.append({"type": "status", "step": step, "content": "正在规划下一步", "status": "running"})
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=exposed_tools,
                tool_choice="auto",
                temperature=0.1,
            )
            message = response.choices[0].message
            content = message.content or ""
            calls = message.tool_calls or []
            if content:
                trace.append({"type": "plan" if calls else "answer", "step": step, "content": content, "status": "completed"})
            if not calls:
                final_text = content or "本轮操作已结束。"
                break
            messages.append(message.model_dump(exclude_none=True))
            for call in calls:
                name = call.function.name
                try:
                    tool_call_count += 1
                    if tool_call_count > max_tool_calls:
                        raise RuntimeError(f"已达到工具调用上限（{max_tool_calls} 次）。")
                    if allowed is not None and name not in allowed:
                        raise ValueError(f"当前 Agent 未启用工具: {name}")
                    params = json.loads(call.function.arguments or "{}")
                    if not isinstance(params, dict):
                        raise ValueError("工具参数必须是对象。")
                    signature = json.dumps([name, params], ensure_ascii=False, sort_keys=True, default=str)
                    repeated_calls[signature] = repeated_calls.get(signature, 0) + 1
                    if repeated_calls[signature] > loop_repeat_limit:
                        raise RuntimeError(f"检测到重复工具调用循环：{name}，已自动停止并要求重规划。")
                    safe_params = _audit_params(name, params)
                    trace.append({"type": "tool_started", "step": step, "name": name, "params": safe_params, "status": "running"})
                    output = _invoke_tool(name, params, pending_actions, canvas_items, timeout_s=tool_timeout_s, sandbox_user_id=sandbox_user_id, sandbox_conversation_id=sandbox_conversation_id)
                    trace.append({"type": "tool_finished", "step": step, "name": name, "content": output, "status": "completed"})
                    if audit_enabled:
                        _audit("tool.completed", {"run_id": run_id, "step": step, "tool": name, "params": safe_params})
                except TimeoutError:
                    output = json.dumps({"is_error": True, "error": f"工具执行超过 {tool_timeout_s} 秒"}, ensure_ascii=False)
                    trace.append({"type": "tool_failed", "step": step, "name": name, "content": f"工具执行超时（{tool_timeout_s} 秒）", "status": "failed"})
                except Exception as exc:
                    output = json.dumps({"is_error": True, "error": str(exc)}, ensure_ascii=False)
                    event_type = "replan" if "循环" in str(exc) else "tool_failed"
                    trace.append({"type": event_type, "step": step, "name": name, "content": str(exc), "status": "failed"})
                    if audit_enabled:
                        _audit("tool.failed", {"run_id": run_id, "step": step, "tool": name, "error": str(exc)})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
        else:
            final_text = f"已达到本轮最大执行步数（{max_steps}）。请缩小问题范围后继续。"
            trace.append({"type": "limit", "step": max_steps, "content": final_text, "status": "failed"})
    except Exception as exc:
        raise LocalChatError(f"本地智能体调用失败：{exc}") from exc

    result = {"answer": final_text, "trace": trace, "pending_actions": pending_actions, "canvas_items": canvas_items, "model": model, "run_id": run_id, "tool_call_count": tool_call_count}
    if audit_enabled:
        _audit("turn.completed", {"run_id": run_id, "model": model, "prompt": prompt[:1000], "tool_call_count": tool_call_count, "tool_names": [t.get("name") for t in trace if t.get("name")], "pending_action_ids": [a["id"] for a in pending_actions]})
    return result


def execute_confirmed_action(action: dict[str, Any]) -> dict[str, Any]:
    """Execute one server-created action after the user presses Confirm."""
    kind = str(action.get("kind", ""))
    params = dict(action.get("params") or {})
    if kind in {"overwrite_sandbox_markdown", "delete_sandbox_file"}:
        base = _sandbox_dir(str(params.get("user_id", "")), str(params.get("conversation_id", "")))
        target = _sandbox_path(base, str(params.get("path", "")))
        if kind == "overwrite_sandbox_markdown":
            draft = _sandbox_path(base, str(params.get("draft_path", "")))
            if not draft.is_file() or draft.is_symlink():
                raise FileNotFoundError("待确认的 Markdown 草稿不存在。")
            _atomic_text_write(target, draft.read_text(encoding="utf-8"))
            draft.unlink()
            canvas = _sandbox_canvas_item(base, target, str(params.get("title", "")))
            payload = {"action_id": action.get("id"), "kind": kind, "status": "overwritten", "path": target.relative_to(base).as_posix(), "canvas": canvas}
        else:
            if not target.is_file() or target.is_symlink():
                raise FileNotFoundError("待删除的沙盒文件不存在。")
            relative = target.relative_to(base).as_posix()
            target.unlink()
            payload = {"action_id": action.get("id"), "kind": kind, "status": "deleted", "path": relative}
        _audit("action.executed", payload)
        return payload
    sid = _sample_id(params)
    if kind == "pipeline_run":
        result = _run_async(PipelineRunStepTool().invoke(params))
    elif kind == "generate_report":
        from wgs_agent.pipeline.sample_registry import require_active, sample_lock

        with sample_lock(sid):
            require_active(sid)
            results = _results_dir()
            analysis = results / f"{sid}_analysis.json"
            knowledge = results / f"{sid}_knowledge.json"
            if not analysis.is_file():
                from wgs_agent.reporting.analysis import ensure_analysis_input

                workflow = get_workflow_status(sid, include_log=False)
                if workflow["state"] != "complete":
                    raise ValueError("尚无分析 JSON，且生信任务尚未完成，暂不能生成报告。")
                analysis = ensure_analysis_input(sid, results)
            result = _run_async(ReportGeneratorTool().invoke({"sample_id": sid, "analysis_json_path": str(analysis), "knowledge_json_path": str(knowledge) if knowledge.is_file() else ""}))
    else:
        raise ValueError("待确认动作类型无效或已过期。")
    payload = {"action_id": action.get("id"), "kind": kind, "sample_id": sid, "is_error": result.is_error, "content": result.content}
    _audit("action.executed", payload)
    return payload
