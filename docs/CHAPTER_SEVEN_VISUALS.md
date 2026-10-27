# 第7章可视化更新

已新增独立模块 reporting/chapter_seven.py；公共文件仅添加第7章接入及专属表格列宽。
7.2：最多3条基因—菌—酶链路；缺CAZy时明确标为证据整理流程。
7.3：合成/降解分面条形图；样本与同一代表通路参考中位数比较，区间单独画P5–P95。不合计重叠通路，不从P5/P95推算中位数。
下方每类仅列前3种贡献菌（中英双语）及最多5项已检出基因/家族。不根据通路名或菌种常识补造基因。
7.4：最多5种菌、6条通路，只依据样本分层贡献连线。

现有test2和test_complete_data输入均未提供CAZy、检出基因明细、同口径功能参考人群数据；相应位置明确留空。
参考比较选用同一代表通路，不以分类学健康人群参考或实测代谢物浓度替代功能参考。

专项测试11项通过，ruff通过；扩大回归72通过、3项失败，3项在撤去本次接入后的隔离副本均能复现。
两份完整预览在 tmp/chapter7-preview/<sample_id>/。
已验证7.2–7.4之外Markdown逐字保持，另一个Codex的第三章修改未覆盖。

当前SSH用户不能读取root所有的正式报告或使用免密root sudo，尚未覆盖var/results内正式文件。
待有权限的会话统一发布（可等待第3/8章编辑完成）：

    cd /home/zhanghaiyang/fmt-healthcare-agent
    sudo .venv/bin/python scripts/refresh_chapter_seven.py test2
    sudo .venv/bin/python scripts/refresh_chapter_seven.py test_complete_data

脚本使用现有报告锁，备份旧报告，暂存PDF成功并确认所有原文件未被并发改写后才发布；不调用模型、不重跑生信、不修改第7.2–7.4以外正文。
如果API进程已缓存旧代码，后续“重新生成报告”需由服务管理者在其他章节工作结束后统一重载API；现有报告只刷新文件无需重启。
