# 映射文件核对表

核对依据：本地 HUMAnN3 `utility_mapping/map_level4ec_uniref90.txt.gz`、样本 `pathabundance_relab.tsv`、VFDB `VFDB_setA_nt.fas.gz`。不存在的 ID 不参与计算。

## 底物 `knowledge_base/consumer_substrate_map.yaml`

| 底物 | 通路 | 核对结果 |
|---|---|---|
| 抗性淀粉/淀粉 | PWY-6731 | verified：样本输出可见 |
| 抗性淀粉/淀粉 | PWY-6737 | **unverified**：样本未观测，候选未参与 |
| 果胶 | GALACTUROCAT-PWY | verified：样本输出可见 |
| 果胶 | PWY-6507 | verified：样本输出可见 |
| 果胶 | GALACT-GLUCUROCAT-PWY | verified：样本输出可见 |
| 菊粉/果聚糖 | 无通路 | 仅用 EC 3.2.1.7；样本无命中 |
| 木聚糖 | PWY-6901 | verified：样本输出可见 |
| 木聚糖 | PWY-7294 | verified：样本输出可见 |

酶：

| EC | 核对结果 |
|---|---|
| 3.2.1.1 | verified：utility_mapping 有映射，样本有命中 |
| 3.2.1.41 | verified：utility_mapping 有映射，样本有命中 |
| 4.2.2.2 | **unverified**：样本无命中，未确认本地参考覆盖 |
| 3.2.1.15 | **unverified**：只有酵母命中，不作为果胶证据 |
| 3.2.1.7 | verified：utility_mapping 有映射，样本无命中 |
| 3.2.1.8 | verified：utility_mapping 有映射，样本有命中 |
| 3.2.1.37 | verified：utility_mapping 有映射，样本有命中 |

**unverified 条目：3**（PWY-6737、EC 4.2.2.2、EC 3.2.1.15）。

## 维生素 `knowledge_base/consumer_vitamin_map.yaml`

B1（THISYN-PWY、PWY-6895、PWY-6897、PWY-6892）、B2（RIBOSYN2-PWY）、B3（PYRIDNUCSYN-PWY、PYRIDNUCSAL-PWY、PWY-7761、NAD-BIOSYNTHESIS-II）、B5（PANTO-PWY、PANTOSYN-PWY）、B6（PYRIDOXSYN-PWY、PWY0-845）、B7（BIOTIN-BIOSYNTHESIS-PWY、PWY-5005）、B9（FOLSYN-PWY、PWY-6612、1CMET2-PWY、PWY-3841）、B12（COBALSYN-PWY）、K2（PWY-5838、PWY-5840、PWY-5845、PWY-5850、PWY-5896）均在样本 `pathabundance_relab.tsv` 中可见。**unverified：0**。

注意：B12 的 COBALSYN-PWY 是 salvage 路线，不是完整从头合成；正文写作“具备合成潜力”，未写成“人体已获得足够维生素”。

## 毒力面板 `knowledge_base/consumer_virulence_panel.yaml`

VFDB 参考集核对：

- 志贺毒素 stx1/stx2：参考集中有 stx1A/B、stx2A/B、stxA/B。
- 紧密黏附素 eae：参考集中有 eae。
- 脆弱拟杆菌毒素 bft：参考集中有 bft-1。
- 艰难梭菌毒素 tcdA/tcdB：参考集中有 toxA/toxB。
- 艰难梭菌二元毒素 cdtA/cdtB：参考集中有 cdtA/cdtB（Clostridium difficile 630）。
- colibactin clb：参考集中有 clbA–clbS。
- cnf1、hlyA、ipaH、eltA、cpe：参考集中可见。
- 肠毒素 ST estA：**本次参考集中未确认**，正文不输出“未检出”，只登记 omitted。

**unverified 面板条目：1**（estA）。样本实际检出：tcdA（toxA）和 cdtA/cdtB。

## 药物类别 `knowledge_base/consumer_drug_classes.yaml`

13 个类别：四环素类、β-内酰胺类、碳青霉烯类、大环内酯类、林可酰胺类、氨基糖苷类、氟喹诺酮类、磺胺类、甲氧苄啶、糖肽类、多黏菌素类、氯霉素类、链阳菌素类。机制均来自任务给定的英文到中文映射。**unverified：0**。

## 重点菌与行动

- `consumer_key_taxa.yaml` 8 个类别：4 个 helpful、4 个 watch；成员均带 rank、aliases、term_id 或 watch_note。
- `consumer_actions.yaml` 6 条规则；每条有 finding_code、because、title、how、examples；不含药品/益生菌/补充剂。
