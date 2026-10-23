# 证据知识库与样本关联子图

`/knowledge` 的图谱工作区参照 LitKG `FMT_use`：35 类实体使用相同配色，
节点浅色背景和深色文字，提供中文类别图例、关系方向、力导向/层次/环形布局、
节点拖拽、画布缩放、证据检查和完整白底 PNG 导出。分散的连通分量会重新排布。
微生物分类单元、菌株、群落、微生物组、代谢物等类别各有独立颜色。

选择节点或关系可查看原句、文档、Claim、页码及限定条件。否定关系显示红色，
推测和待审核关系使用虚线，不显著关系显示蓝色。对于较大的图谱，导出时可选 1×，
避免超出浏览器画布容量；超限时会显示可操作的提示。

## 样本关联子图

在“样本关联子图”中选择已有分析结果或绑定证据的样本，再点击“展示最相关子图”。
默认显示前 40 条关系，可选择 20/40/80/150 条。画布中粗边框标出与样本检测项匹配的实体。

只读接口：`GET /api/knowledge/samples/{sample_id}/graph?limit=40`。

1. 读取现有 analysis、knowledge 和结构化 report 文件，不重新运行样本分析或报告生成。
2. 从物种、分类谱、通路、代谢物、疾病、药物、蛋白等结果提取实体标识；
   不使用样本名称、文件名、文献标题或背景原句作为样本实体。
3. 分页读取当前配置的 LitKG Claim，最多 10000 条，整个扫描最多 45 秒。
4. 仅选择主客体匹配检测实体，或已保存在该样本证据中的真实关系。
   保留原始方向、实体类别、否定、推测、置信度、限定条件和证据来源，不创建推断边。
5. 普通检测实体匹配 50 分，异常检测项 75 分，每条关系最多计入前四个匹配实体；
   报告引用加 30 分，样本已保存证据加 15 分。同分按置信度、Claim ID 排序。
   这是确定性检索排序；点击关系可查看具体匹配依据。
6. 按知识库和 Claim 去重，实体身份也按知识库隔离。`selection` 返回候选数、匹配数和截断情况。

知识服务异常时，保留已扫描的关系和样本已保存证据，`retrieval.status` 与页面提示说明范围。
达到扫描上限时同样显示提示；无匹配显示空状态。已删除样本沿用现有的 410 响应。
样本测量值不发送给 LitKG，只在本机匹配。

## 验证与上线

```bash
WGS_WORKSPACE="$PWD/tmp/knowledge-ui-tests" \
WGS_REPORT_GRAPH_RETRIEVAL_DISABLED=1 WGS_REPORT_GRAPH_LLM_DISABLED=1 \
.venv/bin/python -m pytest tests/test_sample_knowledge_graph.py tests/test_litkg_documents.py \
tests/test_report_knowledge_graph.py tests/test_graph_presentation.py tests/test_sample_management.py -q

cd apps/workspace-web
WGS_WEB_DIST_DIR=.next-knowledge NEXT_TELEMETRY_DISABLED=1 npm run build
```

生产构建可使用 `WGS_WEB_DIST_DIR` 隔离验证，默认仍使用 `.next`。
若现有服务由 root 运行，执行 `sudo bash deploy/activate-knowledge-ui.sh`。
该脚本备份旧 Web 构建，构建默认 `.next`，只重启 API/Web，检查两个服务的 HTTP 响应。
构建失败会恢复旧 Web 构建；不重启 Elasticsearch 或生信流水线。
