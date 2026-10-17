# `content-slim` Skill 设计卡

## 名称

- Skill 名称：`content-slim`
- 用户语言名称：内容生产

## 唯一目的

作为 Content V2 Slim 的唯一用户入口，协调一个内容任务的单 Run、版本、状态、三次真人确认和最终保存调用。

本 Skill 只编排，不拆解对标、不做 Vault 语义检索、不写正文、不生成标题、发布正文或标签，也不直接写入客户 Vault。

## 何时使用 / 何时不得使用

### 使用

- 用户要开始、继续、查看或结束一条 Content V2 Slim 口播内容任务；
- 用户要确认或返修方向、正文或配套文案；
- 程序需要解析当前客户配置、复用同一个 Run、推进合法状态或保存版本链。

### 不得使用

- 建设客户知识、内容方法或个人资料资产；
- 执行对标拆解、语义检索、正文写作或配套文案生成；
- 发布、上传、Git 提交、推送、构建、安装或修复 Host；
- 调用任何旧 Content V1 Skill；
- 创建 Reviewer、临时程序、第二层上下文包或额外 Skill；
- P1 中进入真实 Gate A、正文、配套或保存业务。

## 唯一输入 / 唯一输出

### 唯一输入：`content_slim_request`

所有操作共用一个请求信封：

```json
{
  "operation": "start | respond-direction | respond-draft | respond-package | resume | status",
  "client_id": "<configured-client-id>",
  "payload": {}
}
```

- `client_id` 只用于 Registry 定位，不携带路径；
- 当前 Codex Host 没有向本入口提供一个可验证、跨 `start / respond-direction / status` 稳定的请求身份，因此普通 CLI 不接收 `host_request_id` 或原始 `task_key`；
- `start` 由确定性程序根据冻结的 `client_id`、`speaker_mode`、用户原始选题和参考来源集合生成任务身份并写入受控 `task-keys/` 记录；后续内部操作只接受已经存在且校验通过的 task-record；
- 用户字段或 AI 临时字符串不能直接充当宿主身份或 task-record；
- `payload` 的阶段业务字段在 P2—P5 分阶段定义；P1 不提前实现。

### 唯一输出：`content_slim_response`

所有成功、等待和失败结果共用一个响应信封：

