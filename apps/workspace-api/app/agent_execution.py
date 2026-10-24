"""Bounded main/subagent execution with protocol recovery and final synthesis."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from app.agent_prompts import (
    EVIDENCE_AGENT_ID, EVIDENCE_SYSTEM_PROMPT, EVIDENCE_TOOL_NAMES,
    MAIN_AGENT_ID, MAIN_SYSTEM_PROMPT, RUNTIME_PROMPT,
)
from app.local_chat import LocalChatError, base_url as configured_base_url
from app.model_protocol import ModelProtocolError, decode_message, visible_text


@dataclass
class RunBudget:
    limit: int
    deadline: float
    count: int = 0
    repeats: dict[str, int] = field(default_factory=dict)


def run_agent_turn(
    *, model: str, history: list[dict[str, Any]], prompt: str,
    current_sample_id: str = "", allowed_tools: list[str] | None = None,
    extra_system_prompt: str = "", base_url: str = "", api_key: str = "",
    max_steps: int = 6, max_tool_calls: int = 20, tool_timeout_s: float = 120,
    loop_repeat_limit: int = 2, allow_sensitive: bool = False, audit_enabled: bool = True,
    sandbox_user_id: str = "", sandbox_conversation_id: str = "",
    subagent_config: dict | None = None, agent_id: str = MAIN_AGENT_ID,
    system_prompt: str = "", _budget: RunBudget | None = None, _client: Any = None,
) -> dict[str, Any]:
    from app.agent_chat import TOOLS, _audit, _audit_params, _invoke_tool

    child = agent_id != MAIN_AGENT_ID
    run_id = uuid.uuid4().hex
    budget = _budget or RunBudget(max_tool_calls, time.monotonic() + 600)
    starting_count = budget.count
    local_tool_limit = min(4, max_tool_calls) if child else max_tool_calls
    client = _client or OpenAI(
        api_key=api_key or os.environ.get("WGS_LOCAL_LLM_API_KEY", "local-no-key-required"),
        base_url=base_url or configured_base_url(), timeout=180.0, max_retries=1,
    )
    allowed = set(allowed_tools) if allowed_tools is not None else {t["function"]["name"] for t in TOOLS}
    if child:
        allowed &= EVIDENCE_TOOL_NAMES
    elif subagent_config and subagent_config.get("enabled", True):
        allowed.add("delegate_evidence_review")
    else:
        allowed.discard("delegate_evidence_review")
    if not allow_sensitive:
        allowed -= {"analyze_drugs", "analyze_diseases"}
    exposed = [tool for tool in TOOLS if tool["function"]["name"] in allowed]
    role_prompt = system_prompt or (EVIDENCE_SYSTEM_PROMPT if child else MAIN_SYSTEM_PROMPT)
    context = (f"\n当前样本 ID：{current_sample_id}" if current_sample_id else "\n当前未指定样本 ID。")
    messages = [{"role": "system", "content": RUNTIME_PROMPT + role_prompt + context + extra_system_prompt}]
    for item in history[-12:]:
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            content = str(item["content"]) if item["role"] == "user" else visible_text(str(item["content"]))
            if content:
                messages.append({"role": item["role"], "content": content})
    messages.append({"role": "user", "content": prompt})
    trace, pending, canvas = [], [], []
    answer, completion_status = "", "completed"

    def event(kind: str, step: int, **data: Any) -> None:
        trace.append({"type": kind, "step": step, "agent_id": agent_id,
                      "status": "completed", **data})

    def complete(tools: list[dict], step: int) -> tuple[str, list[dict], bool]:
        """Length/format failures never masquerade as successful tool turns."""
        request_messages = list(messages)
        parts = []
        for attempt in range(3):
            if time.monotonic() >= budget.deadline:
                raise TimeoutError("本轮执行超过总时间预算")
            kwargs = dict(model=model, messages=request_messages, temperature=0.1, max_tokens=4096,
                          timeout=min(180, max(1, budget.deadline-time.monotonic())))
            if tools:
                kwargs.update(tools=tools, tool_choice="auto")
            if "qwen" in model.lower():
                kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            response = client.chat.completions.create(**kwargs)
            if not response.choices:
                raise ModelProtocolError("模型返回空 choices")
            choice = response.choices[0]
            if choice.finish_reason not in {"stop", "tool_calls", "length"}:
                raise ModelProtocolError(f"模型异常结束：{choice.finish_reason}")
            try:
                text, calls = decode_message(choice.message, tools)
                if choice.finish_reason == "tool_calls" and not calls:
                    raise ModelProtocolError("模型声明工具调用但未提供完整调用")
                if not calls and not text:
                    raise ModelProtocolError("模型未返回有效回答")
                if child and tools and not calls and not any(row["type"] == "tool_finished" for row in trace):
                    raise ModelProtocolError("循证整理必须先调用已提供的检索工具；尚未实际检索，不能提交证据结论")
                if choice.finish_reason == "length":
                    if calls or "<tool_call" in (choice.message.content or ""):
                        raise ModelProtocolError("工具调用因长度上限被截断，尚未执行")
                    parts.append(text)
                    event("continuation", step, content="回答达到长度上限，正在续答")
                    request_messages.extend([
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": "上条回答因长度上限中断。请接着未完成处完成结论，不重复已有内容，不调用工具。"},
                    ])
                    tools = []
                    continue
                return "\n\n".join(parts + ([text] if text else [])), calls, True
            except ModelProtocolError as exc:
                event("protocol_recovery", step, content=str(exc), status="running")
                if attempt == 2:
                    raise
                request_messages.append({"role": "user", "content": f"上次模型输出未通过接口校验：{exc}。不要输出思考。请通过可用工具重新提交完整调用，或基于已收到的结果给出完整回答。"})
        return "\n\n".join(parts) + "\n\n本次回答仍达到长度上限，以上为已完成部分；请继续获取剩余内容。", [], False

    event("understanding", 0, content=prompt[:1000])
    if audit_enabled:
        _audit("turn.started", {"run_id": run_id, "agent_id": agent_id, "model": model, "prompt": prompt[:1000]})
    try:
        for step in range(1, max_steps + 1):
            if budget.count >= budget.limit or budget.count-starting_count >= local_tool_limit:
                break
            event("status", step, content="正在整理证据" if child else "正在处理任务", status="running")
            text, calls, complete_answer = complete(exposed, step)
            if not calls:
                answer = text
                if not complete_answer:
                    completion_status = "partial"
                event("answer", step, content=answer)
                break
            if text:
                event("plan", step, content=text)
            messages.append({"role": "assistant", "content": text or None, "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                params = json.loads(call["function"]["arguments"])
                try:
                    if budget.count >= budget.limit:
                        raise RuntimeError(f"已达到共享工具调用上限（{budget.limit} 次）")
                    if budget.count-starting_count >= local_tool_limit:
                        raise RuntimeError(f"已达到子任务工具调用上限（{local_tool_limit} 次）")
                    budget.count += 1
                    signature = json.dumps([agent_id, name, params], ensure_ascii=False, sort_keys=True)
                    budget.repeats[signature] = budget.repeats.get(signature, 0) + 1
                    if budget.repeats[signature] > loop_repeat_limit:
                        raise RuntimeError(f"检测到重复工具调用循环：{name}")
                    if time.monotonic() >= budget.deadline:
                        raise TimeoutError("本轮执行超过总时间预算")
                    safe_params = _audit_params(name, params)
                    event("tool_started", step, name=name, params=safe_params, status="running")
                    if name == "delegate_evidence_review":
                        config = subagent_config or {}
                        event("subagent_started", step, name="循证整理助手", content=params["task"], status="running")
                        result = run_agent_turn(
                            model=config.get("model") or model, history=[], prompt=params["task"],
                            current_sample_id=current_sample_id, allowed_tools=config.get("allowed_tools", list(EVIDENCE_TOOL_NAMES)),
                            system_prompt=config.get("system_prompt") or EVIDENCE_SYSTEM_PROMPT,
                            extra_system_prompt=config.get("skill_context", ""),
                            base_url=base_url, api_key=api_key, max_steps=min(4, max_steps),
                            tool_timeout_s=tool_timeout_s, loop_repeat_limit=loop_repeat_limit,
                            audit_enabled=audit_enabled, agent_id=EVIDENCE_AGENT_ID,
                            _budget=budget, _client=client,
                        )
                        trace.extend(result["trace"])
                        output = json.dumps({"agent_id": EVIDENCE_AGENT_ID, "answer": result["answer"],
                                             "completion_status": result["completion_status"],
                                             "retrieval_count": result["tool_call_count"]}, ensure_ascii=False)
                        event("subagent_finished", step, name="循证整理助手", content=result["completion_status"])
                    else:
                        output = _invoke_tool(name, params, pending, canvas, timeout_s=min(tool_timeout_s, max(1, budget.deadline-time.monotonic())), sandbox_user_id=sandbox_user_id, sandbox_conversation_id=sandbox_conversation_id)
                    event("tool_finished", step, name=name, content=output)
                    if audit_enabled:
                        _audit("tool.completed", {"run_id": run_id, "agent_id": agent_id, "tool": name, "params": safe_params})
                except Exception as exc:
                    output = json.dumps({"is_error": True, "error": str(exc)}, ensure_ascii=False)
                    event("tool_failed", step, name=name, content=str(exc), status="failed")
                    if audit_enabled:
                        _audit("tool.failed", {"run_id": run_id, "agent_id": agent_id, "tool": name, "error": str(exc)})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
        if not answer:
            completion_status = "partial"
            event("limit", max_steps, content="执行预算已用尽，正在汇总已取得的结果", status="failed")
            messages.append({"role": "user", "content": "工具执行预算已用尽。停止调用工具，基于已经收到的结果给出可用结论、关键证据、尚未完成的部分及下一步。"})
            answer, _, _ = complete([], max_steps + 1)
    except Exception as exc:
        observations = [item for item in trace if item["type"] == "tool_finished"]
        if not observations:
            raise LocalChatError(f"智能体调用失败：{exc}") from exc
        completion_status = "partial"
        event("error", 0, content=str(exc), status="failed")
        answer = "本轮未能完成最终整合，已保留以下工具结果。\n\n" + "\n\n".join(
            f"**{row['name']}**\n\n{visible_text(row.get('content', ''))[:2500]}" for row in observations[-5:]
        ) + f"\n\n未完成原因：{exc}。请稍后继续本会话。"
    finally:
        if _client is None:
            client.close()
    result = {"answer": answer, "trace": trace, "pending_actions": pending, "canvas_items": canvas,
              "model": model, "run_id": run_id, "agent_id": agent_id,
              "tool_call_count": budget.count-starting_count, "completion_status": completion_status}
    if audit_enabled:
        _audit("turn.completed", {"run_id": run_id, "agent_id": agent_id, "model": model,
                                  "tool_call_count": result["tool_call_count"], "completion_status": completion_status})
    return result
