# 肠道菌群 → 疾病 孟德尔随机化权重

`disease_mr_weights.json` 是消费者版“疾病风险评估”唯一读取的权重文件，由
`scripts/import_disease_mr.py` 从产品提供的两张表生成：

- `菌_MR_评分.xlsx`：肠道菌群性状（菌种/菌属/科…丰度或有无、功能通路、α多样性）对
  FinnGen R13 共 102 个终点的两样本 MR（IVW）结果，160,338 行；
- `疾病分类表_已注释.xlsx`：FinnGen 终点的官方英文名、中文名和所属系统。

源表的 sha256 和行数记录在 JSON 的 `source` 字段，源表本身不入库。

## 纳入规则（默认）

- IVW P < 0.05；
- 只用**丰度**类性状：菌种丰度、菌属丰度、α多样性（香农、丰富度、逆辛普森）。
  公式要乘以标准化丰度 z，有/无（presence）类性状没有这个量，功能通路与本平台
  的通路注释口径不同，均未纳入；
- 每条保留原始性状名、β、P、−lgP，评分可逐项复核。

结果：102 个终点、3,758 条性状，每个终点 17–73 条（中位 36）。

## 评分

    score = Σ β × (−lgP) × z

z 为该性状在样本中的值相对 cMD 健康成人的标准分：菌种/菌属取
log10(相对丰度% + 0.001)，α多样性取原值；截断在 ±4。性状名是 GTDB 命名，
样本谱是 MetaPhlAn 3（NCBI 命名），对照表见 `src/wgs_agent/reporting/disease_risk.py`
的 `MPA_TO_GTDB` / `MR_ALIASES`；对不上的性状不计入，每个疾病记录实际用到的证据权重占比。

## 更新

```bash
.venv/bin/python scripts/import_disease_mr.py --mr 菌_MR_评分.xlsx --diseases 疾病分类表_已注释.xlsx
```

输出是确定性的（同样输入得到同样字节）。服务器上的参考包目录名带本文件哈希，
提交新文件并 `bash deploy/restart.sh` 后会在后台自动重建，旧包保留不动。
