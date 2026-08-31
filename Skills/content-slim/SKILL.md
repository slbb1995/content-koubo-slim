---
name: content-slim
description: Content V2 Slim 的唯一用户入口。用于开始、继续、恢复或查看一条短视频口播内容任务，在同一个 Run 中协调状态、版本和三次真人确认；P5 可在正文确认后调用 content-publish-pack，确认配套后 create-only 保存两份 Markdown 并保持未发布。仅做编排；不得亲自拆解、检索语义、写稿、发布或调用旧 Content V1 Skill。
---

# Content Slim

## 一句话目的

用一个入口安全管理一条 Content V2 Slim 任务；P5 推进到配套确认和两份 Markdown 安全保存，然后保持未发布并停下。

## 什么时候使用

- 开始或恢复一条口播内容任务；
- 查看当前任务状态；
- 记录方向的认可、普通修改或不采用；
- 生成正文后记录“确认正文”或带具体意见的“需要修改”；
- 生成配套后记录“确认并保存”或带具体意见的“需要修改”；
- 配套确认后调用确定性保存，一次写入并回读两份 Markdown；
- 通过确定性 Runtime 复用同一个 Run、保存版本并推进合法状态。

## 什么时候不要使用

- 建设客户知识、内容方法或个人资料资产；
- 直接拆解对标、判断资料语义、写正文或生成配套文案；
- 构建、安装、发布、Git 操作或 Host 修复；
- 自己读取 03/05、写 Context Pack、正文、配套或客户保存。

## 输入

用户业务输入只包含：

```json
{
  "topic": "用户原始选题",
  "references": ["1—5 篇本地参考"],
  "user_thoughts": null,
  "must_keep": [],
  "must_avoid": []
}
```

`client_id` 和 `speaker_mode` 从当前配置解析。默认读取当前 Codex Host 的持久 Registry；只有一条有效客户记录时自动采用，多条记录时必须让用户明确选择，不扫描电脑或猜测知识库。当前 Codex Host 没有向入口提供可验证且跨 `start / respond-direction / status` 稳定的身份，因此普通 CLI 不接收 `host_request_id` 或原始 `task_key`。确定性程序根据冻结的客户、讲述模式、用户原始选题和参考来源集合生成 task-record；后续内部操作只接受已经落盘并通过完整性校验的相对句柄。不得让用户填写或让 AI 临时编造；不得改传绝对路径，必须原样复用入口返回的 task-record。

## 输出

返回一个用户可读响应，明确当前工作流阶段、Run 和产物状态：

```json
{
  "status": "working | waiting | completed | blocked | abandoned",
  "status_label": "用户可读状态",
  "workflow_stage": "用户可读工作流阶段",
  "message": "当前结果或问题",
  "next_action": "用户下一步",
  "run_exists": true,
  "run_created_now": false,
  "artifacts_exist": false,
  "artifacts_preserved": false
}
```

不要向普通用户展示错误码、技术组件、detail、哈希、Schema、参考全文、相对路径、客户技术字段或完整 Analyzer 输入。内部 AI 交接只读取当前 Run 的受控 Artifact。

## 执行流程

