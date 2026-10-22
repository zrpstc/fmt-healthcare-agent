# 样本编辑与永久删除

“样本与分析”页面选中样本后，可使用“编辑样本”和“删除样本”。需要登录管理员
或研究员账号；只读账号不能执行这两类操作。

## 编辑

- 可修改样本名称（最多 100 字符）和备注（最多 2000 字符）。
- 样本 ID 不变，原始文件、分析内容和既有 PDF 不因名称变更而重写。
- 名称同步显示在样本列表和报告中心，两处都可按 ID 或名称搜索。
- 尚无分析 JSON 的上传样本也可以编辑；运行中可以修改名称和备注。

接口：`PATCH /api/samples/{sample_id}`，JSON 为 `{"name":"名称","notes":"备注"}`。
省略的字段保持原值；空名称恢复为 ID；不接受修改 `sample_id`。

## 永久删除

点击“删除样本”，输入完全一致的样本 ID 后确认。此操作会永久删除配置目录下该样本的：

- 上传文件目录；
- 独立质控、去宿主、物种谱、功能谱及工作目录；
- 分析 JSON、知识 JSON、Markdown、PDF、结构化报告、证据 JSON 和标准图表；
- 上传任务、分组记录及独立任务日志。

不会删除其他样本、共享参考库、共享聚合矩阵、共享运行历史或聊天历史。不会按样本 ID
前缀模糊删除文件，因此 `p2` 与 `p2_other` 不会相互影响。

正在分析、上传或生成报告的样本不能删除。文件删除中途失败时，页面显示“删除未完成”，
处理存储错误后可重试；已删除的文件不会恢复。

删除成功后，样本和报告索引会同步移除，下载、报告生成及工作区 Agent 的样本访问会被阻止。
注册表只保留样本 ID 和删除时间，防止共享历史重新将样本加入索引；名称和备注会清除。
已删除的 ID 不可复用，再次上传请使用新 ID。

接口：`DELETE /api/samples/{sample_id}`，JSON 为
`{"confirmed":true,"confirm_sample_id":"同一样本ID"}`。需携带现有登录令牌。
重复删除返回成功；未知样本返回 404；未登录返回 401；只读账号返回 403；
任务忙或确认不一致返回 409；已删除样本的读取返回 410。

元数据默认保存在 `var/sample-registry/`，可以通过 `WGS_SAMPLE_REGISTRY_DIR` 覆盖。
无需安装新依赖或迁移数据库。实际删除由当前后端服务账号执行，沿用原运行目录权限。

## 验证

所有删除测试均使用独立临时目录和合成文件。新增测试覆盖授权、精确确认、文件清理、
相近 ID 隔离、共享资源保留、运行中拒绝、报告锁、上传互斥、部分失败重试、路径重定向、
存储配置变更以及已退出但尚未回收的 worker。

## 在 gpu02 应用

本次仅修改工作区源码，不重启服务，不删除实际样本。应用时需要重新构建前端，并重新
启动 API/Web/Agent。下面保留当前运行的 Elasticsearch，只重启应用服务，以避开已知
ES 冷启动期间的认证等待问题。请在准备好应用修改时手动执行：

```bash
sudo bash <<'SH'
set -euo pipefail
cd /home/zhanghaiyang/fmt-healthcare-agent
source deploy/common.sh

for name in workspace-web workspace-api agent-daemon; do
  pid_file="$DATA_ROOT/run/$name.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
      if [[ "$command_line" != *"$ROOT"* && "$command_line" != *"next-server"* ]]; then
        echo "PID $pid does not match the expected application; stopping."
        exit 1
      fi
      kill "$pid"
      for attempt in {1..60}; do
        state="$(ps -o stat= -p "$pid" || true)"
        if [[ -z "$state" || "$state" == Z* ]]; then break; fi
        sleep 1
      done
      state="$(ps -o stat= -p "$pid" || true)"
      if [[ -n "$state" && "$state" != Z* ]]; then
        echo "$name has not stopped; wait for active requests before retrying."
        exit 1
      fi
    fi
    rm -f "$pid_file"
  fi
done

NEXT_TELEMETRY_DISABLED=1 npm run build --prefix apps/workspace-web
bash deploy/start.sh
bash deploy/status.sh
SH
```

应用后，登录有写权限的账号，在“样本与分析”选中样本。先用测试样本检查编辑保存和
删除确认交互；永久删除只会在输入 ID 并提交后执行。
