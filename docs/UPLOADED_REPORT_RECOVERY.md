# 上传样本首次生成报告

生信任务的 `complete / 100%` 表示质控、去宿主、MetaPhlAn 和 HUMAnN 已完成。
报告需要另行确认生成。此前，报告中心只扫描 `results/`，完成生信但尚无分析 JSON
的上传样本既不会进入列表，也无法通过报告接口生成首次报告。

修复后的流程：

1. 报告中心同时列出已完成的上传任务，标记为“待生成”；读取列表不会生成文件。
2. 选中样本并确认“生成报告”后，复用规范位置的物种谱和功能谱创建分析 JSON。
3. 使用现有报告生成器输出 Markdown、PDF、结构化报告和证据 JSON。
4. 已有分析 JSON 原样保留；未完成的任务、无效物种谱和缺失功能谱会返回明确错误。
5. PDF 渲染失败时保留分析输入，重试即可，无需重新上传或重跑生信。

分析 JSON 保留输入丰度、来源和计算的多样性。没有参考比较或专项检测时，相关栏目
保持未评估，不补写疾病风险、药物关联或代谢物实测值。报告模型沿用现有配置。

## 在 gpu02 应用修改

仓库路径：`/home/zhanghaiyang/fmt-healthcare-agent`。修改源码不会自动更新正在运行的
Uvicorn 进程，也不会更新现有 Next.js 构建。以下步骤会停止并重新启动服务，请在决定
应用修改时手动执行；本次修复过程不执行这些命令。

```bash
ssh gpu02
cd /home/zhanghaiyang/fmt-healthcare-agent
git diff --check
git diff --stat

# 当前服务及部分运行文件属于 root，沿用现有启动权限。
sudo bash deploy/stop.sh
sudo env NEXT_TELEMETRY_DISABLED=1 npm run build --prefix apps/workspace-web
sudo bash deploy/start.sh
sudo bash deploy/status.sh
```

无需安装新依赖或迁移数据库。`stop.sh` / `start.sh` 会一起管理当前配置的 Elasticsearch。

服务启动后，打开报告中心，选择 `p2`，点击“生成报告”并确认。也可以在服务器调用：

```bash
curl -fsS -X POST http://127.0.0.1:8503/api/reports/p2/generate \
  -H 'Content-Type: application/json' -d '{"confirmed":true}'
```

成功后应出现 `p2_analysis.json`、`p2_health_report.md`、`p2_health_report.pdf`、
`p2_report.json` 和 `p2_report_evidence.json`。默认位置为项目的 `var/results/`；
若配置了 `WGS_RESULTS_DIR`，以该配置为准。页面会显示“报告已生成”，无需重传 FASTQ。

## 回归验证

在独立测试副本和临时运行目录执行以下测试，避免使用线上数据库与样本。

```bash
.venv/bin/python -m pytest -q tests/test_uploaded_reports.py \
  tests/test_sample_index.py tests/test_report_refresh.py tests/test_health_report.py \
  tests/test_workspace_agent.py tests/test_single_server.py
```

覆盖首次生成、列表无写入、用户确认、未完成任务、坏输入、保留已有分析、并发创建、
PDF 失败后重试及现有报告行为。前端使用独立副本运行 `npm run build`。
