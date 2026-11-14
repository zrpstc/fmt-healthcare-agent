# cMD-only变更报告

仓库：`/home/zhanghaiyang/fmt-healthcare-agent`（gpu02）。
实际基线：`adc05f6dfec078fe93da117e8787ec7fdf238c6e`，与附件示例42d7eb4不同，以实际git log为准。
初始git工作区干净；分支：`refactor/cmd-only-reference`。修改留在该分支工作区，未commit、未push。

## 1. 变更摘要

- 健康参考仅保留cMD；移除MHO、通用健康包、旧物种总体表和FMT供体多样性回退。
- 新增不可变ProviderSpec及中性比较模块，集中严格加载、身份/分层和统计，并将工具/上传/postfmt直接接入cMD。
- 实施1000次可复现bootstrap、borderline、统一零值状态和参考者越界物种数基线。
- 实施人口学分层、深度记录/提示、研究批次审计、SHA256解析缓存和NumPy紧凑矩阵。
- 更新测试、模板文案和迁移文档；不重建/发布线上参考，不删除存量数据。按用户最新要求暂缓真实样本报告生成和服务重载。

## 2. 文件清单

共54个文件：新增5、改写36、删除13。

| 文件 | 操作 | 说明 |
|---|---|---|
| `/home/zhanghaiyang/fmt-healthcare-agent/.env.example` | 改写 | 清除旧健康来源变量及注释，追加cMD示例；不修改实际.env |
| `/home/zhanghaiyang/fmt-healthcare-agent/README.md` | 改写 | 唯一cMD入口、统计新行为与指南链接；移除ENA/旧来源操作路径 |
| `/home/zhanghaiyang/fmt-healthcare-agent/deploy/legacy/activate-mho-automatic.sh.txt` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/CHAPTER_ELEVEN_DISEASE_FEATURES.md` | 改写 | 将健康参考名称改为cMD；疾病特征内容保留 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/CMD_ONLY_CHANGE_REPORT.md` | 新增 | 本次完整变更、测试基线/最终结果、迁移、性能和人工步骤报告 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/CMD_REFERENCE.md` | 改写 | 完整契约、统计、分层、深度、批次、缓存、参数和变量迁移 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/HEALTHY_POPULATION_CONTROL.md` | 改写 | 收敛为cMD指南入口 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/HEALTH_REPORT_V3.md` | 改写 | 删除旧表/供体回退说明，描述cMD重新生成规则 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/MHOMICROBIOME_REFERENCE.md` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/MHO_AUTOMATIC.md` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/docs/SINGLE_SERVER.md` | 改写 | 区分cMD健康参考和仍用于非健康物种功能的公共目录 |
| `/home/zhanghaiyang/fmt-healthcare-agent/pyproject.toml` | 改写 | NumPy纳入基础依赖，保证中性比较模块可导入 |
| `/home/zhanghaiyang/fmt-healthcare-agent/runtime/scripts/postfmt_pipeline/process_postfmt_sample.sh` | 改写 | 直接调用cmd_workflow，默认cmd，移除MHO环境变量 |
| `/home/zhanghaiyang/fmt-healthcare-agent/scripts/benchmark_cmd_reference.py` | 新增 | 临时3500×1000可复现基准，测冷/热比较和峰值RSS |
| `/home/zhanghaiyang/fmt-healthcare-agent/scripts/build_healthy_reference.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/scripts/healthy_ena.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/scripts/mho_reference.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/scripts/prepare_cmd_reference.py` | 改写 | CLI分层/年龄界限、层人数和深度manifest；保持严格选择和新目录发布 |
| `/home/zhanghaiyang/fmt-healthcare-agent/scripts/runtime_paths.py` | 改写 | shell变量白名单使用WGS_CMD_*，删除MHO变量 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/build_extended_reference.py` | 改写 | 仅删除物种参考；保留原代谢物描述统计功能 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/cmd_export.R` | 删除 | 删除无调用者的旧宽松cMD物种导出入口；官方严格导出/建包保留 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/cmd_workflow.py` | 改写 | 独立持有通用工具、默认cmd、记录FASTQ reads/bases、缓存和输入一致性检查 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/download_public_reference.py` | 改写 | 仅删除物种参考；保留原HUMAnN通路功能 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/mho_workflow.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/report_common.py` | 改写 | 移除旧物种参考常量/判定；保留疾病表公共目录 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/report_data.py` | 改写 | 停止旧CSV/宽表读取与健康阈值计算；主分析丰度保留 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/sample_management.py` | 改写 | 样本文件目录使用cMD，不执行存量数据清理 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/pipeline/upload_workflow.py` | 改写 | 直接查询cMD工作流状态 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/chapter_three.py` | 改写 | 调用统一百分位实现 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/cmd.py` | 改写 | 去除MHO依赖，明确来源小版本未公布和待测精确3.0.14，使用ProviderSpec |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/document.py` | 改写 | cMD置信区间/状态与正文；清除旧来源文案 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/healthy.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/mho.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/overview.py` | 改写 | not_detected与边界不确定使用相同异常规则 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/population_reference.py` | 新增 | ProviderSpec、SHA256缓存、矩阵、身份/分层、统计、深度与批次的统一实现 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/reference.py` | 改写 | 唯一cMD路径、明确不支持状态、清除历史比较及计数 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/reference_labels.py` | 改写 | 默认cMD和共享统计审计正文 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/template_body.py` | 改写 | 中性人口参考表、统一新审计信息 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/word_figures.py` | 改写 | 移除MHO命名，独立cMD谱显示 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/reporting/word_template.py` | 改写 | cMD文案与新统计绑定；未新增DOCX导出 |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_agent/tools/domain_tools.py` | 改写 | compare_reference直接使用cMD、保留不确定性/基线、不可用不等同于0异常，先验证样本ID |
| `/home/zhanghaiyang/fmt-healthcare-agent/src/wgs_fmt_platform/paths.py` | 改写 | 删除旧物种总体表路径发现与回退 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_chapter_two.py` | 改写 | 默认参考名称改为cMD |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_cmd_population.py` | 新增 | bootstrap/边界/越界/零值/分层/深度/研究/类型/缓存/历史/工具回归 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_cmd_reference.py` | 改写 | 保留原cMD覆盖，默认文案改为cMD |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_cmd_workflow.py` | 新增 | cMD工作流读数、缓存失效、身份排除、禁用、直接shell入口 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_healthy_population.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_mho_reference.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_mho_workflow.py` | 删除 | 删除已移除健康来源专属代码、脚本、文档、历史入口或测试 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_overview_chart.py` | 改写 | 独立cMD谱和cMD审计文案 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_overview_reference_v2.py` | 改写 | 改用cMD fixture，保留中位数/检出率覆盖 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_report_module_integration.py` | 改写 | 状态依赖改为cmd_workflow；保留原基线失败 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_report_reference_workflow.py` | 改写 | 替换旧来源测试，覆盖cMD发布/回滚和禁止旧表/FMT回退 |
| `/home/zhanghaiyang/fmt-healthcare-agent/tests/test_uploaded_reports.py` | 改写 | 首份上传报告使用cMD，主分析保持无健康高低判定 |

