# 健康报告 v3

网页的“重新生成报告”和 `generate_report` 工具现在生成 `health-report-v3`。
正文参考商业检测报告的总览、分项结果、结果说明和日常关注顺序。
目录与数值由程序确定；LLM 按固定主题撰写结构化中文解读。图片及装饰性矢量图不在这次改动范围。

## 固定内容

目录定义在 `src/wgs_agent/reporting/catalog.py`，包括 11 个板块、66 个固定细分方向：

| 板块 | 固定细分方向 |
| --- | --- |
| 菌群组成与结构 | 门、属、种组成，优势菌属与群落分型，优势菌集中程度 |
| 菌群多样性 | 检出丰富度、Shannon、Simpson、Pielou，参考人群位置与纵向变化 |
| 重点菌群 | 双歧杆菌、乳酸菌、产丁酸相关菌、黏液利用相关菌、条件致病相关菌、病原体与毒力标志 |
| 肠道微生态功能 | 定植抵抗、屏障、炎症与免疫、产气与气体利用、黏液与交叉营养、氧化应激 |
| 营养物质代谢 | 碳水化合物、纤维与抗性淀粉、蛋白质与氨基酸、脂质与胆汁酸、维生素、核苷酸与嘌呤 |
| 微生物代谢产物 | 短链脂肪酸、乳酸与琥珀酸、次级胆汁酸、吲哚、酚与胺类、氨与硫化氢、TMA/TMAO |
| 营养摄入与状态推算 | 宏量营养素、纤维、饮食多样性、维生素、矿物质 |
| 肠脑轴及内分泌关联 | 色氨酸、GABA、组胺、儿茶酚胺、雌激素再循环、代谢内分泌信号 |
| 症状相关菌分析 | 腹胀排气、便秘、腹泻、腹痛、排便性状及食物相关不适 |
| 疾病相关特征与风险模型 | 肠道、代谢、肝脏、心血管、神经精神、其他研究关联，经过验证的预测模型 |
| 抗生素耐药性 | β-内酰胺、氨基糖苷、大环内酯、喹诺酮、四环素、磺胺及甲氧苄啶、其他及多重耐药、机制与基因背景 |

有结果的主题展示指标表和短解读；其余固定方向汇总为简洁的未评估表。
“有可用结果”表示存在数据，不表示健康正常。缺失、零值、参考人群区间内分别处理。
明确标为质控失败的样本不生成健康解读。

## 生成链路与产物

1. `ReportGeneratorTool` 读取分析 JSON 和知识 JSON。
2. `reporting/inputs.py` 补读同一样本的既有 MetaPhlAn 和 HUMAnN 产物。
3. `reporting/document.py` 整理数值、来源类型、固定主题和证据 ID。
4. `reporting/narrative.py` 按板块分批调用模型，逐项验证并填入解读。
5. `report_maker.py` 将同一正文输出为 Markdown 和 FPDF PDF。

常规报告不启动 FMT 计算或聚类绘图。已有 FMT 结果可保留在附录。
旧的 `detailed_report.build_detailed_report()` 是科研报告兼容实现，已不作为网页健康报告正文入口。

### 自动参考比较

网页和对话的 `ReportGeneratorTool` 在每次生成时调用 `reporting/reference.py`：

- 从既有完整物种谱恢复全部物种（包括 SGB），或沿用分析文件已有物种条目，重新计算参考比较。
- 优先使用 `WGS_SPECIES_REFERENCE_FILE`，其次使用 `WGS_REFERENCE_DIR/species_reference_overall.csv`。
  默认工作区下，`var/reference` 没有该文件时兼容读取 `data/reference/species_reference_overall.csv`。
  显式配置的路径缺失时不偷偷切换其他人群；自定义工作区也不读取默认工作区的存量数据。
- 参考表采用 CSV 或 TSV 长表，`species/p5/p95` 必需，丰度单位为百分数；支持 `median/p50`、
  `n_samples`、`n_detected/cond_n`、`detection_rate`、`stratum`。总体样本数和检出数分别保存。
  物种未覆盖、零宽区间、单位不可比或观测无效分别记录原因，不能作为正常结果。
