# 第12章：专项代谢转化功能

## 工作流

2026-11-04新增专项流程：现有HUMAnN UniRef基因家族谱 → 本地EC映射及经过核实的实验参考蛋白同簇标记 → 饮食底物/药物背景/验证阶段三组结果 → 分析JSON、证据、网页与PDF。
不重跑FASTQ质控、去宿主、MetaPhlAn或HUMAnN。新上传样本在完成HUMAnN后自动运行；完成过的样本可单独回填。

原报告只有specialized_metabolism展示适配器，没有生成步骤。旧的通用EC流程严格要求每条记录均符合UniRef格式；真实样本在第149980行遇到不符合要求的标识而失败。
新专项流程不接受或暴露这些原始标识，只隔离条目并记录分类计数。若输入存在隔离记录，整体状态为partial，不从未匹配结果推出功能阴性；合规UniRef记录保留原单位和数值。

## 首批10项参考面板

饮食底物：

1. 单宁酯键水解：EC3.1.1.20。
2. 酯化阿魏酸释放：EC3.1.1.73。
3. 没食子酸脱羧：EC4.1.1.59。
4. β-葡萄糖苷水解背景：EC3.2.1.21；不作为异黄酮专一转化证明。
5. daidzein→equol实验参考蛋白同簇标记组：DZNR、DHDR、THDR。

药物背景：

1. β-葡萄糖醛酸结合物去结合背景：EC3.2.1.31。
2. 芳香偶氮键还原背景：EC1.7.1.6、EC1.7.1.17，分开记录本地参考覆盖。
3. 左旋多巴相关脱羧家族背景：EC4.1.1.25；不确认本样本的药物底物活性。
4. 地高辛Cgr2：实验参考蛋白C8WLM1及其UniRef90簇。
5. 地尔硫卓BT_4096：实验参考蛋白Q8A0C5及其UniRef90簇，不用一般GDSL酯酶代替。

## 证据规则

- EC定义来自IUBMB；本地HUMAnN映射逐项检查，缺参考不写成未检出。
- 实验标记的UniRef归属于2026-11-04经UniProt官方接口核实。特异参考簇只对UniRef90输入启用，UniRef50不作等价替代。
- equol旧KO映射没有K26069/K26070/K26071；补充的是实验参考蛋白同簇面板，不是完整通路或equol生产者判定。
- DHDR参考蛋白所在簇也含其他功能注释，故保留shared_function_cluster标记；DDRC、辅因子、菌株连接和底物专一性未验证。
- 同一EC面板对重叠基因取并集；跨面板不相加。equol多步标记各自报告，不加成一个通路丰度。
- 丰度保留HUMAnN原单位，未重新归一化。分层贡献是HUMAnN指派，不证明菌株宿主或物理连接。
- 无对应标记时保留未报告/未评估，不补零。无用药记录时不推断药物暴露、疗效、毒性或剂量。
- 样本QC失败时隐藏专项丰度及解读。

主要来源：

- IUBMB Enzyme Nomenclature：https://iubmb.qmul.ac.uk/enzyme/
- equol：DOI 10.1128/AEM.01101-10；10.1159/000335049；KEGG M00966。
- 左旋多巴：DOI 10.1126/science.aau6323。
- Cgr2：DOI 10.7554/eLife.33953；UniProt C8WLM1。
- BT_4096：DOI 10.1038/s41586-019-1291-3；RCSB PDB 7BR2 / UniProt Q8A0C5。

## 运行与回填

    .venv/bin/python -m wgs_agent.pipeline.specialized_metabolism --sample-id SAMPLE --output-root var/bioinformatics --mapping-dir fmt-databases/humann3/utility_mapping
    .venv/bin/python scripts/refresh_specialized_metabolism.py --sample-id SAMPLE --check
    .venv/bin/python scripts/refresh_specialized_metabolism.py --sample-id SAMPLE

回填持有样本与报告锁，备份原分析并原子发布，保留其他章节和手动提供的专项结果。缓存同时核对输入文件、单位、目录版本和参考映射指纹。
API由root运行的部署可执行：

    sudo bash deploy/activate-specialized-metabolism.sh test_complete_data

随后由正常报告生成入口重建正式报告。原Word第13章内部ID保持稳定，公开编号仍为第12章。

## test_complete_data 实际回填结果

已从原HUMAnN输出读取171781个规范UniRef家族。隔离2条非标准UniRef标识，未向报告或模型暴露原值。状态为partial，保留输入不完整标识。

- β-葡萄糖苷水解背景：家族丰度0.0002189531614 relative_abundance；98个UniRef家族。
- 葡萄糖醛酸结合物去结合背景：家族丰度8.86768182e-05 relative_abundance；26个UniRef家族。
- 芳香偶氮键还原背景：家族丰度3.87844e-06 relative_abundance；1个UniRef家族。

其余项目未取得对应注释支持，不补零、不作功能阴性判定。equol标记0/3、Cgr2标记0/1、BT_4096标记0/1只描述当前谱中的匹配结果，不表示生物学功能缺失。
