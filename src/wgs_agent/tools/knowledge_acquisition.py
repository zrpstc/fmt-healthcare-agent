"""Acquire complete knowledge data without putting the whole export into a model message."""
import json
from pydantic import BaseModel
from wgs_agent.core.tools.base import BaseTool, ToolResult
from wgs_fmt_platform.knowledge.litkg_retrieval import LitkgRetrievalConfig
from wgs_fmt_platform.knowledge.litkg_acquisition import acquire_knowledge_base, snapshot_path, snapshot_summary

class KnowledgeFetchParams(BaseModel):
    force_refresh: bool = False

class KnowledgeBaseFetchTool(BaseTool):
    name = 'fetch_knowledge_base'
    description = '获取当前知识库全部实体、关系、claim 与事实，保留待审核及所有关系类型。返回完整快照位置和数量；后续如何检索、分析或引用由使用层单独规定。'
    params_model = KnowledgeFetchParams
    input_schema = {'type': 'object', 'properties': {'force_refresh': {'type': 'boolean', 'default': False}}, 'additionalProperties': False}

    async def invoke(self, params):
        try:
            values = self.params_model.model_validate(params)
            config = LitkgRetrievalConfig.from_env()
            snapshot = await acquire_knowledge_base(config, force_refresh=values.force_refresh)
            return ToolResult(content=json.dumps({**snapshot_summary(snapshot), 'snapshot_path': str(snapshot_path(config))}, ensure_ascii=False))
        except Exception:
            return ToolResult(content='Complete knowledge base acquisition failed; no partial snapshot was published.', is_error=True, error_type='knowledge_acquisition_error')
