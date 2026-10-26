# MHOmicrobiome 自动对照

当 `WGS_HEALTHY_REFERENCE_PROVIDER=mho` 时，上传和批处理 worker 自动调用独立 MetaPhlAn 4.2.2 支线，并保存健康人群比较。主分析继续使用原环境。默认启用，可用 `WGS_MHO_AUTO_PROFILE=false` 暂停自动准备；报告仍可读取已有谱。

自动流程复用主流水线保留的去宿主 FASTQ。每次准备检查公共参考、实际软件版本、完整目标谱、输入内容 SHA256 和分析配置。有效谱直接复用；输入或分析配置改变时重新计算。参考版本或人口学元数据变化时只重新比较。手动生成的旧谱仅在运行记录中的输入路径、大小和 mtime 仍一致时接管，之后记录内容摘要。

产物位于配置的 `WGS_MHO_PROFILES_DIR`：

- `<SID>/profile.tsv`、`provenance.json`、`run.log`：与原报告读取器兼容。
- `<SID>/comparison.json`：自动计算的物种及多样性对照。
- `.workflow/<SID>.json`：独立任务状态及失败原因。
- `.history/<SID>/<版本>`：替换前的目标谱。

目标目录通过 Linux `renameat2` 原子交换更新；不支持该操作时保留原结果并报告失败。样本锁防止重复计算和处理期间删除。删除样本会清理其独立谱、任务状态及历史版本，公共参考不受影响。

API 的 workflow 响应增加 `healthy_reference`（state、ready、reason、n_subjects）和 `artifacts.healthy_reference`。主分析完成与对照可用分别记录，独立支线失败不会抹掉已完成的主分析。现有报告生成器继续校验并读取该样本的兼容谱，使用最新分析元数据，缺失的身份/匹配字段可取准备时保存的元数据。

worker 的“已完成”路径也会调用该步骤，所以已有 done 不再阻止补齐对照。管理员可执行一次回填，处理所有仍保留去宿主 FASTQ 的有效样本；依次运行，避免无控制并发。

gpu02 首次激活（API 与去宿主文件当前归 root）：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
sudo bash deploy/activate-mho-automatic.sh
```

激活脚本检查参考和实际 4.2.2 环境，重启 API，然后启动历史样本回填。再次执行会复用仍运行的回填任务。激活日志和回填日志留在服务器 `var/logs/`，脚本仅输出固定状态。

单独准备一个样本：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
PYTHONPATH="$PWD/src" .venv/bin/python -m wgs_agent.pipeline.mho_workflow ensure \
  --sample-id SAMPLE_ID --output-root "$PWD/var/bioinformatics"
```

独立回填：

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m wgs_agent.pipeline.mho_workflow backfill
```

使用能够读取去宿主文件的服务账号运行。参考库仍需一次性正确安装；本功能不自动更换参考队列、降低人数门槛或伪造缺失的人口学字段。当前比较包括完整物种分布和丰富度、Shannon、Simpson、Pielou，功能通路不在此参考包范围内。

可选配置：`WGS_MHO_THREADS`、`WGS_MHO_PYTHON`、`WGS_MHO_METAPHLAN`、`WGS_MHO_TOOL_BIN`、`WGS_MHO_DATABASE`。未设置时使用项目 `.venv`、`ENV_ROOT/mho-tax`、`ENV_ROOT/fmt-tax` 和 `DB_ROOT/metaphlan4`。
