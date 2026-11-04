# 第 4 章：菌株 marker 与毒力参考序列分析

实现日期：2026-11-04。项目：`/home/zhanghaiyang/fmt-healthcare-agent`。

## 已实现

- `src/wgs_agent/pipeline/strain_virulence.py`：两个独立节点、输入完整性与指纹校验、并发锁、原子产物、失败状态和缓存失效。
- 菌株节点调用现有 MetaPhlAn 与 sample2markers，输出有质量门槛的 marker 共识记录、marker 数和可判定位点。**本版不把 marker 共识当成已确定的菌株名、MLST ST 或完成的参考菌株比较。**
- 毒力节点调用 Bowtie2，对 VFDB core 核酸参考序列做匹配和覆盖统计；过滤低质量、未知 MAPQ、次级、补充及已标记重复比对，区分达到门槛的匹配和低于门槛的候选。删除与跳跃位置不增加覆盖广度，完全相同的参考序列合并为带别名的参考组。
- 报告加载规范化产物，刷新旧分析 JSON，并防止旧模块覆盖新结果。状态区分未运行、运行中、输入/数据库/工具缺失、覆盖不足、失败和成功。
- worker 在基础流程完成及缓存命中时均调用新增节点；样本状态接口返回 `chapter_four` 状态。
- 没有独立序列关联证据时不声明基因宿主。具体宿主归属和完整菌株分型仍需要组装、参考比较等额外证据。

## 当前验证结果

- 新增模块测试：20/20 通过。
- 真实工具合成数据测试：Bowtie2 建索引、比对、解析均完成；3 条已知匹配 reads 产生 1 个预期检出参考组。
- Python/Bash 语法、目标文件 Ruff 和 `git diff --check` 均通过。
- 相关回归：56 通过、9 失败；9 个失败用修改前备份代码复测均复现。具体失败名称另见本次交付说明。
- 生产 API 只读健康检查返回 200。

遵照用户选择，本次未使用 root，未补跑 `test2`、`test_complete_data`，未更新真实报告，未重启 API。当前服务进程可能仍缓存旧 Python 代码；磁盘代码已经更新，完整启用需由有权操作该服务的账号加载新版本。

## 已准备的数据库

VFDB core 位于：

```text
/home/zhanghaiyang/fmt-healthcare-agent/fmt-databases/vfdb/VFDB_setA_nt.fas.gz
```

下载自官方 HTTPS 地址，已通过 gzip/FASTA 校验，含 4,891 条参考记录，合并为 4,889 个完全相同序列去重组。旁边的 `.source.json` 记录下载时间、来源与 SHA-256。已有数据库不会被下载脚本静默覆盖。

准备脚本：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
PYTHONPATH=/home/zhanghaiyang/fmt-healthcare-agent/src \
  /home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python -B \
  /home/zhanghaiyang/fmt-healthcare-agent/scripts/prepare_vfdb.py \
  --output /home/zhanghaiyang/fmt-healthcare-agent/fmt-databases/vfdb/VFDB_setA_nt.fas.gz
```

## 后续由有权限的运行账号补跑

普通项目账号当前无法读取两个样本的 `clean_merged` 与上传文件。以下命令仅作为后续执行说明，本次没有执行：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
PYTHONPATH=/home/zhanghaiyang/fmt-healthcare-agent/src \
  /home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python -B \
  -m wgs_agent.pipeline.strain_virulence \
  --sample-id test2 \
  --output-root /home/zhanghaiyang/fmt-healthcare-agent/var/bioinformatics \
  --reads /home/zhanghaiyang/fmt-healthcare-agent/var/bioinformatics/clean_merged/test2.dehosted.fastq.gz \
  --db-root /home/zhanghaiyang/fmt-healthcare-agent/fmt-databases \
  --tax-bin /home/zhanghaiyang/fmt-healthcare-agent/var/runtime/envs/fmt-tax/bin \
  --threads 4
```

第二个样本将 `test2` 替换为 `test_complete_data`。该命令会先完整读取 FASTQ，校验格式、gzip 完整性、读段数和输入指纹，再运行两个节点。无需重新上传或重跑基础质控与功能分析。随后在加载新版本代码的报告服务中重新生成报告；旧分析文件会补齐两个模块。

规范化产物：

```text
/home/zhanghaiyang/fmt-healthcare-agent/var/bioinformatics/profiles/strains/{sample_id}.json
/home/zhanghaiyang/fmt-healthcare-agent/var/bioinformatics/profiles/virulence/{sample_id}.json
```

退出码 0 表示两个节点均完成或 marker 覆盖不足已明确记录；退出码 2 表示至少一个节点未完成。查看 JSON 中的 `status`、`reason_code`，不能把退出码 2 或缺失产物解释为未检出。

可用参数：`--force`、`--vfdb`、`--marker-db`、`--min-vf-reads`、`--min-vf-breadth`、`--min-vf-identity`、`--min-strain-markers`。默认筛查阈值为 reads≥3、覆盖广度≥80%、身份率≥90%、MAPQ≥20；它们是可复现的筛查门槛，尚未进行临床验证。菌株 marker 共识采用显式的覆盖与质量参数，不进行菌株名称推定。

## 验证与回滚

新增测试命令：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
PYTHONPATH=/home/zhanghaiyang/fmt-healthcare-agent/src:/home/zhanghaiyang/fmt-healthcare-agent/tests \
  /home/zhanghaiyang/fmt-healthcare-agent/.venv/bin/python -B -m unittest \
  discover -s /home/zhanghaiyang/fmt-healthcare-agent/tests \
  -p test_chapter_four_pipeline.py
```

修改前的 7 个既有文件保存在：

```text
/home/zhanghaiyang/fmt-healthcare-agent/tmp/chapter4-backup-20261104T013258Z
```

后续对新增文件的修正另有 `chapter4-followup-*` 备份。若需回滚，先核对工作区中本次之后的修改，再按相对路径恢复最初备份中的 7 个既有文件；新增源码与测试文件由本次代码包清单列出。不要对整个工作区执行 reset 或递归删除。数据库和真实样本数据不属于源码回滚范围。

方法依据：[StrainPhlAn 官方文档](https://github.com/biobakery/MetaPhlAn/wiki/StrainPhlAn-4)、[VFDB 官方下载说明](https://www.mgc.ac.cn/VFs/download.htm)。
