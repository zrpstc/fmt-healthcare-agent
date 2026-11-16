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
| `GET /api/consumer/glossary/review` | admin/researcher | 审核队列 |
| `POST /api/consumer/glossary/review/{term_id}` | admin/researcher | 通过/修改后通过/拒绝 |

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

环境变量：

```bash
WGS_GLOSSARY_REQUIRE_REVIEW=1   # 默认；设为 0 时 pending 可在内部预览中显示
```

公开分享页无论该变量如何设置，都不显示 pending 术语。审核结果写入 `consumer_glossary_reviews`（`term_id`、`field`、`status`、`text`、`reviewer`、`reviewed_at`），构建器读取时数据库审核结果优先于 YAML 状态。

审核页面：`/reports/review`。待审条目不会进入公开 JSON；通过后下一次构建自动使用，缓存键随审核版本变化。

## 5. 文件与环境变量

- `WGS_RESULTS_DIR`：报告/产物目录，默认 `var/results`。
- `WGS_DATABASE_URL`：业务数据库；SQLite 默认可用。
- `WGS_WEB_SEARCH_PROVIDER=searxng` 与 `WGS_SEARXNG_URL`：可选术语网页检索，默认关闭。
- LLM 润色当前未接入运行时配置，默认全部使用规则文案；如接入需在 `narrative.py` 中增加受控调用和数字校验。

## 6. 验证

后端：

```bash
.venv/bin/python -m pytest -q
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