完整关键词盘点及保留理由另见同目录`reference-inventory.csv`。

用途例外：`download_public_reference.py`还有HUMAnN通路功能，`build_extended_reference.py`还有代谢物功能，故只删除其中物种参考部分。`WGS_REFERENCE_DIR`还服务这些功能和疾病表路径，因此保留其非健康物种用途，健康物种比较已完全断开。

基线项目根目录下的data/reference及species_reference_overall.csv实际已不存在，因此没有额外数据文件可删；相关路径发现代码已删除。全仓遗留名称审查中，前端Next构建产物的mho匹配确认是Unicode实体映射（℧），不是参考provider，未误删构建依赖。旧来源名称仅在迁移说明、历史结果无效化逻辑和回归测试中保留。

未修改FMT配型、疾病文献特征JSON/算法、耐药/MGE、菌株/毒力及其他界专项源文件。旧主分析健康区间不再提供给共享的旧工具；保留这些工具本身的非参考算法。

## 3. 评审改进项

| 编号 | 是否实施 | 实现位置（仓库内路径） | 对应测试 | 未实施原因/限定 |
|---|---|---|---|---|
| 1 | 是 | reporting/population_reference.py::comparison | test_bootstrap_reproducible_and_matches_empirical_resampling；test_borderline_never_high_or_low_and_zero_semantics | 固定种子20261114、1000次；边际经验bootstrap，非联合区间 |
| 2 | 是 | population_reference.py::outlier_baseline；reference_labels.py::audit_summary | test_outlier_baseline_leave_one_out_and_large_approximation | ≤300逐人留一；>300全队列分位数近似留一，明确标注 |
| 3 | 是 | population_reference.py::comparison/abnormal；document.py；overview.py | test_not_detected_and_borderline_agree_in_counts_overview_and_tables | 零且P5>0始终not_detected；同时落边界CI时另置borderline且不计确认越界 |
| 4 | 是 | scripts/prepare_cmd_reference.py；population_reference.py::stratum | test_stratum_below_thirty_never_pools；test_age_boundaries_are_validated_and_inclusive_at_lower_edge；test_builder_cli_parameters_are_forwarded | country/sex/age_band组合；至少30人，不自动合层 |
| 5 | 是 | prepare_cmd_reference.py；cmd_workflow.py::_fastq_depth；population_reference.py::depth_distribution | test_population_audit_depth_studies_and_report；test_target_depth_is_recorded_without_reference_depth_and_legacy_header_is_used；test_cmd_workflow_profiles_counts_reads_and_reuses_valid_artifacts | 旧线上包无深度字段，未重建，因此该包仍提示缺失 |
| 6 | 是 | population_reference.py::compare；reference_labels.py::audit_summary | test_population_audit_depth_studies_and_report | 研究数/每研究人数/丰富度和Shannon中位数范围；不做批次校正 |
| 7 | 是 | population_reference.py::_parse_bundle/compare；prepare_cmd_reference.py | test_numeric_study_and_subject_ids_exclude_self | study_id和subject_id均先str和strip |
| 8 | 是 | population_reference.py::load_bundle/PopulationMatrix；scripts/benchmark_cmd_reference.py | test_hash_cache_reuses_parse_and_invalidates_modified_content | 每次仍计算文件SHA256；同内容不重复解析；缓存最多两包 |
| 9 | 核查完成，保持未公布 | cmd.py::PIPELINE/SOURCE_PROFILER_MINOR_VERSION；docs/CMD_REFERENCE.md | test_exact_target_minor_and_reference_pipeline_validation；官方源码文档数字版本核查 | 官方3.14.0源码DESCRIPTION、NEWS.md、README.md未明确MetaPhlAn 3小版本，未猜测 |
| 10 | 是（结构预留） | population_reference.py::ProviderSpec | test_provider_spec_is_immutable_and_extensible_without_implementing_cmd4 | 本次未实现cMD4，配置入口仅接受cmd |

