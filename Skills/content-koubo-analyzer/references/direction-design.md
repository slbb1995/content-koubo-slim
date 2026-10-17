# 每次判断，方法按需采用

本页适用于 analysis_version=slim-1.1；旧 Run 保持 slim-1.0 输出，不补造新版记录。

## 选材与判断

先读原题、完整对标、我的想法和 ORAL-GUIDE-001（1.1.0），识别客户要保留的意思和读者的问题。原讲法适合就保留；需要具体角度说明时再读 ORAL-GUIDE-002，采用结构时看本篇需要解释、操作、诊断、比较还是讲述真实变化。八种角度不是必填标签，增强机制可以不用；有对标时正式结构可为空，没有对标时指引不能独立充当内容蓝图。

method_judgment 只记录简短结论与依据：intent、decision（retain/refine/alternative）、reason、angles（可空）、unused_methods_reason、material_gaps（可空）、guidance_ids（实际用于判断且包含通用指引）。不输出长篇内部推演，不做八角度评分。客户意图与对标观点冲突时说明取舍；无法确定核心意图就报告具体缺口。未读取的资料不能声称采用。

## 完整方向

一版足够时只给一版。两版必须分别回答不同的具体问题或采用不同推进路线；换标题、换开头一句不算。共用参考拆解和冻结资料，预算不翻倍。每项保留自己的模式建议、业务资料需求和收尾，recommended_option_id 只作推荐。

每项 fused_direction 内的 writing_design 包含：

- angle：原题内的具体进入问题及与客户原意的关系。
- opening：让谁认出什么处境，承诺回答什么。写功能，不预写正文句子。
- body_steps：有序列表，每项 content 说明新增内容，reason 说明与上一步关系，evidence 说明依据或待取得事实。
- ending：回应开头、落下判断、条件或检查动作；不要求每篇 CTA 或金句。
- method_uses：本项实际采用的 asset_id 与具体 application；只能来自本次 planning_guidance 或本方案 selected_method_assets，可为空。
- evidence_boundary：事实、假设与未取得依据的范围。不能虚构比较结果、内幕或本人经历。

structure_plan 必须等于 [opening, 每个 body_steps.content, ending]；customer_readable_direction.oral_structure 与它同值。其余现有客户投影字段保持同值。程序直接把 writing_design 加入 Gate A，入口不可另编计划。

每项 reference_usage 按参考原序逐篇记录 reference_id、adopted_value（采用的具体内容价值/机制，可写不采用）、application（本篇怎样执行）、not_used（不采用部分及原因）。保留详细借鉴，不能只写“用钩子/用结构”。未选方向的专属要求不进入本方案；所有参考的禁止迁移边界仍保留。

## 确认与交接

方向候选仍只对应一个 Run。完整展示后等待用户，单方向可直接认可；双方向明确选择并认可。按同一方向版本冻结所选设计，再交给 P3。不要提前写正文，不增加 Reviewer 或自动二次改写。
