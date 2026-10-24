# LitKG 原生图谱 GraphRAG 工具

`LitKGGraphRAGTool` 的 Agent 工具名是 `litkg_graph_rag`。工具只读使用当前配置的
LitKG 原生实体、关系、完整事实和原文证据，不创建本地图数据库、不重建图谱、不生成文件，
也不由工具自身调用 LLM 生成答案。主 Agent 和循证整理 subagent 均可通过只读 Skill 调用。

## 调用示例

```json
{
  "question": "Why might Faecalibacterium prausnitzii protect against inflammatory bowel disease?",
  "entities": [
    {"name": "Faecalibacterium prausnitzii", "entity_type": "MicrobialTaxon"},
    {"name": "inflammatory bowel disease", "entity_type": "Disease"}
  ],
  "hops": 2,
  "max_results": 8
}
```

样本问题由主 Agent 先读取真实样本工具，再传入发现的菌种、代谢物、疾病或通路名称。
工具不猜测样本，不读取任意文件路径。`entities` 为 1..4 项，`hops` 为 1..2，
`max_results` 为 1..12；不接受模型提供服务器 URL、KB ID、Shell 或写操作参数。
服务地址、KB ID、令牌和超时沿用已验证的 `WGS_CLAIM_API_*` 配置，当前正式库为 KB26。

## 检索与证据回溯

1. **实体标准化**：在 KB 内调用 `/entities`，按确切规范名、别名或标准标识匹配。
   原文 `F. prausnitzii` 可定位到原生节点 7255。多个确切匹配保留歧义候选，不自动合并。
   只有子串命中时要求细化；没有标准化 ID 时保留 `normalized_id=null`，不补造外部 ID。
2. **原生关系扩展**：调用 `/relations?entity_id=...&direction=both`，保留否定及推测。
   按实际端点构造候选 1–2 跳路径；连接用户指定起始实体的路径优先于孤立关键词命中。
   入边查询不改变原生谓词方向。
3. **完整事实回溯**：根据原生边的文档证据，用 `/facts?document_id=...&entity_id=...`
   分页读取完整事实。必须同时匹配 `relation_id`、谓词、端点参与者、否定/推测属性及有效原文，
   才能将边纳入返回子图。多元参与者与条件不被压平成无条件的二元因果。
4. **补充召回**：没有取得可核验图谱事实时，可用 `/ask`、`generate=false` 补充证据。
   补充事实不会凭空变成原生边或图路径。
5. **Agent 回答**：返回 `entity_resolution`、`subgraph`、`paths`、`facts`、`citations`、
   `retrieval_scope` 和 `warnings`。每条边/路径指向实际 Fact/Citation ID、文档、页码和 DOI。

路径中的 `cross_document`、`shared_document_ids`、`negated`、`speculative` 以及每段
`traversal` 明确可见。`interpretation=retrieved_chain_not_causal_proof` 表示这是一条
被逐段文献支持的检索链，不表示原研究证明了整条传递因果；同一文献也不保证人群或条件一致。
`extraction_confidence` 是抽取置信度，不能当作临床证据等级。
只读 Skill 还要求逐句核对原文支持度、保留未定义缩写，并将待审/原文支持不足的抽取列为疑点。

## 边界与预算

- 最多展开 6 个起始候选；二跳最多扩展 4 个相关邻居；每个节点最多读取前 40 条关系。
- 最多 24 次 HTTP 请求、90 秒总预算；完整事实最多回溯 8 组文档/实体，每组最多 2 页×50 条。
- 输出控制在约 17K 字符的实际工具 JSON 封装内。事实、引用、关联边和路径成组保留或省略，
  原文句和 JSON 不按前缀截断。省略数量和未穷尽范围在输出中明确标记。
- 上游部分失败时保留已核验事实并标记 `partial`；全部不可用时返回错误，不能据此断言没有关系。
- 当前重排是查询实体连接性、问题/研究条件的词汇相关性及待审标志，不宣称使用向量相似度或临床质量评分。

## 实测与启用

KB26 的原生图谱中实测找到了 `Faecalibacterium prausnitzii (7255)` →
`butyrate (7761)` → `inflammatory bowel disease (9176)` 的两段关系，
例如原生 Relation 13666 / 13777，完整 Fact 10878 / 10989，Citation 10878:0 / 10989:0。
同一文档 `kgmi-07-03-1134082.pdf` 的页码分别为 2 和 6。工具保留原始谓词及限制，
这些检索结果本身不构成对该菌临床疗效的证明。

真实工具查询约 0.8 秒，读取 16 次原生 HTTP 接口，返回 6 条有原文的边及对应事实，
受输出预算影响其余事实明确标记省略。实际 Qwen 模型已通过新工具检索并引用两跳链的
Relation/Fact/Citation ID。验证记录保存在 `tmp/graphrag-20261024/`。

最终回归测试 64 项通过；通过生产前端的 `/backend/api/chat` 通道实测 HTTP 200，
约 13.1 秒完整结束，实际调用 `litkg_graph_rag`，返回 6 条事实、6 个引用、6 条原生边和
6 条路径（含两跳路径）。已确认输出未被外层工具消息截断、引用对应实际返回的 ID，
并且主 Agent 与循证 subagent 均已绑定只读 Skill。

已知解释质量限制：当前 Qwen 在复测中仍将未定义的 HGC 解释为健康对照，并对
Fact 5037 的直接负相关作过强解读；该原句只明确陈述抗炎菌在 HGC 更常见、促炎菌与 IBD
相关。提示词已加入该指代反例和待审约束，但测试通过表示检索、权限、回溯与引用链路通过，
不表示 LLM 的每句科研解释均已核实。正式科研结论仍须核对原句及 LitKG 的待审标记。

只需重启后端 API，前端和 LitKG 无需重启。重启后注册并绑定 Skill：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
sudo bash deploy/restart-report-api.sh
.venv/bin/python scripts/enable_litkg_graphrag.py
```

`enable_litkg_graphrag.py` 先确认新工具已加载，再备份角色/Skills 配置，通过现有 API 创建
只读 `litkg-graphrag` Skill 并绑定主 Agent 和循证 subagent，保留模型、其他 Skills 及启停状态。
相关源码备份在 `tmp/graphrag-20261024/backup/`，配置备份在同目录的 `catalog-backup/`。