上述测试主要位于`/home/zhanghaiyang/fmt-healthcare-agent/tests/test_cmd_population.py`、`tests/test_cmd_workflow.py`和`tests/test_cmd_reference.py`。

## 4. 环境变量迁移表

| 变量/参数 | 迁移 |
|---|---|
| WGS_HEALTHY_REFERENCE_PROVIDER | 保留但可选；未设置/空/cmd均使用cMD，其他值明确unsupported_provider并写日志 |
| WGS_HEALTHY_REFERENCE_DIR | 删除；改用WGS_CMD_REFERENCE_DIR |
| WGS_HEALTHY_ENA_DIR、WGS_MHO_* | 删除，不复用旧参考谱 |
| WGS_SPECIES_REFERENCE_FILE | 删除，无旧表回退 |
| WGS_REFERENCE_DIR | 保留，仅HUMAnN通路、代谢物及疾病表目录，不再提供健康物种参考 |
| WGS_REFERENCE_CACHE_DIR | 保留，仅原HUMAnN通路工具缓存 |
| WGS_CMD_REFERENCE_DIR、WGS_CMD_PROFILES_DIR | 保留，分别指定参考包和独立待测谱目录 |
| WGS_CMD_AUTO_PROFILE、WGS_CMD_THREADS | 保留，自动准备开关和线程数 |
| WGS_CMD_PYTHON、WGS_CMD_VENDOR_DIR、WGS_CMD_TOOL_BIN、WGS_CMD_DATABASE、WGS_CMD_SOURCE_DIR | 保留；应用解释器仍是WGS_ENV_ROOT/bin/python，WGS_CMD_PYTHON用于独立profiler |
| WGS_FMT_MATCHING_DIR及其他配型变量 | 保留配型原用途，不再用于健康多样性回退 |
| --stratify-by | 新增，country/sex/age_band可组合 |
| --age-band-boundaries | 新增，默认18 30 40 50 60 70 80，必须从18开始且严格递增 |