- 完整且有效的样本谱还可与 `WGS_FMT_MATCHING_DIR`（默认 `var/data/fmt-matching`）中的
  `species_abundance_train.csv`、`match.xlsx` 建立探索性多样性比较。仅纳入 `donor + healthy`，
  排除当前样本；存在 `subject_id` 时按个体去重并排除当前个体，不足 30 份有效参考时不建立比较。
  参考和样本使用相同多样性公式。该子集未作人口学匹配，数据库和完整特征口径仍需核验；
  经验百分位不是疾病概率。已有纵向记录继续保留。
- 新比较与参考文件内容哈希进入分析 JSON、结构化报告和证据 JSON。全部报告产物渲染成功后
  才替换更新后的分析文件；PDF 失败或分析文件被其他写入者更新时，不发布本次比较和报告。
- 不运行新的测序分析、FMT 模型或外部数据下载，也不将实测代谢物浓度资料套用到预测产能。

现有总体表的所有物种 P5 均为零，因此按该表不能判断偏低；多数物种 P5=P95=0，继续保留
未比较状态。参考表健康筛选、独立人数和软件数据库版本尚未核验，报告会呈现此适用范围。

同一目录发布以下文件：

- `{sample_id}_health_report.md`：网页预览和正文。
- `{sample_id}_health_report.pdf`：中文 PDF，带封面、总览、章节分页和书签。
- `{sample_id}_report.json`：完整结构化报告，包括每个主题、证据和已接受模型文本。
- `{sample_id}_report_evidence.json`：输入摘要、哈希、运行状态、引用检查及模型回退原因。

先完成整套暂存产物，再替换文件；PDF 生成失败时保留上一版。文件权限为 `0600`，同一样本使用文件锁避免并发覆盖。
网页 `/api/reports/{sample_id}/structured` 可下载结构化报告。

## 模型服务

继续使用已有工作区模型配置。不需要安装 SGLang 客户端或更改推理框架。
接口只需接受标准的 `POST <base_url>/chat/completions`，并将最终 JSON 返回在
`choices[0].message.content` 中。`base_url` 通常以 `/v1` 结尾。

可选的报告专用环境变量：

```dotenv
# 同时设置 BASE_URL 和 MODEL 时覆盖工作区模型。
WGS_REPORT_LLM_BASE_URL=http://127.0.0.1:30000/v1
WGS_REPORT_LLM_MODEL=your-served-model
# 如服务需要认证，单独通过受限环境变量配置 WGS_REPORT_LLM_API_KEY。
WGS_REPORT_LLM_DISABLED=0
WGS_REPORT_RESPONSE_FORMAT=json_object
WGS_REPORT_MAX_TOKENS=8192
WGS_REPORT_LLM_CONCURRENCY=2
WGS_REPORT_TIMEOUT_SECONDS=180
WGS_WEB_PROXY_TIMEOUT_MS=900000
```

`WGS_REPORT_RESPONSE_FORMAT` 支持 `json_object`、`json_schema`、`none`。
默认 JSON mode；后端明确拒绝 `response_format` 时重试普通文本模式，仍要求并验证 JSON。
支持 JSON-schema 约束解码的服务可以改用 `json_schema`。模型需有足够上下文和输出空间；
建议从支持至少 32k 上下文、能稳定输出中文 JSON 的指令模型开始验证。
推理模型的内部思考不进入正文，不读取 `reasoning_content`。客户端不发送特定厂商的 thinking 参数。
网页的代理超时默认延长到15分钟，避免分批生成被 Next 默认的30秒限制中断。
这项配置需要重新构建并启动 Web 服务才生效；本次代码修改不自动部署。

