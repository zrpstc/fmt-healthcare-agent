# 消费者版报告运维说明

## 1. 构建与刷新

离线构建：

```bash
cd /path/to/fmt-healthcare-agent
.venv/bin/python scripts/build_consumer_report.py ZYMO_D6331 --refresh
```

产物写入：

```text
${WGS_RESULTS_DIR:-var/results}/ZYMO_D6331_consumer_report.json
${WGS_RESULTS_DIR:-var/results}/ZYMO_D6331_consumer_report.cache.json
```

缓存键包含：源 `{sample}_report.json` 的 SHA-256、构建器版本、术语库版本、数据库审核结果版本、是否允许 pending。任一变化会重建。

## 2. 后端接口

| 接口 | 权限 | 说明 |
|---|---|---|
| `GET /api/reports/{sid}/consumer` | 与现有报告接口一致 | 返回视图模型；过期自动重建；`?refresh=1` 仅 admin/researcher |
| `POST /api/reports/{sid}/consumer/share` | admin/researcher | 生成 1–90 天分享链接，返回 token/url/expires_at |
| `GET /api/reports/{sid}/consumer/shares` | admin/researcher | 列出链接状态 |
| `DELETE /api/reports/{sid}/consumer/shares/{id}` | admin/researcher | 撤销链接 |
| `GET /api/share/{token}` | 公开 | 校验过期/撤销；样本 ID 换成别名；`X-Robots-Tag: noindex` |
| `GET /api/share/{token}/downloads/{kind}` | 公开 | PDF/CSV 下载 |
| `GET /api/reports/{sid}/consumer/downloads/{kind}` | 公开（内部预览） | PDF/CSV 下载 |
| `GET /api/consumer/glossary/review` | admin/researcher | 审核队列；默认不含已拒绝条目，`?include_rejected=1` 时一并返回 |
| `POST /api/consumer/glossary/review/{term_id}` | admin/researcher | 按字段（`one_liner` / `watch_note`）通过、修改后通过或拒绝；通过时文字为空返回 422；术语或字段不存在返回 404 |
| `POST /api/consumer/glossary/generate` | admin/researcher | 为指定样本中缺少解释的菌生成解释草稿，请求体 `{sample_id, limit=20, use_llm=true}`；结果一律 pending |

分享令牌使用 `secrets.token_urlsafe(32)`，数据库只存 SHA-256。公开接口同一 IP 每分钟最多 60 次请求。

## 3. 前端

```bash
cd apps/workspace-web
npm install
npm run build
npm run start -- -p 18502
```

路由：

- `/r/{sampleId}`：内部预览，不套工作区侧栏。
- `/share/{token}`：公开只读页，不套侧栏，`noindex, nofollow`。
- `/reports`：报告中心，新增“消费者版预览”“分享给用户”，artifact ribbon 新增“消费者版 JSON”。
- `/reports/review`：术语与说明审核台（admin/researcher）。
- `/samples`：有消费者版 JSON 时显示“消费者版报告”入口。

前端只渲染 Python 生成的 `display`，不做百分比、分档或术语判断。

## 4. 术语审核

### 4.1 三个来源与合并规则

解释文字按 `(term_id, field)` 合并，字段分两种，分开审核：

- `one_liner`：一句话说明，不超过 40 字；
- `watch_note`：需留意说明，不超过 60 字。

来源优先级从低到高：

1. 人工词条 `knowledge_base/consumer_glossary.yaml`（v2，内容是 JSON）；
2. 机器草稿表 `consumer_glossary_candidates`，草稿一律 pending；
3. 人工审核表 `consumer_glossary_reviews`（`term_id`、`field`、`status`、`text`、`reviewer`、`reviewed_at`），覆盖前两者。

菌的解释按拉丁学名或别名查找（`GlossaryService.taxon_term`），不再维护中文名映射表。属级面板成员按实际检出菌的学名解析，不再把某个种的解释挂到整个属上。`watch_note` 在种级没有记录时可以回退到属级词条，`one_liner` 不回退。

只有 `approved` 的文字才能进入正文。**AI 或脚本不得把自己写的内容标为 approved**，必须由人在审核台批准。

### 4.2 缺口记录与草稿生成

