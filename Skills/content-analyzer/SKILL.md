---
name: content-analyzer
description: Content V2 Slim 的内部爆款拆解与方向 Skill。用于 content-slim 已在同一 Run 冻结用户原始选题、1—5 篇参考、client_id 和 speaker_mode，并提供当前 Manifest 授权的少量 04 候选后，逐篇拆解、融合冲突、选择真正相关的方法资产，生成完整 Gate A 方向与唯一 Writer 模式建议。不得创建 Run、读取 03/05、写正文或进入 P3。
---

# Content Analyzer

## 一句话目的

把已准备好的外部参考和少量 04 候选融合成一版完整、可判断、不会挪用同行身份的写作方向。

## 使用边界

- 只接收程序生成并通过校验的 `analyzer_input_v1`；
- 只分析其中 1—5 篇独立参考和 0—5 张 04 候选；
- 不接收原始 `task_key`、绝对路径、整个 Vault 或未授权页面；
- 不创建 Run、状态、版本、收据或临时程序；
- 不读取 03/05，不创建 Content Context Pack，不调用 Writer；
- 不生成正文、标题、发布正文、标签，不保存或发布。

## 输入

读取唯一输入合同 `schemas/analyzer-input.schema.json`。必须保持：

- `topic_original` 是用户原话；`topic_normalized` 只能由程序生成并标记 `topic_normalized_source=system_generated`，两者不能互换；
- 输入不含用户填写的 `target_audience` 或 `target_audience_scope`；根据选题、参考和 04 候选判断受众，并在 Gate A 交给用户确认；
- `references` 按 `REF-001...` 独立存在，不先拼成一篇；
- `method_candidates` 的 `asset_role` 只能是 `peer_content_asset` 或 `oral_method_asset`；
- 04 候选由入口基于原始选题、规范化选题、用户想法、`must_keep` 与参考的有限标题/高信号片段轻量准备；候选因泛词命中不等于相关，无高相关项时保持空数组；
- `revision_request` 为空时生成首版；不为空时只按具体意见修普通方向，不改变冻结身份。

输入字段、数量、来源或角色不符合合同时立即停止，不自行补造。

## 输出

只返回一份符合 `schemas/analyzer-output.schema.json` 的 `analyzer_result_v1`：

- 每篇参考各有一项 `reference_analyses`；它们共同组成同版详细拆解报告，也是下游 Writer 详细蓝图的唯一来源，不能被客户阅读摘要替代；
- 多篇只形成一个 `fused_direction`，显式记录冲突与处理；
- 04 选择只来自输入候选，保留角色、相对路径和页面哈希；
- `content_goal` 只用 `explain / discuss / convert`；
- `writer_mode` 只选 `ganhuo / huati / zhuanhua` 中一个，并说明业务理由；
- `secondary_tactics` 只放少量辅助技巧；
- `business_context_needs` 只列后续可能需要的业务资料类型，不读取资料；
- `customer_readable_direction` 完整承载 Gate A 的业务内容；其受众、核心承诺、参考价值、口播结构、Writer 理由、04 使用方式和一般化边界必须与对应融合字段同值。

不要输出机械 ID、绝对路径、时间、状态、正文或发布物料。

## 执行流程

1. 完整读取 `references/source-roles-and-gate-a.md`；
2. 逐篇拆解受众、问题主线、核心承诺、内容价值、钩子与结构机制；
3. 为每篇分开列出可迁移点和禁止转移项；
4. 多篇时融合共同机制、去重，记录至少绑定两篇来源的真实冲突；无冲突使用空数组；
5. 只选择确实服务当前方向的 04 候选；无相关候选时保留空数组，不凑数量；
6. 分开说明同行内容资产提供了什么内容方向，口播方法资产提供了什么表达机制；
7. 根据选题、参考、04 候选判断目标受众，再根据受众、核心承诺、希望读者发生的变化和参考机制提出一个 Writer 主模式；不要用关键词直接写死路由；
8. 生成完整客户阅读方向，逐字保留原始选题，并如实呈现用户想法、必须保留和不要写成；
9. 按唯一输出合同返回，等待程序校验和真人 Gate A。

## Gate A 边界

Analyzer 只生成一份同版结果，但服务两个用途：`reference_analyses + fused_direction` 是详细拆解报告，供后续形成 Writer 详细蓝图；`customer_readable_direction` 是这份报告的客户确认投影。入口把客户投影固定分成五组展示：谁来说、讲给谁；核心观点和承诺；对标准备保留什么；哪些内容不照搬；准备怎么讲。五组不得改变详细报告的业务结论，也不得成为 Writer 的唯一依据。

Analyzer 不替用户选择 `认可整版方向 / 需要修改 / 不采用`，也不把程序校验当成人工批准。`direction_vN` 只响应同版本 `analyzer_input_vN`；V2 及以后必须含针对上一版的非空真人修改意见。普通修改返回完整新版，不覆盖旧版，不只返回补丁。

## 来源与身份保护

- `peer_content_asset` 可提供选题、问题主线、通用观点、场景、顺序和细节方向；
- `oral_method_asset` 只提供钩子、结构、推进、增强机制和 CTA 方法；
- 不把同行作者身份、经历、客户案例、公司业务、专属数据、承诺或高度识别性原句写成当前客户内容；
- 将专属内容去身份化、一般化或条件化；无法安全转换时舍弃并写入禁止项；
- 不把参考中的断言自动升级为客户事实。

## 错误与停止

- 参考少于 1 篇、多于 5 篇、缺篇、重复、内容为空或来源边界不清时停止；
- 04 候选越界、角色不明、哈希或来源绑定缺失时停止；
- `speaker_mode`、原始选题、参考集合、客户或已展示受众被要求根本改变时停止并要求新 Run；
- 同行专属内容无法隔离，或完整方向无法满足唯一输出时停止；
- 不通过 Reviewer、新 Run、临时程序、正文或 P3 能力绕过阻断。

## 最小示例

输入含两篇独立参考、一张同行内容资产和一张口播方法资产。逐篇说明各自的内容价值与禁止项，融合共同问题主线并标出冲突；选择同行页提供通用场景，选择结构页提供推进方法；建议一个主 Writer 模式，返回完整 Gate A 方向。不要写任何正文句子。

## 文件导航

- `references/source-roles-and-gate-a.md`：逐篇拆解、融合、来源角色、路由和 Gate A 细则；
- `schemas/analyzer-input.schema.json`：唯一输入字段；
- `schemas/analyzer-output.schema.json`：唯一输出字段。

设计原因保存在 Factory 设计卡；路径、搜索、版本和 Gate 状态由 `content-slim` Runtime 负责，不复制到本文件。