1. 从当前 Host 的默认或显式 Registry 定位客户：唯一记录自动采用，多条记录等待用户选择，再按 `client_id` 定位 Vault 和 Manifest；
2. 校验 Manifest 并解析 `speaker_mode`；
3. 在创建 Run 前验证 1—5 篇参考可读，再根据冻结业务身份和参考来源集合生成受控 task-record，创建或恢复唯一 Run；
4. create-only 冻结用户原始选题、参考集合、`client_id` 和 `speaker_mode`；系统内部生成规范化问题并标记 `system_generated`，不要求用户或 AI 提供；
5. 只从 Manifest 的 `method_root` 轻量检索 04，不依赖用户填写受众范围；最多 0—3 张同行内容资产和 0—2 张口播方法资产，可返回不同 `audience_scope`；无高相关结果时继续；
6. 把标准化参考和 04 候选交给 `$content-analyzer`，接收完整结果后生成一次 Gate A；
7. Gate A 修改前由 AI 判断是否根本改变原始选题、目标受众、核心承诺、参考集合、客户或讲述者；根本变化时在现有 `respond-direction` 内部交接设置 `--task-identity-changed`，由程序要求新 Run；普通修改才在同一 Run 生成下一版，且 `direction_vN` 只消费同版本 `analyzer_input_vN`；
8. 认可时冻结用户实际看到的同版本 Gate A 或其确定性投影，不采用时结束；
9. Gate A 批准后，程序只按冻结清单回读 04，按业务需求读取少量 03，并按 `speaker_mode` 条件读取 05；
10. 调用 `$content-context-retriever` 形成唯一 `content_context_v1.json`，校验并进入 `context_ready`；
11. P4 只把这份 Context Pack 交给 `$content-writer`，按冻结值加载一份 `ganhuo / huati / zhuanhua` 主模式规则；
12. 程序把 Writer 的自然段输出 create-only 保存为同版本 `draft_vN.json` 与 `draft_vN.md`，完整展示正文；
13. 用户选择“需要修改”时，保留旧版本，在同一 Run 用当前正文、同一 Context Pack 和本次具体意见生成下一版；
14. 用户选择“确认正文”时，程序生成 `approved_draft.json` 并进入 `draft_approved`；
15. P5 重新校验已确认正文，只把正文交给 `$content-publish-pack`，生成一份含 2 个封面标题、3 个发布标题、推荐项、50—100 字发布正文和 5 个标签的 `package_vN.json`；
16. 用户选择“需要修改”时，保留旧版本，在同一 Run 用当前配套、同一已确认正文和本次具体意见生成下一版；
17. 用户选择“确认并保存”时，默认使用推荐标题，也可选当前其他候选；程序固定 `approved_package.json`，不再询问一次是否保存；
18. 程序重新校验冻结客户位置和 Manifest 输出根，一起预检两个目标，create-only 写入纯口播稿与配套文案并分别回读；
19. 只有两份文件都成功才进入 `saved`；结果始终保持 `publish_status=not_requested`，P5 停止，不进入 P6。

## 真人停点

完整产品只有三个真人停点：方向、正文、配套与保存。P5 启用第三个真人停点，必须先完整展示配套，再接受“确认并保存”或带具体意见的“需要修改”；确认动作立即保存，不增加第四次询问。

Gate A 只接受：`认可整版方向 / 需要修改 / 不采用`。正文确认只接受：`确认正文 / 需要修改`。配套确认只接受：`确认并保存 / 需要修改`。程序校验不代替真人选择。

展示 Gate A 时，只把 Runtime 同版结果确定性归并成五组客户内容，不另做第二次分析：谁来说、讲给谁；核心观点和承诺；对标准备保留什么；哪些内容不照搬；准备怎么讲。五组必须与同版详细拆解报告一致；客户确认后，Runtime 将该版本的逐篇内容价值、钩子、结构、可迁移项、禁止迁移项和冲突处理投影进唯一 Context Pack，Writer 必须按详细蓝图执行，不能只根据五组摘要写作。展示后仍只接受既有三个选择，不增加确认拆解或确认资料等新 Gate。

每次完整展示方向、正文或配套 Gate 后，必须立即结束当前 Assistant 轮次；展示 Gate 的同一轮次禁止调用 `respond-direction`、`respond-draft` 或 `respond-package`。收到下一条真实用户消息后，先用原样 task-record 查询当前 Run 状态，再选择该状态对应的唯一 `respond-*`；不得按上一轮的记忆猜入口。只有该消息明确包含当前 Gate 允许的决定或具体修改意见后，才可调用对应 `respond-*`。对合法选择只去除首尾空白和句末常见中英文标点；“随便”“差不多”等模糊表述仍不视为确认。Agent 不得代写、推断、预填或从阶段授权、测试授权、结构校验、既有记忆中派生批准决定。

