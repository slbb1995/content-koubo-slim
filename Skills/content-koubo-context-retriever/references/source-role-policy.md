# 来源角色与方向冻结规则

## 04：同行内容与口播方法

- 只使用 P2 已冻结项，禁止 Gate A 后重新搜索、替换或追加；
- `peer_content_asset` 只提供通用问题、观点线索和内容组织价值；
- `oral_method_asset` 只提供表达顺序、钩子、节奏和结构方法；
- 同行身份、经历、客户案例、公司业务、专属数据和识别性原句不得进入 Writer 上下文；
- 输出 `writer_context` 时改成适用于当前批准方向的通用判断或表达方法。

## 03：客户业务知识

- 只在 `business_context_needs` 非空时使用程序给出的候选；
- 只选择真正相关的局部片段，保留相对路径和逐字可回溯片段；
- 03 为空时允许继续，用一般性或条件性表达；
- 不得把 04 或模型常识冒充客户自己的产品、服务、案例、数据、观点或承诺。

## 05：讲述者 Profile

- `personal_ip` 必须使用本 Run 已明确选定并冻结的一份 active Profile；`primary` 只参与默认选择，不限制选择其他 active Profile；
- `company_brand` 和 `neutral` 不读取 05，输出 `profile_context: null`；
- 只提取 Writer 当前真正需要的少量逐字片段；
- 本人确认事实、项目设定和候选素材不得互相冒充；候选素材不能自动升级为本人事实。

## 重大冲突

03/05 若与 Gate A 已批准的核心立场、讲述身份或 Writer 主模式冲突，不得静默修正 Context Pack。停止进入 Writer，用大白话说明冲突，并回到 Gate A 修改方向或新建 Run。普通补充和措辞差异不触发新 Gate。

## 固定输出政策

`source_role_policy` 使用以下固定值，不能由 AI 另写一套规则：

```json
{
  "peer_content": "generalize_without_peer_identity_experience_case_business_data_or_quote",
  "client_business": "use_only_selected_03_for_client_specific_business_support",
  "client_profile": "personal_ip_only_keep_confirmed_profile_layers_separate",
  "missing_business": "use_general_or_conditional_language_and_do_not_invent_client_facts"
}
```