`.env.example`已移除旧来源注释并添加cMD示例；实际`.env`未读取原值到模型，也未改写。完整默认路径见CMD_REFERENCE.md。

## 5. 测试结果

| 阶段 | 常规通过 | 失败 | 跳过 | 通过的子测试 | 耗时 |
|---|---:|---:|---:|---:|---:|
| 修改前全量 | 582 | 50 | 2 | 16 | 911.385s |
| 最终前实际仓库定向 | 61 | 0 | 0 | 0 | 132.523s |
| 修改后全量 | 576 | 29 | 2 | 16 | 630.441s |

新增失败：0。
JUnit总事件数含子测试；终端常规测试通过数与子测试通过数分开统计。基线为582常规通过+16子测试通过、50失败、2跳过；先前口头598为合计。
重构后、删除旧来源前，原cMD 9项测试全部通过。第一次扩大定向90项中89通过，唯一失败已在基线；之后发现并修正迁移测试对可选旧字段n_normal的断言，未为基线失败改动无关模块。
最终前实际仓库定向61项全通过，包括cMD统计/工作流、上传、路径以及未修改的疾病特征模块。另有最后补充的工具ID校验用例由最终全量覆盖。
31个修改/新增Python文件编译通过，git diff --check通过；既有3537×984 cMD包通过新加载器严格校验，最低人数仍为30。

基线中原有失败（全部50项，保留作独立基线，不归因于本次修改）：

