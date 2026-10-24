# Word报告正文模板 v4

报告版本health-report-v4，正文模板word-native-1-14-v2。
四份只读Word原稿保存在docs/report_templates；SHA-256记录于reporting/word_contract.json。
DOCX的填写说明仅作为模板数据，不作为执行指令，也不进入受检者报告。

原第03—16章改为1—14，保留58个小节、52个结果表、21个图表和12个流程图。
三组并排图合并为面板，最终30个模板PNG。章节、图表、目录和交叉引用同时重编号。

Letter纸张，左右18.2915、上15.9985、下15.24毫米。
章标题23pt/#3465A4，小节16pt/#EA7500，正文11pt，表格10pt。
表头#E2EDF0，交替行#F6F8F9，边框#D9D9D9；评分值保留蓝色大字。
图表色板#246A73/#4A86A4/#8AB8C2/#B5D2CD/#C6B694/#E7E9EC。
流程框和箭头的位置与颜色从DrawingML编译。

scripts/compile_report_word_templates.py使用带lxml的Python重新编译原稿。
Word图表的示意数值不进入运行时。word_template.py按原稿正文、字段和顺序填入结果；
template_body.py仅作为已验证的检测数据适配器，旧逐主题正文不再作为输出模板。
word_figures.py按实际数据生成原稿对应的堆叠条、横条、成对横条、散点、圆环与流程图。
没有数据时保留图位，显示未提供/未启用，不能沿用示意比例。

模型使用word_sections中的word.章节.小节，按writing_focus填充Word解读位置，通常一至两句。
标题、图表、数值和编号由程序生成。跨小节总结的证据范围对应原稿。
引用、支持摘录、事实边界、失败回退继续校验；固定说明行不触发模型。
建议只在第14章行动小节生成，并对应已有证据。

原sections中11组66个稳定证据主题继续用于知识图谱和文献分组。
继续调用原graph_markdown与render_bibliographies，不改变图谱节点/关系/配色和文末文献。
之前的图谱多行文字修复保留。实际正文结构在presentation.chapters，模板图及数据在word_figures。

新章节：1组成，2多样性/生态功能，3重点菌，4菌株/毒力，5耐药/元件，6古菌/真菌/DNA病毒，
7底物/营养代谢，8代谢物功能潜力，9宿主互作，10肠脑轴/内分泌，11症状/问卷，
12疾病关联/经验证模型，13专项转化，14综合解读/行动。
原可选模块键保持兼容，全部复用已有分析结果，不启动新生信任务。

宿主与元件连接各自需要明确支持和序列证据。贡献分母不完整不计算占比。
P5/P95不推算中位数；不同功能分位数不相加；生成、利用和浓度不互相代用。
diversity.ordination/enterotype_ordination需要method及points，点含有限x/y、group、is_sample；
必须同时有样本和参考点才绘图。评分圆环需要scale_min/scale_max，以及验证、适用性、版本、量尺和依据。

开头保留目录，总览最多5条有证据支撑且值得优先关注/复核的发现，不枚举缺失项目。
PDF/Markdown/结构化报告/证据/图片先完整生成后发布，失败保留旧报告。
网页与PDF共用图片，文件名按内容寻址。

验证：原报告全套回归，33个图形完整性，Word字段，无数据/QC，反应方向/单位，模型新协议，
相同占位段落防串章，知识图谱/文献保持，实际PDF生成、逐页检查与前端构建。

正式API/Web由root运行，服务所有者执行：

    cd /home/zhanghaiyang/fmt-healthcare-agent
    sudo bash deploy/activate-report-templates.sh

该脚本验证新暂存构建，备份旧Web，构建并重启API/Web；构建失败恢复旧Web，不停止生信工作进程。
已经生成的旧报告保持不变，重新生成后应用新正文。
