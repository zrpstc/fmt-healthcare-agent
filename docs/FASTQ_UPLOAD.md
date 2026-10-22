# FASTQ 上传卡住的修复

Next.js 15.5.27 的外部 rewrite 代理会克隆请求体，默认仅保留 10 MiB。
原有 `/backend/api/samples/upload` 经过该代理时，大于阈值的 multipart 文件被截断，
后端无法完成接收，页面一直等待；挂起连接还会阻止 Web 在收到 SIGTERM 后正常退出。
gpu02 日志中的 `Request body exceeded 10MB` 与 `test2: not_submitted` 对应这一问题。

## 当前行为

- 上传 URL 保持不变，由专用 Node.js Route Handler 流式转发到本机 API。
- 上传入口优先于通用 rewrite，不读取整个 FASTQ 到 Web 内存，不再经过其 10 MiB 克隆限制。
- multipart boundary、Content-Length（存在时）和登录 Authorization 会原样传递；也支持无 Content-Length 的分块上传。
- 其他 API 继续使用现有 rewrite。后端文件验证、样本互斥和分析任务启动逻辑保持原样。
- 页面显示上传百分比及已发送字节。发送完成后显示服务器校验/提交阶段；此时不代表分析已完成。
- 浏览器请求总超时为 15 分钟。服务器转发超时沿用 `WGS_WEB_PROXY_TIMEOUT_MS`，默认 900000 毫秒。
- 网络断开、代理超时及后端错误均显示明确提示。响应丢失时先刷新样本列表确认任务是否已创建，避免重复提交。
- 从双端切换到单端后，不发送之前选过的 R2。

## 验证

```bash
npm run test:upload --prefix apps/workspace-web
```

13 项回归涵盖大于 10 MiB 的完整转发、授权及 boundary 保留、错误透传、连接失败、
断连/超时中止、浏览器进度和单端提交。

完整 HTTP 检查脚本 `scripts/check_web_upload.py` 仅允许在独立
`/tmp/fmt-upload-fix-*` 源码副本运行；需要 Python 项目依赖、Web node_modules，
并先用 `WGS_API_PORT=18503` 构建前端。它启动回环地址的临时 Web 和真实 API，
使用独立临时运行目录及只执行 sleep 的合成 worker，不执行真实生信分析：

```bash
WGS_API_PORT=18503 NEXT_TELEMETRY_DISABLED=1 npm run build --prefix apps/workspace-web
PYTHONPATH=src:apps/workspace-api /path/to/project/.venv/bin/python scripts/check_web_upload.py
```

验证 25,682,694 字节的合成双端 gzip FASTQ，普通及分块上传均返回 202，落盘字节数
和 SHA-256 与输入完全相同；单端返回 202，重复样本返回 409，非法格式返回 422，
后端断连返回 502。Web 日志没有请求体截断警告。

## 应用到在线服务

此次只改变 Web 代码。必须重新构建并重启 Web，旧进程不会自动加载源码修改。
API、Agent 和 Elasticsearch 无需重启。若旧 Web 被已经挂起的上传连接阻塞，
应用脚本会先发送 SIGTERM，等待 15 秒，再核实进程命令、工作目录和启动时间后
结束该 Web 进程，断开挂起上传。脚本不会终止分析 worker。

应用成功后刷新浏览器，重新选择 R1、R2，再提交。之前卡住的请求不会自动恢复；
样本列表中没有创建的 ID 可以重新提交，已经存在的任务应直接查看其状态。
