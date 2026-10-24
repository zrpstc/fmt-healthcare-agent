"""Agent-facing read-only GraphRAG tool over the configured LitKG instance."""
from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from wgs_agent.core.tools.base import BaseTool, ToolResult
from wgs_fmt_platform.knowledge.litkg_graphrag import (
    GraphRAGError, NativeGraphRetriever, render_graph,
)
from wgs_fmt_platform.knowledge.litkg_retrieval import LitkgRetrievalConfig, LitkgRetrievalError


GRAPHRAG_SKILL_INSTRUCTIONS = """机制和多实体问题使用 litkg_graph_rag，优先检索实际实体的1至2跳关系。保留原生方向、条件、否定、推测及待审标志，路径逐段对应 Fact/Citation ID、原文与页码。
原生抽取关系是待核对的候选主张：以 citation 的原文句为依据，不能仅凭 predicate 或 qualifiers 就采纳结论。pending_review_kinds 含 claim_rejection、semantic_split 等时明确标注待审；原文不足以支持该抽取时单列为抽取疑点，不作为确定结论或已验证机制。原文未定义的缩写保留原样，不猜测扩写；标题、年份、研究类型未提供时不补造。直接引文逐字引用，省略必须标注，不能将改写文字伪装成原句。
指代核验反例：原句说“抗炎菌A在HGC更多；促炎菌B与疾病D相关，在LGC更多”，只支持A在HGC更多、B与D相关，不能据此断言A与D直接负相关。HGC/LGC 未给出定义时原样保留，不能扩写成健康/低葡萄糖控制或以此判断健康状态。若图谱将A与D抽取为直接关系，应注明原句支持不足、该边待核验。
TREATS 等原生谓词不能直接升级成已证实疗效；两跳路径仅为逐段检索链，同一文献或跨文献均不自动证明整体因果。输出前逐条核对主张与原句的研究对象、限定条件和结论强度，说明检索范围及省略情况。"""


class EntitySeed(BaseModel):
    model_config = {'extra':'forbid','str_strip_whitespace':True}
    name: str = Field(min_length=1, max_length=200, description='实体名称、拉丁名、别名或标准标识，不能编造内部 ID')
    entity_type: str = Field(default='', max_length=80, description='可选实体类型，例如 MicrobialTaxon、Metabolite、Disease、BiologicalProcess')


class GraphRAGParams(BaseModel):
    model_config = {'extra':'forbid','str_strip_whitespace':True}
    question: str = Field(min_length=1, max_length=2000)
    entities: list[EntitySeed] = Field(min_length=1, max_length=4)
    hops: int = Field(default=2, ge=1, le=2)
    max_results: int = Field(default=8, ge=1, le=12)


class LitKGGraphRAGTool(BaseTool):
    name = 'litkg_graph_rag'
    description = (
        '只读使用 LitKG 原生图谱回答机制、关系链或样本实体问题。先传入从问题/真实样本结果提取的英文实体或拉丁名，'
        '通过 /entities 标准化、/relations 扩展1至2跳、/facts 回溯原文，必要时 /ask(generate=false) 补充；'
        '返回有逐段证据的子图、路径、事实与页码。路径不自动证明因果，不创建文件或修改图谱。'
    )
    params_model = GraphRAGParams
    input_schema = {
        'type':'object', 'additionalProperties':False,
        'properties': {
            'question':{'type':'string','minLength':1,'maxLength':2000,'description':'具体科研问题，建议英文，最终仍用中文回答'},
            'entities':{'type':'array','minItems':1,'maxItems':4,'description':'从问题或已读取样本中提取的实体；同名歧义时提供类型',
                'items':{'type':'object','additionalProperties':False,'properties':{
                    'name':{'type':'string','minLength':1,'maxLength':200},
                    'entity_type':{'type':'string','maxLength':80}},'required':['name']}},
            'hops':{'type':'integer','minimum':1,'maximum':2,'default':2},
            'max_results':{'type':'integer','minimum':1,'maximum':12,'default':8},
        }, 'required':['question','entities'],
    }

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        try:
            values = self.params_model.model_validate(params)
            retriever = NativeGraphRetriever(LitkgRetrievalConfig.from_env())
            result = await retriever.retrieve(values.question, [seed.model_dump() for seed in values.entities],
                hops=values.hops, max_results=values.max_results)
            return ToolResult(content=render_graph(result), is_error=result['status']=='unavailable')
        except (LitkgRetrievalError, ValidationError) as exc:
            message = str(exc) if isinstance(exc, GraphRAGError) else 'GraphRAG 配置或参数无效；请检查知识库配置与实体名称/类型'
            return ToolResult(content=json.dumps({'source':'litkg-native-graphrag','status':'unavailable',
                'error':message,'warnings':['图谱检索未完成；不能据此断言不存在相关关系。']},ensure_ascii=False),
                is_error=True, error_type='runtime_error')
        except Exception as exc:
            return ToolResult(content=json.dumps({'source':'litkg-native-graphrag','status':'unavailable',
                'error':f'GraphRAG 响应处理失败（{type(exc).__name__}）'},ensure_ascii=False),
                is_error=True,error_type='runtime_error')
