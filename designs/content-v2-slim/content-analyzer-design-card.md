# `content-analyzer` Skill 设计卡

## 名称

- Skill 名称：`content-analyzer`
- 用户语言名称：爆款拆解与写作方向

## 唯一目的

读取程序已经标准化且冻结边界的 1—5 篇外部参考件，以及当前客户 Manifest 授权的少量 04 候选，完成逐篇拆解、多篇融合、来源去重与冲突提示，形成一版可供用户完整判断的 Gate A 写作方向。

本 Skill 只做语义分析和方向建议。它不创建 Run、不生成或填写 `task_key`、不扫描文件系统、不读取 03/05、不创建 Content Context Pack、不调用 Writer，也不生成正文、标题、发布正文或标签。

## 何时使用 / 何时不得使用

### 使用

- `content-slim` 已在同一个 Run 内冻结用户原始选题、参考集合、`client_id` 和 `speaker_mode`；
- Reference Prep 已逐篇完成，参考数量为 1—5，来源边界可回读；
- 程序已通过当前客户 Manifest 的 `method_root` 返回 0—3 张高相关 `peer_content_asset` 和 0—2 张高相关 `oral_method_asset`；
- 首次形成 `direction_v1`，或用户提出不改变任务根本身份的普通方向修改，需要同 Run 形成 `direction_v2/v3`。

### 不得使用

- `task_key` 缺失、来源不是宿主或确定性程序，或需要 AI 临时编造；
- 原始选题、参考集合、`client_id` 或 `speaker_mode` 尚未冻结；
- 参考件少于 1 篇或多于 5 篇，任一参考无法独立读取或来源边界不清；
- 需要猜测客户目录、扫描 Manifest 未授权范围，或读取 03/05；
- 需要生成正文、标题、发布正文、标签、Content Context Pack 或进入 P3；
- 需要调用旧 Content V1 Skill、独立 Reviewer、临时程序、保存或发布能力；
- 用户的修改根本改变原始选题、目标受众、核心承诺、参考集合、`client_id` 或 `speaker_mode`。这种情况必须由程序要求新 Run，不能由 Analyzer 静默沿用旧身份。

## 唯一输入 / 唯一输出

### 唯一输入：`analyzer_input_v1`

输入由确定性程序装配，AI 不填写机械身份、路径、时间、版本或来源映射：

```json
{
  "analysis_version": "slim-1.0",
  "topic_original": "用户原始选题，create-only",
  "topic_normalized": "系统规范化后的问题，不冒充用户原话",
  "topic_normalized_source": "system_generated",
  "client_id": "configured-client",
  "speaker_mode": "personal_ip",
  "user_thoughts": null,
  "must_keep": [],
  "must_avoid": [],
  "references": [
    {
      "reference_id": "REF-001",
      "title": "参考标题",
      "content": "已清理正文",
      "source_boundary": "本篇独立来源边界"
    }
  ],
  "method_candidates": [
    {
      "asset_id": "METHOD-001",
      "asset_role": "peer_content_asset",
      "relative_path": "当前 method_root 内的相对路径",
      "excerpt": "局部相关内容",
      "relevance_evidence": ["命中的主题或问题线索"]
    }
  ],
  "revision_request": null
}
```

约束：

- 用户业务输入只包含 `topic_original`、1—5 篇参考、`user_thoughts`、`must_keep`、`must_avoid`；不得要求用户或 AI 提供 `topic_normalized`、`target_audience` 或 `target_audience_scope`；
- `topic_original` 与系统确定性生成的 `topic_normalized` 必须并存，且用 `topic_normalized_source=system_generated` 明确标记来源；
- `references` 保持 1—5 篇独立项，不先拼成一篇；
- `method_candidates` 只能来自当前 Manifest 授权的 `method_root`，并已由程序限制数量；
- `asset_role` 只能是 `peer_content_asset` 或 `oral_method_asset`；
- `revision_request` 只用于同 Run 普通修改，必须带用户的具体修改意见；
- 原始 `task_key`、绝对路径、内部哈希和客户 Vault 全文不进入 Analyzer 输入。

### 唯一输出：`analyzer_result_v1`

```json
{
  "analysis_version": "slim-1.0",
  "reference_analyses": [],
  "selected_method_assets": [],
  "fused_direction": {},
  "content_goal": "explain",
  "speaker_mode": "personal_ip",
  "writer_mode": "ganhuo",
  "writer_mode_reason": "选择一个主模式的业务理由",
  "secondary_tactics": [],
  "business_context_needs": [],
  "customer_readable_direction": {}
}
```

程序负责为输出绑定 Run、版本、来源映射和 create-only 文件名；Analyzer 不写 `direction_vN` 路径、状态、时间或收据。

## AI 职责 / 程序职责

### AI 职责

