# 第11章：疾病相关特征与经验证模型

2026-11-04：删除原第11章“症状相关特征与问卷对照”。原12、13、14章公开展示为11、12、13章；目录、小节标题、图注、图片替代文字和综合解读引用同步更新。
原Word源文件及内部证据/图表标识保持稳定，避免历史知识子图、模型小节及缓存图片串章。REPORT_CHAPTERS 是公开目录，CHAPTERS 是源模板索引。

## 空数据的实际原因

- 上传分析和报告输入此前没有生成diseases模块，疾病预测模型也没有载入。
- test_complete_data有完整105项物种谱（MetaPhlAn Jan25），可以复用现有物种丰度进行文献特征注释。
- phenotype_species_stats.csv未在本项目参考目录发现；现有物种健康分位数和MHNO健康对照没有同口径疾病病例/对照数据，不能由它们推出疾病分值。
- 本地curatedMetagenomicData是包源码、样本元数据和资源目录，不能作为已下载且完成同版本处理的疾病队列矩阵。
- 现有FMT triplet模型用途为FMT配对，不能作为疾病预测模型。未发现可执行疾病模型及其特征/预处理定义、独立验证和适用性材料。

## 已补齐的流程

pipeline/disease_features.py从完整有效的百分比物种谱生成可追踪的文献物种关联。标准报告输入、既有分析刷新和正式报告生成均已接入。
默认参考pipeline/disease_associations.json首批覆盖：

1. 结直肠癌：5个跨队列物种标记；Thomas AM et al., Nature Medicine 2019, https://doi.org/10.1038/s41591-019-0405-7 ，正文与Fig.1a。
2. 克罗恩病：3个物种特征；Lloyd-Price J et al., Nature 2019, https://doi.org/10.1038/s41586-019-1237-9 ，Fig.2f/Extended Data Fig.4b。

每条保存实际丰度、文献中的组间方向、DOI、原文定位、研究人群、流程版本和参考摘要。
物种未在谱中报告时保留未定量；不补零、不按子串匹配、不凭缺失推断减少。重复物种、无效值、混合单位和不完整输入均返回明确未评估原因。
该流程只注释已知研究特征，不重跑FASTQ/QC/去宿主/MetaPhlAn/HUMAnN，不计算疾病风险、病例相似度、临床阈值或功能性疾病标记。

## 真实样本结果

test_complete_data：

- 结直肠癌：5项参考物种均未在物种谱报告，未定量。
- 克罗恩病：Faecalibacterium prausnitzii = 0.297421%；Escherichia coli = 7.77107%；Roseburia hominis未在谱中报告。
- 原研究的富集/减少方向与本样本丰度分开显示；本样本未判定同向或反向。
- 模型保持未启用，按预测终点、适用人群、输入定义、外部验证和性能逐项解释缺少内容。

其他疾病类别、疾病功能标记和预测模型需要额外核验参考资料；当前不声称已经覆盖。

## 刷新与维护

正式API重新生成报告时自动补齐该模块，并沿用原有锁与原子发布。手动提供的既有疾病模块和已验证预测记录保持兼容。
独立检查/回填已有分析：

    .venv/bin/python scripts/refresh_disease_features.py --sample-id test_complete_data --check
    .venv/bin/python scripts/refresh_disease_features.py --sample-id test_complete_data

回填脚本备份原分析并持有报告锁；它不重新生成报告。新增疾病参考必须具备原始论文DOI、定位、研究人群、物种和方向。要启用预测模型，还须补充可执行模型、特征/预处理协议及与本样本条件匹配的独立外部验证。
