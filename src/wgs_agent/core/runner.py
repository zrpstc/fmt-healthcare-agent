"""AgentRunner — 基于 AgentLoop 的执行引擎（WGS 版本）

简化版：专注 LLM 驱动的宏基因组分析
去除了 subagent/mcp/task 等未复制模块
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from wgs_fmt_platform.paths import runtime_path

from wgs_agent.core.config import WgsConfig
from wgs_agent.core.context import ExecutionContext
from wgs_agent.core.events.bus import EventBus, EventHandler
from wgs_agent.core.llm import make_provider
from wgs_agent.core.llm.base import LLMProvider
from wgs_agent.core.loop import AgentLoop
from wgs_agent.core.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class RunOutcome:
    status: str
    result: str
    reason: str | None


class AgentRunner:
    """执行一次基于 AgentLoop 的 WGS 分析 run"""

    def __init__(
        self,
        config: WgsConfig,
        *,
        bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        extra_handlers: list[EventHandler] | None = None,
        runs_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._bus = bus or EventBus()
        self._provider = provider
        self._extra_handlers: list[EventHandler] = extra_handlers or []
        self._runs_dir = runs_dir or runtime_path("WGS_RUNS_DIR", "runs")

    def _build_registry(self) -> ToolRegistry:
        """构建工具注册表 — 注册所有 WGS 分析 + 知识检索 + 自我审查工具"""
        registry = ToolRegistry()

        # ── WGS 领域工具 ──
        try:
            from wgs_agent.tools.domain_tools import DOMAIN_TOOLS
            for _tool_cls in DOMAIN_TOOLS:
                registry.register(_tool_cls())
        except ImportError:
            pass

        # ── 知识检索工具 ──
        try:
            from wgs_agent.tools.knowledge_tools import KNOWLEDGE_TOOLS
            for tool_cls in KNOWLEDGE_TOOLS:
                registry.register(tool_cls())
        except ImportError:
            pass

        # ── 自我审查工具 ──
        try:
            from wgs_agent.tools.reviewer_tool import SelfReviewTool
            registry.register(SelfReviewTool())
        except ImportError:
            pass

        return registry

    async def run_and_capture(self, goal: str, *, run_id: str | None = None) -> RunOutcome:
        """执行一次 agent run 并返回结果"""
        run_id = run_id or _now().replace(":", "").replace("-", "")
        run_path = self._runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        provider: LLMProvider = self._provider or make_provider(
            self._config.llm.provider,
            self._config.llm.default_model,
        )

        registry = self._build_registry()
        bus = self._bus

        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self._config.agent.max_steps,
            prefill_messages=[{"role": "user", "content": goal}],
            session_notes="",
            global_context="",
            project_context="",
        )

        loop = AgentLoop(
            provider, registry, bus,
            permission_manager=None,
            compactor=None,
            compact_threshold=0.0,
            session_id="",
        )

        try:
            await loop.run(context)
            return RunOutcome(
                status=context.status,
                result=context.result,
                reason=context.reason,
            )
        except asyncio.CancelledError:
            if not context.is_done():
                context.mark_failed("cancelled")
            raise
        except Exception:
            log.exception("agent run failed run_id=%s step=%d", run_id, context.step)
            if not context.is_done():
                context.mark_failed("llm_error")
            return RunOutcome(
                status=context.status,
                result=context.result,
                reason=context.reason,
            )