- 逐篇识别参考件的受众、问题主线、核心承诺、内容价值、结构机制和不可转移内容；
- 根据选题、参考和 04 候选判断目标受众，并把判断放进 Gate A 由用户确认；
- 多篇时融合共同机制、去重，并明确保留或舍弃的冲突；
- 从少量候选中只选择真正相关的 04 资产，不为凑数量使用无关页面；
- 分开使用 `peer_content_asset` 的内容方向价值和 `oral_method_asset` 的表达方法价值；
- 将同行专属内容去身份化、一般化或条件化，不转移同行身份、经历、客户案例、公司业务、专属数据和高度识别性原句；
- 输出 `content_goal`、唯一 `writer_mode`、选择理由、少量辅助技巧、后续可能需要的业务上下文类型，以及客户可读的完整方向；
- 把用户原始选题、想法、必须保留和不要写成准确呈现在 Gate A 阅读版中。

### 程序职责

- 当前 Codex Host 没有向本入口提供可验证且跨三类操作稳定的宿主请求身份；确定性程序根据冻结的 `client_id`、`speaker_mode`、原始选题和参考来源集合生成 `task_key`，在 Run 索引和 `state.json` 持久化摘要与生成来源；普通 CLI 不接受任意 `host_request_id` 或原始 `task_key`；
- 后续内部操作只接受受控 Run Store 中已存在且内容校验通过的 task-record；用户字段和 AI 临时值不得直接冒充该记录；
- 在同一 Run create-only 冻结 `topic_original`、参考集合及各自来源边界、`client_id`、`speaker_mode`；
- Reference Prep 验证 1—5 篇、逐篇读取和清理，不改原文件、不联网补材料、不合并来源；
- 只从 Manifest 解析 `method_root`，只在该根内受控检索和局部读取 04；搜索不依赖用户填写受众范围，可在既有预算内返回不同 `audience_scope` 的高相关候选；
- 默认最多返回 0—3 张同行内容资产和 0—2 张口播方法资产；无高相关结果时返回空，不阻断；
- 校验 Analyzer 单一输入输出，绑定来源、版本和状态；
- `direction_vN` 只能消费同版本 `analyzer_input_vN`，每个 Analyzer 输入只能生成一次对应方向；V2 及以后输入必须绑定上一版方向和非空真人“需要修改”意见，没有真人修改记录时拒绝再次登记方向；
- 首次 create-only 写入 `direction_v1` 和完整 Gate A；普通修改在同 Run 写下一版本，保留旧版本；
- Gate A 只接受“认可整版方向 / 需要修改 / 不采用”；批准快照绑定具体 `direction_version`、完整 Gate A 与其确定性哈希；`approved_direction` 是用户所见 Gate A 的确定性投影，不得改冻隐藏的 `fused_direction`；
- Analyzer 输出中的融合方向、客户阅读方向、Writer 理由和 04 使用方式必须语义同值，核心承诺、结构或 Writer 理由不一致时在展示前拒绝；
- 非法身份变化、路径越界、来源错绑或状态跳跃时 fail closed。

## 依赖工具

- 创建期：必须先回读本设计卡，再显式调用 `skill-creator`；
- 运行期：只接收 `content-slim` Runtime 准备的结构化输入；
- 确定性依赖：现有 `run_store`、`state_machine`、`client_manifest`，以及 P2 增加的 Reference Prep 和受控 04 Search/Reader；
- 仅使用 Python 标准库实现确定性 Runtime；
- 旧 Content V1 Skill 运行依赖为 0。

## 禁止访问范围

- 03 业务知识根和 05 Profile 根；
- 当前 Manifest 未授权的任何 Vault 目录；
- 其他客户的 Registry、Manifest 或资产；
- 整个 Vault、整篇历史稿和无关 04 页面；
- `~/.codex/skills`、客户 RC、客户 Vault 写入区、旧 V1 Run 和 Host 管理状态；
- Git 写操作、远端、构建、安装、发布平台和 Writer；
- 任何由 AI 临时生成的执行程序。

## Gate A 完整内容与选择

一次 Gate A 必须同时展示：

1. 用户原始选题；
2. 目标受众；
3. 核心承诺或立场；
4. 外部参考中准备借鉴的价值；
5. 选中的 04 内容方向或口播方法及参与方式；
6. 目标口播结构和各部分内容；
7. 用户想法、必须保留和不要写成；
8. `speaker_mode` 的普通语言说明；
9. 内容目标、推荐 Writer 主模式和理由、辅助技巧及后续业务资料需求；
10. 同行身份、客户事实和内容一般化边界。

合法选择只有：

```text
认可整版方向
需要修改
不采用
```

“认可整版方向”冻结用户实际看到的 Gate A 或其确定性投影，并绑定该 Gate A 的 `direction_version` 与哈希；内部 `selected_method_assets` 只能作为已展示 04 使用方式的受控来源绑定一并保存。P2 随即停止，不装配上下文、不调用 Writer。

## 错误与返修