构建报告时，正文展示了某个菌却没有可审核的文字，构建器会把它写进：

```text
${WGS_RESULTS_DIR:-var/results}/{sample}_consumer_glossary_needs.json
```

生成草稿（先构建一次报告，再执行）：

```bash
.venv/bin/python scripts/build_consumer_report.py ZYMO_D6331
.venv/bin/python scripts/generate_consumer_glossary.py ZYMO_D6331 --limit 20
.venv/bin/python scripts/generate_consumer_glossary.py ZYMO_D6331 --no-llm   # 只收集证据，由审核人撰写
```

也可以在审核台选择样本，点击「补全解释」，效果等同于调用 `POST /api/consumer/glossary/generate`。

证据依次来自：

1. 结构化报告中已保存的 LitKG 文献声明；
2. PubMed 摘要（需 `WGS_CONSUMER_GLOSSARY_PUBMED=1`，可选 `NCBI_API_KEY`）；
3. SearXNG 检索摘要（需 `WGS_WEB_SEARCH_PROVIDER=searxng` 和 `WGS_SEARXNG_URL`，只接受白名单域名）。

报告模型由 `wgs_agent.tools.detailed_report.resolve_report_model()` 读取。模型把证据压缩成一句话后，草稿要通过以下校验：长度、禁用措辞（有益菌、有害菌、致病、导致、治疗、益生菌等）、不得出现英文、属级证据必须以「同属研究提示」开头、必须引用证据编号。未通过或未配置模型时，只把证据写入候选表，`draft_status` 记录原因，由审核人撰写。证据文本一律当作数据，不当作指令。

已有文字的候选条目不会被重新生成覆盖；重复运行只会合并样本列表、刷新证据。

### 4.3 审核台

页面：`/reports/review`。侧栏「术语审核」入口只对 admin/researcher 显示。

- 每条显示字段、当前文字、证据、来源和用到它的样本；
- 通过时必须填写文字，可直接修改后通过；
- 被拒绝的条目默认不再回到队列，勾选「显示已拒绝」可以查看并重新处理；
- 可选择样本，一键「补全解释」。

审核结果写入数据库后，下一次构建自动生效：缓存键包含审核版本。

### 4.4 预览开关

```bash
WGS_GLOSSARY_REQUIRE_REVIEW=1   # 默认；设为 0 时 pending 内容带「待审」标记显示在内部预览中
```

该开关只影响内部预览。公开分享页始终以 `allow_pending=False` 构建，无论变量如何设置都不显示 pending 内容。

## 5. 文件与环境变量

- `WGS_RESULTS_DIR`：报告/产物目录，默认 `var/results`。
- `WGS_DATABASE_URL`：业务数据库；SQLite 默认可用。
- `WGS_WEB_SEARCH_PROVIDER=searxng` 与 `WGS_SEARXNG_URL`：可选术语网页检索，默认关闭。
- `WGS_CONSUMER_GLOSSARY_PUBMED=1`：草稿生成时检索 PubMed，默认关闭；`NCBI_API_KEY` 可选，用于提高 PubMed 限流额度。
- `{sample}_consumer_glossary_needs.json`：构建时写出的解释缺口清单，供草稿生成使用。
- LLM 润色当前未接入运行时配置，默认全部使用规则文案；如接入需在 `narrative.py` 中增加受控调用和数字校验。

## 6. 验证

后端（项目要求 Python ≥3.12 且 <3.13）：

```bash
.venv/bin/python -m pytest tests/test_consumer_*.py -q   # 消费者版测试
.venv/bin/python -m pytest -q                            # 全量
```

注意：`uv.lock` 目前与 `pyproject.toml` 不同步，`uv sync --frozen` 不会安装 numpy；测试还会导入 pandas 等 `legacy` 依赖。搭建测试环境时可以执行：

```bash
uv pip install -e ".[dev,infra,legacy]"
```

前端：

```bash
cd apps/workspace-web
npx tsc --noEmit
npm run build
npm run lint
node --test tests/consumer.test.mjs
```

扫描消费者 JSON：

```bash
.venv/bin/python scripts/scan_consumer_report.py ZYMO_D6331
```

（如果脚本不存在，使用 `tests/test_consumer_builder.py` 中的扫描逻辑。）