- `tests.test_agent_execution.test_real_subagent_runs_readonly_and_returns_to_primary`
- `tests.test_chapter_seven.test_concurrent_report_edit_aborts_before_publication`
- `tests.test_chapter_two.test_diversity_figure_contains_both_profiles_and_true_reference_statistics`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[True-WGS_FMT_RESOURCE_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[True-FMT_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[False-WGS_FMT_RESOURCE_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[False-FMT_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_keep_fresh_workspace_defaults`
- `tests.test_graph_presentation.test_unknown_english_fallback_is_hidden_instead_of_leaking_to_image`
- `tests.test_health_report.test_standard_chat_api_generates_topic_text_and_keeps_outline`
- `tests.test_health_report.test_compatible_backend_format_fallback_and_bounded_repair`
- `tests.test_health_report.test_missing_data_and_service_failure_remain_readable_without_model`
- `tests.test_healthy_population.test_subject_filtering_zero_inclusion_percentile_and_idempotence`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[version-incompatible_target_pipeline]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[missing_version-unknown_target_pipeline]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[top_n-incomplete_target_profile]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[bad_total-incomplete_target_profile]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[matching-insufficient_healthy_subjects]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[missing_demographics-missing_matching_metadata]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[missing_file-healthy_reference_unreadable]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[bad_manifest-invalid_healthy_manifest]`
- `tests.test_healthy_population.test_explicit_cohort_never_silently_uses_legacy_or_stale_results[too_few-insufficient_healthy_subjects]`
- `tests.test_healthy_population.test_matching_zero_width_and_tie_percentile`
- `tests.test_healthy_population.test_absent_cohort_species_is_only_zero_filled_for_complete_profiles`
- `tests.test_healthy_population.test_duplicate_feature_aliases_and_duplicate_labels_fail_closed`
- `tests.test_healthy_population.test_healthy_comparison_reaches_all_report_artifacts`
- `tests.test_litkg_full_acquisition.test_acquisition_drains_every_page_and_preserves_all_statuses_and_predicates`
- `tests.test_managed_elasticsearch.StartupScriptTests.test_failure_prevents_web_and_api_start`
- `tests.test_managed_elasticsearch.StartupScriptTests.test_start_prepares_search_before_application_processes`
- `tests.test_managed_elasticsearch.StartupScriptTests.test_status_and_stop_include_elasticsearch`
- `tests.test_report_knowledge_graph.test_graph_contains_only_relevant_actual_claims_and_valid_endpoints`
- `tests.test_report_knowledge_graph.test_missing_results_and_title_only_references_do_not_create_edges`
- `tests.test_report_knowledge_graph.test_malformed_service_payload_does_not_break_report`
- `tests.test_report_module_integration.test_cache_recovery_runs_all_supplements_without_base_pipeline`
- `tests.test_report_reference_workflow.test_existing_analysis_recompared_without_losing_zero_unknown_or_custom_fields`
- `tests.test_report_reference_workflow.test_complete_profile_recovers_top_n_and_retains_sgb_for_diversity`
- `tests.test_report_reference_workflow.test_fraction_unit_and_incompatible_unit`
- `tests.test_report_reference_workflow.test_missing_reference_preserves_input_comparisons_and_provides_audit`
- `tests.test_report_reference_workflow.test_diversity_uses_only_healthy_donors_excludes_self_and_keeps_longitudinal`
- `tests.test_report_reference_workflow.test_regeneration_saves_comparisons_and_matching_hash_to_all_artifacts`
- `tests.test_report_refresh.test_reports_and_downloads_are_not_cached`
- `tests.test_report_templates.test_contribution_concentration_requires_complete_consistent_units`
- `tests.test_single_server.test_shell_config_matches_python_from_other_directory`
- `tests.test_uploaded_reports.test_first_uploaded_report_automatically_compares_existing_reference`
- `tests.test_word_template.test_complete_word_contract_without_example_measurements`
- `tests.test_word_template.test_every_word_field_and_visual_has_a_missing_data_state`
- `tests.test_word_template.test_directions_and_contribution_denominators_remain_separate`
- `tests.test_word_template.test_model_uses_word_subsections_instead_of_legacy_topics`
- `tests.test_word_template.test_empty_template_does_not_request_model_for_fixed_explanatory_rows`
- `tests.test_word_template.test_subunit_abundance_is_visible_and_labels_have_space`

修改后仍失败：

- `tests.test_agent_execution.test_real_subagent_runs_readonly_and_returns_to_primary`
- `tests.test_chapter_seven.test_concurrent_report_edit_aborts_before_publication`
- `tests.test_chapter_two.test_diversity_figure_contains_both_profiles_and_true_reference_statistics`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[True-WGS_FMT_RESOURCE_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[True-FMT_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[False-WGS_FMT_RESOURCE_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_follow_portable_root[False-FMT_ROOT]`
- `tests.test_fmt_triplet_online.test_triplet_resources_keep_fresh_workspace_defaults`
- `tests.test_graph_presentation.test_unknown_english_fallback_is_hidden_instead_of_leaking_to_image`
- `tests.test_health_report.test_standard_chat_api_generates_topic_text_and_keeps_outline`
- `tests.test_health_report.test_compatible_backend_format_fallback_and_bounded_repair`
- `tests.test_health_report.test_missing_data_and_service_failure_remain_readable_without_model`
- `tests.test_litkg_full_acquisition.test_acquisition_drains_every_page_and_preserves_all_statuses_and_predicates`
- `tests.test_managed_elasticsearch.StartupScriptTests.test_failure_prevents_web_and_api_start`
- `tests.test_managed_elasticsearch.StartupScriptTests.test_start_prepares_search_before_application_processes`
- `tests.test_managed_elasticsearch.StartupScriptTests.test_status_and_stop_include_elasticsearch`
- `tests.test_report_knowledge_graph.test_graph_contains_only_relevant_actual_claims_and_valid_endpoints`
- `tests.test_report_knowledge_graph.test_missing_results_and_title_only_references_do_not_create_edges`
- `tests.test_report_knowledge_graph.test_malformed_service_payload_does_not_break_report`
- `tests.test_report_module_integration.test_cache_recovery_runs_all_supplements_without_base_pipeline`
- `tests.test_report_refresh.test_reports_and_downloads_are_not_cached`
- `tests.test_report_templates.test_contribution_concentration_requires_complete_consistent_units`
- `tests.test_single_server.test_shell_config_matches_python_from_other_directory`
- `tests.test_word_template.test_complete_word_contract_without_example_measurements`
- `tests.test_word_template.test_every_word_field_and_visual_has_a_missing_data_state`
- `tests.test_word_template.test_directions_and_contribution_denominators_remain_separate`
- `tests.test_word_template.test_model_uses_word_subsections_instead_of_legacy_topics`
- `tests.test_word_template.test_empty_template_does_not_request_model_for_fixed_explanatory_rows`
- `tests.test_word_template.test_subunit_abundance_is_visible_and_labels_have_space`

## 6. 性能测量

- 数据：3500名合成个体×1000物种，20研究；输入矩阵42,472,574字节。
- 冷比较（含SHA256、解析、统计、bootstrap、越界基线及最多300人的排序图）：4.854秒。
- 缓存后完整再比较：3.525秒，确认解析对象重用且比较结果完全可复现。
- 进程峰值RSS：282.75MiB；NumPy矩阵本身26.70MiB。峰值包括导入、生成临时数据及两次比较，不只是矩阵。
- 固定种子20261114；每个比较1000次经验bootstrap。测试数据仅在临时目录，未发布或替换参考。

复现命令：
```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
PYTHONPATH=src .venv/bin/python scripts/benchmark_cmd_reference.py --subjects 3500 --species 1000
```

## 7. 需要手动执行的步骤

1. 需要应用运行中的服务读取这次代码及.env变更时，由用户手动执行整体重载：

```bash
cd /home/zhanghaiyang/fmt-healthcare-agent
sudo bash deploy/restart.sh
bash deploy/status.sh
```

该入口重读.env，重启API、Web、已启用Agent及托管Elasticsearch，按需重建前端；不主动生成报告或重建参考包。本次未执行。

2. 若.env仍选旧来源，将provider改为cmd或取消设置，并保留正确的WGS_CMD_REFERENCE_DIR/WGS_CMD_PROFILES_DIR。只修改需要迁移的字段，不覆盖整个.env。

3. 仅在需要人口学分层或参考深度字段时，自行选择新目录重建包；本次不执行或发布：

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_cmd_reference.py \
  --package-dir /path/to/official/curatedMetagenomicData \
  --metadata /path/to/cmd-source-snapshot/sample_metadata.tsv \
  --catalog /path/to/ExperimentHub.sqlite \
  --source-dir /path/to/cmd-source-cache \
  --output /path/to/new-cmd-reference \
  --stratify-by country sex age_band \
  --age-band-boundaries 18 30 40 50 60 70 80
```

这些/path/to占位需替换为已有官方源码、元数据及Hub目录真实位置；现有源快照确认有number_reads正值20592条、number_bases正值22584条。新建包会保留深度字段；旧包不受影响。

4. 可手工检查后归档的旧数据（均相对于实际工作区，不是要求立即删除）：

- reference/mho/、reference/healthy/、reference-targets/mho/（含.workflow/.history）。
- reference-sources/mho/、reference-sources/healthy-ena-demo/、reference-sources/healthy-processed/。
- 旧species_reference_overall.csv及其他废弃物种参考统计文件。
- 旧mho-tax环境仅在确认没有其他用途后考虑归档。

不清理cMD、FMT配型、其他专项资源或样本原始/结果文件。本次没有执行这些清理。

## 8. 待确认事项与剩余风险

- 真实样本Markdown/PDF端到端生成按用户最新指示暂缓；单元/集成测试只使用临时合成数据。
- 用户确认当前项目没有Word文件生成功能；本次更新已有Word模板绑定/图表文案，没有新增或声称验证实际DOCX导出。
- 来源MetaPhlAn 3小版本未公布；待测精确3.0.14与来源主版本/v30匹配属于已记录的探索性比较。
- 旧线上cMD包3537人×984物种，metadata没有reads/bases；未重建前参考深度比较仍明确缺失。
- 原研究健康标签、QC、测序/提取批次及深度定义没有被重新临床核验或统一校正；本次只增加透明审计，不做下采样。
- bootstrap区间是逐特征边际区间；计数基线是描述性背景，不是联合推断、FDR校正或疾病概率。
- 新分层可能导致许多层不足30人；会明确不可用，不合层、不降低门槛。
- 基线已有失败单独保留，FMT路径、知识图谱、生命周期/Word结构等无关问题未为通过测试而修复。

交付附件：本报告、reference-inventory.csv、changed-files.json、test-results.json。