- `task_key` 缺失、来源不可信或要求 AI 临时补造时，在创建 Run 或分析前停止；
- 参考数量、来源边界、Manifest、`method_root` 或 Run 身份不可信时 fail closed；
- 04 无高相关结果不是错误，使用空候选继续形成方向；
- 普通方向修改必须先记录非空真人“需要修改”意见，再 create-only 生成严格同版本 Analyzer 输入；没有该意见、重复消费输入或版本错绑时拒绝；
- 原始选题、目标受众、核心承诺、参考集合、`client_id` 或 `speaker_mode` 根本变化时拒绝同 Run 返修；
- “不采用”把 Run 置为 `abandoned`，不产生正文或保存；
- 失败响应说明真实阶段、Run 与产物是否存在/保留，以及唯一最小恢复动作；
- 不通过新 Run、覆盖旧版本、Reviewer 或临时程序掩盖机械失败。

## 最小示例

1. 当前 Host 未提供稳定请求身份，Runtime 根据冻结业务身份和参考来源集合生成并持久化 task-record；
2. 用户提交一个原始选题和 2 篇参考，Runtime 在同一 Run create-only 冻结四类任务身份；
3. Reference Prep 分别生成 `REF-001`、`REF-002`，不拼接原文；
4. Runtime 只在 Manifest 授权的 `method_root` 返回 1 张 `peer_content_asset` 和 1 张 `oral_method_asset`；
5. Analyzer 逐篇拆解、融合共同价值，标出冲突，输出一个主 Writer 模式和完整客户阅读方向；
6. 程序只允许 `analyzer_input_v1 → direction_v1`，保存并展示一次完整 Gate A；
7. 用户明确选择“需要修改”并留下意见后，程序生成 `analyzer_input_v2`，Analyzer 才能生成 `direction_v2`；用户认可后冻结所见 V2 Gate A 及其确定性投影并停在 P2。

## P2 验收标准

- 本设计卡先于 Skill 创建，已完整回读并通过 Master SPEC/PHASE-P2 边界校验；
- `skill-creator` 初始化命令、输出、源文件哈希和设计卡哈希可回读；
- P2 只新增 `content-analyzer` 一个 Skill；
- 1、2、5 篇参考均通过，0、6 篇和不可读来源均阻断；
- 用户原始选题 create-only，规范化问题不能覆盖或冒充用户原话；
- 普通 CLI 不接受 `host_request_id` 或原始 `task_key`；当前 Host 无稳定身份时，只接受由冻结业务身份和参考来源集合生成并持久化的 task-record，用户字段与 AI 临时值不能直接伪装成宿主身份；
- 任务启动时冻结原始选题、参考集合、`client_id` 和 `speaker_mode`；
- 04 只从 Manifest 授权的 `method_root` 检索；不依赖用户填写 `target_audience_scope`；0—3 张同行页与 0—2 张结构页上限成立，可返回不同 `audience_scope`，无相关结果继续；
- `peer_content_asset` 与 `oral_method_asset` 在输入、选择和 Gate A 中分离；
- 同行身份、经历、客户案例、公司业务、专属数据和识别性原句不转移；
- Gate A 一次完整生成，三种选择合法；方向版本与 Analyzer 输入严格一对一，V2 必须有针对 V1 的真人修改意见；
- Gate A 批准绑定具体版本并冻结用户实际看到的 Gate A 或确定性投影，不读取 03/05、不创建 Content Context Pack、不调用 Writer；
- `start` 与 `respond-direction` 的普通输出不含 Analyzer 输入、参考全文、相对路径、SHA、Schema 或客户技术字段；
- P2 保存一份真实 `$content-analyzer` Forward Evidence：输入含两篇独立参考、1 张同行资产和 1 张口播方法资产，保存脱敏输入、实际输出、最终 Gate A 与转移边界检查；该证据不进入运行主链、不新增 Reviewer；
- 正常任务仍为一个 Run；Reviewer、临时 Python 和旧 V1 运行调用均为 0；
- P2 聚焦测试通过，但 Review 状态仍为 `pending`，不得自行宣布 Gate P2 PASS 或进入 P3。

## 新增项的消费者与替代关系

| 新增项 | 保护的业务结果 | 消费者 | 替代的旧步骤 | 不增加时的可复现问题 | 为何不能并入其他职责 |
| --- | --- | --- | --- | --- | --- |
| `content-analyzer` | 一次形成可判断的写作方向 | `content-slim` 与 Gate A 用户 | 旧 Analyzer、前置 Reviewer 和多份中转 | 对标价值、04 方法与 Writer 路由分散，用户无法一次判断 | 这是唯一需要 AI 语义理解的 P2 职责 |
| Reference Prep | 参考来源独立、可复算 | Analyzer 输入装配 | 旧 Adapter/Ingest Skill 往返 | 多篇被拼接、原文件被改或来源错绑 | 这是确定性文件处理，不应再建 Skill |
| 04 受控 Search/Reader | 方向只使用当前客户授权资产 | Analyzer 输入装配 | AI 扫 Vault 或猜目录 | 跨客户、越界或上下文膨胀 | 路径与上限必须由程序控制 |
| Gate A 方向版本 | 用户判断与返修可回读 | 用户、P3 后续阶段 | 独立 Reviewer 与多 Run 返修 | 修改覆盖 V1 或机械错误制造新 Run | 版本和状态属于现有 Run Store/状态机 |