官方接口说明：
[SGLang chat completions](https://docs.sglang.io/docs/basic_usage/openai_api_completions)、
[SGLang structured outputs](https://docs.sglang.io/docs/advanced_features/structured_outputs)。

## 提示词与校验

`SYSTEM_PROMPT` 和 `WRITING_RULES` 位于 `reporting/narrative.py`。
模型每个主题返回：

```json
{
  "id": "key_taxa.bifidobacteria",
  "mode": "observation",
  "interpretation": "只解释本主题已提供的结果，正文不重述具体数字。",
  "advice": "可留空，或提供适度的背景记录建议。",
  "evidence_ids": ["S1"],
  "support_quotes": [{"id": "S1", "quote": "从本主题样本记录中逐字摘录支持文本"}]
}
```

外层固定为 `sections: [{id, topics: [...]}]`。
`observation` 模式仅解读检测记录；`association` 模式同时要求本主题样本和文献证据。
文献标题不能充当研究结论。未知 ID、跨主题引用、重复主题、错误摘录、数字编造、诊断及用药建议会被拒绝。
每批最多修复一次格式或内容错误；网络失败不反复重试。失败主题保留指标和规则说明，其他已通过主题继续使用。
审计字段 `llm_status` 为 `generated`、`partial`、`fallback`、`not_configured` 或 `no_eligible_data`。

引用绑定和文本规则不等于医学语义已经验证。审计保留 `semantic_entailment_verified: false`，
临床上线前仍需专业人员审核知识适用性、模型解读和真实样本表现。

## 上游输入约定

原有 `species/compare/enterotype/pathways/metabolites/diseases/knowledge` 继续支持。
新增可选模块为 `taxonomy/diversity/functional_modules/nutrition/diet/symptoms/gut_brain/resistance/pathogens/disease_models`。
补充模块可以是记录列表，或以 `observations`、`items`、`results` 为键的对象。

典型补充输入：

```json
{
  "diet": {"observations": [
    {"name": "膳食纤维摄入", "value": 18, "unit": "g/day", "method": "饮食记录", "data_type": "reported"}
  ]},
  "symptoms": {"observations": [
    {"name": "腹胀", "answer": "偶发", "duration": "待补充"}
  ]},
  "resistance": {"method": "由上游填写实际方法", "genes": [
    {"gene": "由上游填写", "drug_class": "tetracycline", "mechanism": "由上游填写", "result": "由上游填写检测判定"}
  ]}
}
```

完整运行示例见 `scripts/preview_health_report.py` 中的 `demonstration()`；所有值均为合成数据。

- `taxonomy.ranks` 支持 `phylum/genus/species` 列表；`complete: true` 表示完整物种谱。
- 只有完整且有效的物种谱才计算多样性；保留未命名 SGB。Shannon 使用自然对数，Simpson 使用 `1−Σp²`，Pielou 使用 `H/ln(S)`，单物种时 Pielou 不定义。
- `species.is_complete_profile: true` 只能用于未被 Top N、名称或参考库覆盖过滤的完整物种数据。
- 已有单样本原始产物按 `profiles/metaphlan/{sample_id}_profile.tsv` 和 `profiles/humann/{sample_id}_pathabundance_relab.tsv` 读取。
- 完整通路和代谢物保留在结构化结果中；展示层取摘要。`UNMAPPED/UNINTEGRATED` 留在注释覆盖审计中，不能作为生物学通路。
- 测量条目需 `data_type: measured`（也支持 `metabolomics/clinical_measurement`）、实际 `method` 和 `unit`，否则不标为实测。
- 预测模型仅在同时有 `externally_validated: true`、`applicable: true`、`model_version` 时进入独立模型主题；这些元数据必须由上游模型注册和验证流程提供。
- 知识库记录可通过 `topic_ids` 明确绑定主题；关键词用于检索归类，不作为机制成立或功能强弱的计算依据。

报告层不会运行新的耐药基因检测，不会把药物交互分当作耐药性。
缺少 AMR、饮食问卷、临床营养检验或内分泌数据时，相关项目保留未评估状态。

## 预览与验证

在项目 Python 3.12 环境安装现有 `legacy` 和 `dev` 依赖后运行：

```bash
PYTHONPATH=src python scripts/preview_health_report.py
# 使用已配置的模型生成合成样例的解读：
PYTHONPATH=src python scripts/preview_health_report.py --use-llm --output-dir tmp/health-report-llm-preview
# 使用已有分析文件，默认离线且输出到独立目录：
PYTHONPATH=src python scripts/preview_health_report.py --analysis /path/SAMPLE_analysis.json --output-dir tmp/sample-preview
python -m pytest tests/test_health_report.py tests/test_detailed_report.py tests/test_claim_report_references.py tests/test_report_refresh.py
```

脚本默认不调用模型，不覆盖已有预览输入。默认产物在 `tmp/health-report-preview`。
字体按显式环境变量、仓库本地字体、系统 Noto CJK、文泉驿顺序查找，无自动下载。
可用 `WGS_REPORT_FONT_REGULAR/WGS_REPORT_FONT_BOLD` 指定字体路径。
