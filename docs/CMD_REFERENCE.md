# curatedMetagenomicData 健康参考

`WGS_HEALTHY_REFERENCE_PROVIDER=cmd` 使用独立的 cMD3 对照谱，替换原 MHNO 健康比较。主分析的 Jan25 物种谱、HUMAnN 与其他专项结果保留。

本机首版参考：3,537 名成人、29 项研究、984 个物种。来源为数据库目录中的 cMD 3.19.1 资源目录，以及此前从官方 cMD 3.14.0 源码包导出的 22,588 条元数据快照；选择结果由输入内容哈希固定。实际丰度矩阵由官方 ExperimentHub 资源目录解析后下载，来源 ID、URL、字节数和 SHA-256 保存在 manifest 中。

纳入条件为粪便、年龄≥18、`disease=healthy`、`study_condition=control`、`antibiotics_current_use=no`；排除明确妊娠或哺乳者。先验证完整物种矩阵，再按“研究+个体”选最早合格时间点。未知用药或年龄不纳入；未知妊娠/哺乳不当作已确认否定。没有额外限定 BMI，healthy 是原研究标签，不等于临床正常或合格供体。元数据和丰度格式检查不能代替全部原始测序 QC。

参考为 MetaPhlAn3 发布谱。每个待测样本用固定 MetaPhlAn 3.0.14、v30 数据库生成独立谱，并与参考一起按已分类物种总和归一化至100%。来源没有每份谱的精确软件小版本，报告保留该限制，比较标为探索性；不把 Jan25/SGB 主分析直接投射为 cMD 参考值。

当前目录：

```text
/storageB/zhanghaiyang/fmtha-data/var/reference/cmd/native-v3/
    manifest.json
    metadata.tsv
    species_abundance.tsv
/storageB/zhanghaiyang/fmtha-data/var/reference-targets/cmd/<SAMPLE>/
    profile.tsv
    provenance.json
    comparison.json
    run.log
/storageB/zhanghaiyang/fmtha-data/fmt-databases/metaphlan3_cmd/
/storageB/zhanghaiyang/fmtha-data/var/runtime/vendor/metaphlan-3.0.14/
```

配置使用 `WGS_CMD_REFERENCE_DIR`、`WGS_CMD_PROFILES_DIR`、`WGS_CMD_VENDOR_DIR`、`WGS_CMD_DATABASE`；`WGS_CMD_AUTO_PROFILE=true` 自动准备独立谱。新上传及主流程缓存恢复均经原健康比较入口分派到 `cmd_workflow`。报告渲染本身只读本地谱，不启动比对或网络下载。

对已有样本补算：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
set -a
source .env
set +a
PYTHONPATH=src .venv/bin/python -m wgs_agent.pipeline.cmd_workflow \
  --sample-id SAMPLE --threads 4
```

随后重新生成报告。样本质控失败、参考文件或哈希错误、缺少独立谱、数据库不符、排除本人后不足30人时，明确报告不可用，不回退到旧人群。完整物种和多样性分布包含零值；P5=P95时不判定高低。经验百分位使用 midrank CDF。

报告排除同名原始样本、同一研究中的同一个体、相交的原始 run；缺乏身份信息时说明无法核验其他编号是否属于同一人。物种和多样性分位数使用全部合格参考，群落 PCoA 为控制计算量使用固定300人的绘图子集，图文分别标明绘图人数和参考总人数。

重新建库采用 `scripts/prepare_cmd_reference.py`，要求明确提供包目录、元数据快照、官方 ExperimentHub SQLite目录、来源缓存和新的输出目录。已存在的版本只验证，不覆盖。官方目录位于 `https://experimenthub.bioconductor.org/metadata/experimenthub.sqlite3`；脚本仅接受白名单中的官方 HTTPS 资源位置。运行时安装过程及下载/校验记录保留在 `var/reference-sources/cmd/native-v3/`，MetaPhlAn安装不改变现有 fmt-tax 包。

服务通过现有 `deploy/runtime.py restart --component workspace-api` 加载更新。历史静态报告需要重新生成才显示新参考；回滚需同时恢复本次源码备份与原环境配置，避免标签和计算来源不同步。
