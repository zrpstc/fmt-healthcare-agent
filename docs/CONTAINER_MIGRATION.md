# containerComputerNode 容器迁移

## 包内容

- Python 3.12 slim 运行环境
- 锁定依赖 `uv.lock`
- 非 root 用户 `wgs`（UID/GID 10001）
- FastAPI daemon 与健康检查
- Claim API OpenAPI 启动探测
- 持久化卷 `/app/var`
- 默认只读根文件系统、删除 Linux capabilities

## 1. 复制并解压

```bash
scp WGS-FMT-Agent-v2-container-bundle.tar.gz containerComputerNode:/opt/src/
ssh containerComputerNode
cd /opt/src
tar -xzf WGS-FMT-Agent-v2-container-bundle.tar.gz
cd WGS-FMT-Agent-v2/deploy/container
```

## 2. 配置

```bash
cp .env.container.example .env.container
```

默认配置使用：

```text
WGS_CLAIM_API_URL=http://10.181.8.92:8080
WGS_CLAIM_API_OPENAPI_PATH=/openapi.json
WGS_CLAIM_API_KNOWLEDGE_BASE_IDS=auto
```

`auto` 会先读取 `/knowledge-bases`，因此知识库重建并产生新 ID 后无需修改配置。
如需限制检索范围，可填写逗号分隔的 ID，例如 `25,26`；知识库页面也可以临时多选。

先从计算节点验证：

```bash
curl -fsS http://10.181.8.92:8080/openapi.json | python -m json.tool | head -100
```

如果自动选择的 Claim 路由不正确，在 `.env.container` 明确填写：

```text
WGS_CLAIM_API_SEARCH_PATH=/实际/claim/查询路径
WGS_CLAIM_API_SEARCH_METHOD=GET或POST
WGS_CLAIM_API_VERSION_PATH=/实际/version/路径
```

## 3. 构建与启动

```bash
docker compose build --pull
docker compose up -d
docker compose logs -f wgs-fmt-agent
```

启动日志会输出 OpenAPI 中发现的 Claim 路由。若 Docker bridge 无法访问内网 API：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.host-network.yml \
  up -d
```

## 4. 验证

```bash
curl -fsS http://127.0.0.1:8000/health
docker compose exec wgs-fmt-agent python -m wgs_fmt_platform.knowledge.probe
docker compose exec wgs-fmt-agent python -m pytest -q
```

生产镜像默认不安装测试依赖，因此最后一条仅适用于以 `--extra dev` 构建的调试镜像。

## 5. 数据迁移

将需要保留的数据放入 Docker 卷对应的 `/app/var`：

```text
/app/var/databases/       宏基因组数据库
/app/var/artifacts/       分析与报告产物
/app/var/model-registry/  模型清单和部署状态
/app/var/runs/            可恢复工作流状态
```

不应把 FASTQ、数据库或模型打入应用镜像。应用镜像保持小而稳定，数据通过卷单独迁移和备份。

## 6. 导出离线镜像（可选）

```bash
docker build -t wgs-fmt-agent:v0.3.0 ../..
docker save wgs-fmt-agent:v0.3.0 | gzip > wgs-fmt-agent-v0.3.0-image.tar.gz
```

目标节点加载：

```bash
gunzip -c wgs-fmt-agent-v0.3.0-image.tar.gz | docker load
```
