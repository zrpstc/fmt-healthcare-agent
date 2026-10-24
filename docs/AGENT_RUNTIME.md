# FMT 主 Agent 与循证 subagent

唯一对话入口为 `fmt-researcher`（FMT科研助手）。`evidence-curator`（循证整理助手）
作为只读 subagent，通过 `delegate_evidence_review(task)` 被调用，结果返回主 Agent 整合。
子任务仅开放知识库/PubMed 检索，不能写报告、操作文件、启动 Pipeline 或再次委派。
主/子任务共享工具预算，单次循证子任务最多 4 次检索，保留最终汇总步骤。

系统提示词使用本机 `prompt-architect` 技能按实际工具、样本/通路/代谢物数据语义、
证据边界和失败处理重新设计；完整可复制版本在 `apps/workspace-api/app/agent_prompts.py`。
稳定运行约束为 `RUNTIME_PROMPT`，角色提示词分别为 `MAIN_SYSTEM_PROMPT` 与
`EVIDENCE_SYSTEM_PROMPT`；动态样本、已启用 Skills 和工作区设置在每轮注入。

## 本次修复

实测现用 Qwen3.6/SGLang 服务返回 `finish_reason=stop`，但 `message.tool_calls=null`，
实际工具请求在 `content` 中以 `<tool_call><function=...>` 出现。
旧循环将其当作最终答案，导致界面只显示思考/调用文本然后结束。

- 兼容原生结构化调用、Qwen XML 与 JSON 工具请求；按本轮开放工具及参数 Schema 校验，
  完整解析后才执行。截断、未知工具和非法参数触发有限修复，不执行半个调用。
- 对当前 Qwen 请求传入已实测的 `enable_thinking=false`，输出边界另外过滤思考标签。
- 检查结束原因：`length` 自动有限续答；异常结束、空回答和协议错误不再冒充完整回答。
- 达到执行预算后额外进行一次不开放工具的汇总；模型中途失败时保留已取得的工具结果，
  返回 `completion_status=partial` 及执行轨迹。
- 只有真正调用检索工具后，循证子任务才能提交证据摘要。
- 修复 PubMed 空摘要/内嵌标签导致的异常；合并结构化摘要各段，保留研究类型、可追溯链接
  和摘要截断标志。摘要不是全文，提示词要求不据未取得的段落推断结果。

现有 `/api/chat` 是完成整轮后返回 JSON，并非浏览器逐 token 流式接口；本次修复执行中断
的已复现根因，不引入新的 SSE 接口。

## 配置兼容

`GET /api/agents` 仅返回唯一主 Agent；设置页使用 `?include_subagents=true` 编辑主/子配置。
配置字段 `kind` 为 `agent` / `subagent`，子配置的 `parent_agent_id` 为 `fmt-researcher`。
不能新增第二个主 Agent，不能删除/停用唯一主 Agent。
旧 `evidence-curator` 会话仍可打开，后续消息由主 Agent 处理，原记录保留。

`scripts/upgrade_agent_catalog.py` 更新两份提示词及主从字段，保留模型、其他 Skills 与会话。
循证角色只绑定 `evidence-retrieval`，执行层另有独立只读白名单。

## 验证与激活

回归测试：`test_agent_protocol.py`、`test_agent_execution.py`、`test_agent_api.py`、
`test_agent_pubmed.py` 和原有 `test_workspace_agent.py`。涵盖真实故障格式、原生协议、
参数校验、委派、预算、长度续答、失败结果保留、单主入口和历史会话。
前端需通过 `npm run build`；真实模型验证记录在 `tmp/agent-runtime-20261024/smoke-*.json`。

本次采用独立 `.next-agent-runtime` 预构建目录，原 `.next` 保留。
生产 API/Web 目前以 root 运行，验证后执行：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
sudo bash deploy/activate-agent-runtime.sh
```

脚本只重启本项目 API/Web，备份 Agent 配置和 `.env`，迁移提示词，设置 Web 构建目录，
并检查 API、聊天页和转发后的单主入口。失败时恢复修改前的相关源码、配置和旧 Web 构建。
不重启模型服务、生信任务或 Elasticsearch。激活备份含运行配置，目录权限为 700，勿公开。
