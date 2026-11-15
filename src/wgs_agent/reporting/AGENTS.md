# 报告模块的 AI 阅读入口

修改本目录前，先从仓库根目录阅读：

1. `docs/CONSUMER_REPORTING_INFRASTRUCTURE.md`：公共接口、JSON契约、G1–G12与新章节接入步骤。
2. `docs/CONSUMER_REPORTING.md`：当前消费者章节和配置概览。
3. `docs/REPORT_BODY_TEMPLATES.md`、`docs/CMD_REFERENCE.md`：原稿合同、编号和参考资产规则。
4. 涉及知识子图时，再读 `docs/REPORT_KNOWLEDGE_SUBGRAPHS.md`。

先检查当前分支、未提交改动和对应源码。文档中的日期、测试计数和章级变更说明是历史快照；当前用户要求优先，不要覆盖其他任务已有的工作区改动。

消费者层复用现有格式、词典、omissions、参考和功能聚合接口。新增章节不只修改CONSUMER_CHAPTERS，还需接入解读、图片、目录、附录及测试。原始证据、单位、精度和稳定ID继续保留；Word原稿与word_contract.json维持只读。展示刷新不启动生信任务。

接口或默认策略改变时，同步更新基础设施指南与概览；不要仅把约定留在聊天、临时脚本或某一章的交付记录中。