## 错误与停止

- 任意 CLI 字符串被当作宿主身份或 task-record 时，在创建 Run 或恢复前停止；
- Registry、Manifest、Run 索引、参考来源或 `method_root` 不可信时立即停止；
- Registry 含多个客户且用户未选择时停止，不按顺序、最近使用时间或目录名猜测；
- 同一 `task_key` 出现多个候选 Run 时 fail closed；
- Gate A 修改根本改变任务身份时设置内部 `--task-identity-changed`，不得在原 Run 创建下一版方向；
- 非法状态迁移、版本覆盖或客户身份变化时停止；
- Context Pack 错绑、Writer 输出不是纯正文段落、修改意见为空或确认版本不一致时停止；
- 正文未确认、配套字段/数量不合法、确认版本不一致或候选外标题选择时停止；
- Registry 重绑、Manifest 无效、输出路径越界、目标重名或双文件任一写入/回读失败时，不报告保存完成；
- 保存阶段重试只复用已确认正文、配套和标题选择，不重新生成内容；
- 错误响应说明真实工作流阶段、Run 是否存在、是否刚创建、产物是否存在和是否保留；错入口时只给当前真实阶段和唯一恢复动作。task-record 无效时继续 fail closed，提示复用入口返回的原句柄，不据此断言 Run 一定不存在；
- 机械失败复用同一个 Run，不创建新 Run 掩盖问题。

## 禁止事项

- 不调用任何旧 Content V1 Skill；
- P2 调用 `content-analyzer`；P3 调用 `content-context-retriever`；P4 调用 `content-writer`；P5 只新增并调用 `content-publish-pack`；
- 不增加 Reviewer、第二层上下文包或临时程序；
- 不扫描未授权目录，不写客户名、行业、Profile 文件名或资产物理目录；
- Writer 只允许读取一份 `content_context_v1.json`；不调用三个旧 Writer，不搜索 Vault，不重选模式；
- 配套 Skill 不读取 Vault、不修改或重复输出已确认正文；
- P5 只写 Manifest 授权输出根下的两份最终 Markdown，不修改客户 Vault 的 01—05；
- 不调用旧标题、分发或保存 Skill，不增加 Reviewer、状态、发布能力或 P6 产物；
- 不修改客户 RC、Host、main、Tag，不执行客户内容的 Git、推送、同步、上传或发布。

## 最小示例

正文 `draft_v2` 已确认后，P5 只根据它生成 `package_v1` 并展示。用户给出具体意见时，在同一 Run 生成 `package_v2`，旧版保留；用户确认并默认采用推荐标题后，程序一次保存纯口播稿和配套文案，两份都回读成功才完成，结果保持未发布。

## 文件导航

- `scripts/content_slim.py`：方向、Context Pack、正文、配套版本与三次真人确认的编排；
- `runtime/client_registry.py`、`client_manifest.py`：默认配置位置、唯一客户选择与通用配置；
- `runtime/run_store.py`、`state_machine.py`：锁、单 Run、正文/配套版本和状态；
- `runtime/reference_prep.py`：1—5 篇参考的独立准备；
- `runtime/vault_search.py`、`vault_reader.py`：Manifest 限定的 04 搜索/回读，以及 P3 授权 03 的局部检索和条件 05 回读；
- `runtime/schema_validation.py`：Analyzer、Gate A、唯一 Context Pack、正文与配套输出边界；
- `runtime/vault_save.py`：Manifest 授权输出根下的双文件 create-only 保存与回读；
- `runtime/error_model.py`：用户响应与技术记录分离；
- `schemas/`：Registry 与 Manifest 字段合同。

设计原因保存在 Factory 设计卡；实现细节读 `runtime/`；字段约束读 `schemas/`。不要把这些内容复制回本文件。
