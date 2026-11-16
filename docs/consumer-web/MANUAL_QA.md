# 消费者版人工验收清单

Playwright 浏览器下载在当前 gpu02 环境被阻断（Node 18 低于 20；Chromium 下载连接 ECONNREFUSED 443）。因此浏览器打印预览采用人工验收；网页截图使用 OpenCode 内置 Chromium 生成，路径见 `docs/consumer-web/screenshots/`。另生成了静态打印 PDF `docs/consumer-web/screenshots/consumer-report-print.pdf`（用 ReportView 静态 HTML + WeasyPrint，28 页），用于核对打印 CSS，不等同于浏览器 `window.print()` 的逐页效果。

## 1. 响应式

在 Chrome DevTools 中检查：

- 375px：无页面横向滚动；目录为吸顶横向滚动条；状态卡片单列；宽表格只在 `overflow-x:auto` 容器内滚动。
- 768px：目录横向、正文单列；卡片可两列。
- 1280px：左侧 220px 吸顶目录；正文最大 720px 居中；状态卡片三列。
- 页脚附近不出现被截断的卡片。

## 2. 目录与术语

- 滚动时目录高亮当前部分；点击目录跳到对应 section。
- 点击虚下划线术语：手机底部抽屉、桌面气泡；Esc 关闭；焦点回到触发按钮。
- 每节顶部术语提示条只显示 approved 条目；pending/rejected 不显示。
- 公开页中不出现“待审”术语。

## 3. 子图

- 滚动到子图时才加载 vis-network；首屏不加载。
- 鼠标滚轮不缩放页面/子图；可拖动画布。
- 点击边打开底部抽屉，显示原句、文献标题、年份、DOI。
- 虚线表示 pending；图例文字正确。
- 打印时子图不渲染，改为“研究提示：A — 产生 → B”列表。

## 4. 打印 PDF

Chrome → 打印预览：

- A4 纸；目录、按钮、分享对话框隐藏。
- 卡片不跨页断开；“了解更多”全部展开。
- 子图为文字列表；页面不出现红色（consult 色仅用于就医提示框）。
- 打印出的消费者版 PDF 与专业版 PDF 是两个独立下载项。

## 5. 分享与安全

- 管理员/研究者能在报告中心生成 1/7/30/90 天链接；viewer 不显示分享按钮。
- 复制链接后，未登录浏览器打开 `/share/{token}` 能看到消费者版。
- 过期、撤销、错误 token 显示友好说明页，不暴露细节。
- 公开 JSON 不含真实 sample_id、服务器路径或内部服务 URL；响应头 `X-Robots-Tag: noindex`；页面 metadata `robots: noindex, nofollow`。
- 同一 IP 每分钟超过 60 次公开请求返回 429。

## 6. 审核台

- `/reports/review` 只对 admin/researcher 可读。
- 待审条目显示术语、字段、生成文本、来源、使用样本。
- 通过、编辑后通过、拒绝、批量通过都写入数据库；下一次打开报告自动重建，公开页不再显示 pending。
- reviewer 使用登录用户。

## 7. 性能

- 构建产物中 `/r/[sampleId]` 与 `/share/[token]` 首屏 JS 约 124 kB（gzip 前，Next 输出 First Load JS）；vis-network 只在滚动到子图时动态加载。
- 375px 首屏无横向滚动。
