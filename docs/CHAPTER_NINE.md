# 第 9 章诊断与实现记录

项目：gpu02 `/home/zhanghaiyang/fmt-healthcare-agent`。核验日期：2026-11-04。

结论：主要问题是缺少专用的特征提取与报告绑定，另有部分输入证据确实缺失；无需为已有通路重跑整套生信分析。

## 已核实的根因

1. 报告已有 HUMAnN 通路丰度及物种分层贡献，但生态主题仅按 `mucin`、`inflammation`、`barrier` 等通用词匹配，漏掉具体底物和结构合成名称。
2. 第 9 章没有独立解析器；9.1 流程图依赖维度文字匹配，9.3 只读取旧主题命中，9.4 主要是固定跨章提示，没有完整绑定样本证据。
3. 两个现有样本的分析输入均没有 `functional_modules`。因此无法从当前报告输入获得经注释的黏液切割酶、细菌素、鞭毛蛋白和氧化应激基因证据。没有相关注释不等于功能不存在，也不能证明原始测序数据不包含相关基因。

## 数据支持范围

|现有样本|通路总数|底物利用|发酵|lipid A合成|肽聚糖相关|宿主糖链相关单糖利用|
|---|---:|---:|---:|---:|---:|---:|
|test2|53|1|2|0|2|0|
|test_complete_data|349|13|10|1|4|4|

这些列存在交叉，不能相加作为功能总量。完整样本原先漏掉的关键记录包括 `P441-PWY`、`GLCMANNANAUT-PWY`、`FUC-RHAMCAT-PWY`、`FUCCAT-PWY` 和 `KDO-NAGLIPASYN-PWY`。

## 已完成的实现

新增 `src/wgs_agent/reporting/chapter_nine.py`：提取九类功能线索，更新生态主题证据，输出 `chapter_nine_results`，接入第 9 章正文、表格、流程图和报告文档构建。每条结果保留原证据编号、通路编号、单位和贡献菌；单糖利用与黏液切割酶分开；不以物种丰度替代基因证据，不合并重叠通路计分，并遵循原报告的中英文质控状态。

接入文件：`document.py`、`template_body.py`、`word_template.py`、`word_figures.py`。新增测试：`tests/test_chapter_nine.py`。修改前副本保存在 `tmp/chapter9-work/code-backup-*`。采用局部变更和并发内容检查；核对时另一进程对 `Body.resistance` 的更新仍被保留。未提交、重置其他工作，也未重启共享服务或覆盖正式报告。

## 验证与后续策略

14 项新增测试及 6 项 PDF 分页测试通过。现有 65 项相关回归中 10 项失败，在隔离目录恢复本次修改前代码后同样复现，失败集合一致。两个样本均通过生产构建、表格、段落和流程图的离线验证；第 9 章无待填占位符，表格列数和流程图结构有效。

预览：`tmp/chapter9-work/test2_chapter9_preview.md`、`tmp/chapter9-work/test_complete_data_chapter9_preview.md`；对应结构化结果为同目录下的 `*_chapter9_result.json`。正式历史报告需按正常生成流程重新生成；常驻服务若缓存了 Python 模块，需在其他并行章节修改完成后统一重载。

现阶段已使用全部受支持的报告输入。进一步显示具体黏液切割酶等功能，需要保留并接入 HUMAnN gene-family 产物，使用有版本的 UniRef→EC/GO 映射和经筛选的功能标记注释，再提供定量、来源和物种分层信息。真实屏障或炎症结论还需要相应宿主测量，不能由通路补算。

方法依据：[HUMAnN 官方手册](https://github.com/biobakery/humann/blob/master/readme.md)说明其输出为功能潜力、通路/基因家族丰度和物种分层贡献，并提供功能重分组工具；本次只使用现有输出，没有下载新数据库或调用外部模型。