```json
{
  "status": "waiting | working | completed | blocked | abandoned",
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

内部状态、哈希、绝对路径、Schema、参考全文、Analyzer 输入和技术报告路径不进入普通用户响应。内部 AI 交接只读取当前 Run 中受控、create-only 的 Artifact。

## AI 职责 / 程序职责

### AI 职责

- 理解用户当前是在开始、确认、返修、恢复还是查看状态；
- 只展示当前阶段需要用户判断的业务内容；
- 在后续阶段调用且仅调用对应的新内部 AI Skill；
- 用大白话解释阻断，不把机械合同暴露给用户。

## 真人 Gate 的跨轮次边界

- 完整展示方向、正文或配套 Gate 后，必须结束当前 Assistant 轮次；同一轮次不得调用对应的 `respond-direction`、`respond-draft` 或 `respond-package`；
- 只有收到下一条真实用户消息，且该消息明确包含当前 Gate 允许的决定或具体修改意见，才可调用对应 `respond-*`；
- Agent 不得代写、推断、预填或从阶段授权、测试授权、结构校验、既有记忆中派生批准决定；
- 该约束只收紧现有三个真人停点的执行顺序，不新增 Runtime、状态、Schema、Artifact、Reviewer 或第四个确认点。

### 程序职责

- `client_registry`：用 `client_id` 定位 `vault_root` 和 Manifest 相对路径；
- `client_manifest`：校验逻辑资产根、输出策略和 `speaker_mode`；
- `run_store`：以跨进程文件锁保护同一 `task_key` 的唯一 Run、中断恢复和 create-only 版本；
- `state_machine`：只允许 Master SPEC 定义的状态迁移；
- `error_model`：统一错误字段与大白话消息；
- P2—P5 才分阶段增加参考准备、受控检索、唯一 Context Pack 和保存实现。

## 依赖工具

- 创建期：必须显式调用 `skill-creator`；
- 运行期：P1 仅使用 Python 标准库和传入的 Registry、Manifest、Run 根；
- 后续 AI 依赖固定为 `content-analyzer`、`content-context-retriever`、`content-writer`、`content-publish-pack`，且只在各自阶段获批后接入；
- 旧 Content V1 Skill 运行依赖必须为 0。

## 禁止访问范围

- 未由 Registry 与 Manifest 授权的本地目录；
- 客户 Vault 的逻辑资产根之外；
- `~/.codex/skills`、客户 Skill RC、旧 V1 Run 和 Host 管理状态；
- 任何远端、发布平台或 Git 写操作；
- Writer 直接访问 Vault；
- 客户名、行业、固定 Profile 文件名、固定资产物理目录和写死的本地绝对路径。

## 错误与返修

- 错误必须说明：哪里出错、真实工作流阶段、Run 是否存在和是否刚创建、产物是否存在和是否保留、下一步怎么做；
- 机械失败在同一 Run、同一阶段恢复，不新建 Run 掩盖问题；
- 方向、正文和配套返修使用 `v2/v3/...`，旧版本 create-only 保留；
- 非法状态迁移、Manifest 不兼容、路径越界或 `personal_ip` 所需 Profile 条件不成立时 fail closed；
- P1 只建立错误与返修机制，不生成任何真实业务内容。

## 最小示例

1. 调用方提交 `operation=start`、已配置的 `client_id`、用户原始选题和参考集合，不提交 `task_key`；
2. Runtime 校验 Registry 与 Manifest，根据冻结业务身份和参考来源集合生成 task-record，创建一个 Run，状态为 `started`；
3. 同一组冻结身份因机械原因重试时复用受控 task-record 并返回原 Run，不创建第二个 Run；
4. P1 返回“基础运行环境已准备，内容阶段尚未启用”；
5. 任何真实方向、正文、配套或保存动作都保持未实现并停止。

## P1 验收标准

- 仓库只新增 `content-slim` 一个 Skill；
- 设计卡已回读，所有必填章节存在且与 Master SPEC 一致；
- `skill-creator` 初始化命令和输出证据可回读；
- Registry 只承担 `client_id → vault_root + manifest_relative_path` 定位；
- Manifest schema 为通用合同，支持 `personal_ip`、`company_brand`、`neutral`；
- `personal_ip` 要求 Profile，另外两种模式不强制 Profile；
- 同一组冻结业务身份和参考来源重试仍只有一个 Run；普通 CLI 不接受任意 `host_request_id` 或原始 `task_key`；
- 并发启动和 state 已写但 index 未更新的中断恢复仍只有一个 Run；
- 索引中的 `run_id` 不能越过 Run 根，版本失败不留下损坏占位；
- 版本 create-only，状态迁移非法时阻断；
- 错误响应为统一大白话模型；
- 新代码不包含客户名、行业、固定 Profile 文件名、固定资产物理目录或本地绝对路径；
- 旧 Content V1 Skill 运行依赖、Reviewer、临时程序和第二层上下文包均为 0；
- P1 聚焦测试通过，但 Review 状态仍为 `pending`，不得宣布 Gate P1 PASS。

## 新增项的消费者与替代关系

| 新增项 | 保护的业务结果 | 消费者 | 替代的旧步骤 | 不增加时的可复现问题 | 为何不能并入其他职责 |
| --- | --- | --- | --- | --- | --- |
| Registry | 不串客户 | `content-slim` Runtime | 依赖当前目录或多处路径配置 | 同一请求可能解析到错误 Vault | 只负责本地定位，不能混入客户自描述规则 |
| Manifest schema | 新客户不改主流程 | Manifest 校验器及后续检索/保存模块 | V1 大配置合同 | 客户目录与模式漂移无法启动前阻断 | 客户自描述必须留在 Vault 合同层 |
| Run Store + 版本链 | 正常任务只有一个 Run，返修可回读 | 状态机及后续四个阶段 | 多 Run 重试与覆盖式产物 | 机械重试生成新 Run 或覆盖旧版本 | 这是确定性持久化，不属于 AI Skill |
| 状态机 | 三次真人确认不可越过 | `content-slim` | V1 重型状态与收据链 | 未确认就进入下游 | 状态合法性应由程序统一控制 |
| 错误模型 | 用户知道卡点和最小下一步 | 所有 Runtime 模块 | exit code/合同术语直出 | 用户无法判断是否丢产物或该做什么 | 横跨所有机械模块，需要单一格式 |

## P1 Review 有限收口设计决定

- Run Store 的 `start_task`、`transition` 和版本写入共用一把跨进程文件锁；消费者仍只有 `content-slim`，不新增模块或状态。
- state 已创建但 index 未更新时，按 `task_key` digest 查找唯一 Run；零候选才新建，多候选立即阻断。
- 用户响应只说真实工作流阶段和 Run/产物事实；组件、错误码与 detail 只进入技术记录。
- `SKILL.md` 同时服务人类理解与 AI 执行；设计原因留在本卡，细节放 references，实现放 runtime，字段放 schemas。
