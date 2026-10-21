# FMT triplet model: paper-level evaluation summary

## Validation design

- Dataset: 66 complete, labeled recipient–donor–post-FMT triplets.
- Validation: five-fold patient-level cross-validation; every response probability shown here is out-of-fold.
- Uncertainty: 2,000 patient-level bootstrap resamples.
- Comparator: fixed CLR-distance baseline. This is not the historical `contrastive_model.pt`.

## Response prediction

| Metric | Pooled OOF estimate | Bootstrap 95% CI |
|---|---:|---:|
| Accuracy | 0.697 | 0.591–0.803 |
| Balanced accuracy | 0.727 | 0.611–0.836 |
| Sensitivity | 0.644 | 0.510–0.784 |
| Specificity | 0.810 | 0.625–0.958 |
| F1 | 0.744 | 0.630–0.842 |
| MCC | 0.423 | 0.207–0.633 |
| ROC-AUC | 0.800 | 0.684–0.911 |
| PR-AUC | 0.888 | 0.789–0.967 |
| Brier score | 0.207 | 0.135–0.284 |

The arithmetic mean of the five fold-level ROC-AUC values is 0.838, and the mean fold-level PR-AUC is 0.916. These differ from pooled OOF ROC-AUC and PR-AUC because fold sizes and score distributions differ; pooled OOF values are used for the main ROC and PR figures.

## Donor retrieval

| Metric | Triplet model | Fixed baseline |
|---|---:|---:|
| MRR | 0.339 | 0.219 |
| Mean rank | 10.24 | 15.70 |
| Recall@1 | 0.212 | 0.121 |
| Recall@3 | 0.379 | 0.197 |
| Recall@5 | 0.424 | 0.303 |
| Recall@10 | 0.576 | 0.455 |

The paired bootstrap MRR improvement is 0.120 (95% CI 0.042–0.197).

## Engraftment analysis

The response-associated engraftment comparison gave Mann–Whitney p=0.0557 and rank-biserial effect size r=0.295. This is suggestive but does not pass a two-sided 0.05 threshold.

## Interpretation constraints

This is a small, retrospective, multi-project internal validation. Disease, project, geography, treatment protocol, sequencing batch, and response definition may be confounded. These results support continued algorithm development but are not standalone evidence of clinical utility. External project-level validation and comparison with the historical trained contrastive model remain required.
