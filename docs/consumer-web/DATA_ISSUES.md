# 数据问题与修复记录

## 1. 丁酸合成显示“核梭杆菌 100%”

**根因**：专业版 `chapter_two.redundancy_rows` 对每个功能类别只选一条代表通路（`丁酸合成` 选中 P163-PWY），而 `cooperation_data` 也按一条通路取贡献菌。P163-PWY 的分层贡献只有核梭杆菌，导致占比显示 100%。

**修复**：消费者版 `consumer_web/functions.py::aggregate_category` 汇总 `CENTFERM-PWY`、`PWY-5676`、`P162-PWY`、`P163-PWY`、`PWY-5022` 等全部已观测通路，按分类单元合并分层贡献；再以重点菌面板补入普拉梭菌、罗氏菌等已知产丁酸类别成员，并在正文中说明分层注释覆盖有限。

**测试**：`tests/test_consumer_functions.py::test_butyrate_aggregates_all_pathways_not_one_representative`。

**后续事项**：专业版仍保留单通路选择；未修改专业版输出，后续可在 `reporting/chapter_two.py` 统一到同一聚合口径。

## 2. 乳酸利用为空

**根因**：样本只有 `PWY-8086`（(S)-lactate fermentation to propanoate, acetate and hydrogen）的 community 行，没有分层贡献行；`contributor_summary` 返回 missing，旧实现因此显示为空。样本中罗氏韦荣球菌占 24.8%，但 HUMAnN 分层输出没有给出它的该通路贡献。

**修复**：消费者版保留“通路已检出”，在缺少分层时用菌种特性补充韦荣球菌等乳酸利用菌，并明确标注为菌种特性推断，不伪造基因分层。

**测试**：`tests/test_consumer_functions.py::test_lactate_without_strata_can_use_taxonomy_fallback`。

## 3. 四类纤维底物为空

**根因**：专业版第 7 章主要依赖 `nutrient_metabolism.fiber` topic，但该 topic 在样本中为 missing；同时没有把底物映射到 HUMAnN 通路/EC，导致四类底物为空。

**修复**：新增 `consumer_substrate_map.yaml`，把抗性淀粉、果胶、菊粉/果聚糖、木聚糖映射到已核对通路和 EC；用 `substrate_evidence` 汇总通路分层和 EC 贡献。菊粉/果聚糖只保留 EC 3.2.1.7，样本无命中，因此显示“本次未检出相关基因”。

**测试**：`tests/test_consumer_functions.py::test_fiber_union_is_shared_by_diversity_and_nutrition`。

**一致性**：`diversity` 第 3 小节和 `nutrition` 卡片都调用同一个 `fiber_union`，两处贡献菌并集一致。

## 4. 普拉梭菌未进入丁酸通路分层

**根因**：样本 HUMAnN 的丁酸相关通路分层中没有普拉梭菌，只有 P163 的核梭杆菌；这是分层输出覆盖限制，不是消费者版计算错误。

**修复**：正文在丁酸阶段和代谢产物卡片中使用重点菌类别成员补充普拉梭菌、罗氏菌，同时保留“分层注释覆盖有限”的事实；不把类别成员写成实测通路贡献。

## 5. 肠毒素 ST 不在参考集

**根因**：VFDB setA 中未确认 `estA` 参考序列。

**修复**：面板条目标记为未覆盖，正文不输出“未检出”，登记 omissions；`unverified` 记录见 `MAPPING_AUDIT.md`。

## 6. 图子集清洗后不足两条边

**根因**：多个 topic 原始子图只有研究分组、探针、编号或“位于”关系；清洗后只剩 0–1 条边。

**修复**：按规则隐藏该子图并登记 omissions，不输出无证据图。可用的子图集中在组成、多样性分工、重点菌、营养、代谢产物和更多线索。
