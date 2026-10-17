# Content V2 Slim Compass

本文件是 Master SPEC 的轻量执行入口，不替代 `CONTENT-V2-SLIM-FULL-CYCLE-SPEC.md`，也不得新增 Master SPEC 中不存在的要求。

## 1. 用户要得到的结果

用户在 Codex 新 Session 中提供选题、1—5 篇对标和可选写作要求。系统在一个 Run 内完成：

```text
对标拆解 + 轻量检索当前客户 04
→ Gate A 确认方向
→ 按需读取当前客户 03 / 05，并复用已选 04
→ 生成唯一 Content Context Pack
→ 生成并确认口播稿
→ 生成并确认标题、发布正文和标签
→ create-only 保存两份 Markdown
→ 结束，保持未发布
```

用户只做三个真实业务决定：方向、正文、配套与保存。

项目总原则：

> 用真实任务暴露问题，再把重复、过重、位置不合理的流程删除、合并或重新分配职责，让链路更短、更稳定。

## 2. 五个新 Skill

| Skill | 唯一职责 | 不得做 |
| --- | --- | --- |
| `content-slim` | 唯一用户入口；调度、状态、三个真人确认和保存调用 | 不拆解、不做语义检索、不写稿 |
| `content-analyzer` | 拆解外部对标，筛选 04 候选，融合 Gate A 方向并建议 Writer 模式 | 不读 03/05、不写正文、不创建 Run |
| `content-context-retriever` | Gate A 后复用 04、按需装配 03、条件读取 05，生成唯一 Context Pack | 不静默改方向、不保存、不让 Writer 扫 Vault |
| `content-writer` | 按 Gate A 冻结的一个主模式生成和修改口播稿 | 不检索 Vault、不重选模式、不生成配套文案 |
| `content-publish-pack` | 正文确认后生成标题、发布正文和标签 | 不修改正文、不保存、不发布 |

所有新 Skill 的首次创建和结构性修改必须显式调用 `skill-creator`。`skill-creator` 不可用时停止，禁止手写或复制完整新 Skill 绕过。

`SKILL.md` 必须同时服务人类理解与 AI 执行：设计原因进设计卡；细节进 references；实现进 runtime；字段进 schemas。正文只保留目的、使用边界、输入输出、执行流程、真人停点、错误停止、最小示例和文件导航，不复制 Runtime 或完整 Schema。

## 3. Content 通用，客户 Vault 专属

Content V2 Slim 不写死客户姓名、行业、仓库名、本地绝对路径、Profile 文件名或 03/04/05 物理目录名。运行时只通过以下通用字段工作：

```text
client_id
vault_root
client_manifest
knowledge_root
method_root
profile_root
output_root
speaker_mode
```

本地 Registry 只负责 `client_id → vault_root + manifest` 定位；客户 Vault Manifest 负责逻辑资产根、speaker_mode、Profile 选择和输出策略。客户业务事实、内容方法、IP 资产和最终内容留在客户 Vault。新增客户不得复制主流程或新建客户专属 Writer。

## 4. 03 / 04 / 05 动态读取

```text
03：客户或公司的业务知识、产品、服务、观点和业务资料
04：同行内容资产、选题方向、问题主线、通用观点和口播方法
05：个人 IP 的确认事实、项目设定和候选素材
```

规则：

- 04 在 Gate A 前轻量检索，最多返回少量高相关同行页和结构页；无相关结果时继续，不拿无关页面凑数。
- Gate A 后只复用已冻结的 04，不重新全库搜索。
- 03 仅在本篇需要客户业务支撑时检索；缺少同名页面不整篇阻断，可一般化或条件化表达，但不得虚构客户业务、案例、数据和承诺。
- `personal_ip` 必须读取唯一 active primary Profile；`company_brand` 默认不读 05；`neutral` 不读 05。
- 04 可以提供通用内容与方法，但同行身份、经历、客户案例、公司业务和专属数据不得转移给当前客户。
- 03、04、05 任一可选区块为空不自动失败；只有当前 `speaker_mode` 明确要求的 Profile 缺失才阻断。

## 5. AI 与程序分工

AI Skill 负责理解、选择、写作和生成。确定性程序负责：

```text
client_registry
client_manifest
reference_prep
run_store
state_machine
vault_search
vault_reader
content_context_store
schema_validation
error_reporting
vault_save
```

任何内部 AI Skill 都不得自己创建 Run、扫描文件系统、保存、推进状态或现场编写临时执行程序。Writer 只接收一份 `content_context_vN.json`。

## 6. Gate 与反膨胀速查

真实黑盒任务中已经发生的失败优先；稳定复现且影响当前结果、静态必然严重问题次之；理论风险默认进入 P6 观察，不在当前阶段加机制。

Gate 只允许四类阻断：

1. 用户无法完成当前阶段业务结果；
2. 串客户、泄露资料或读取未授权范围；
3. 覆盖、丢失或错误冻结已确认内容；
4. 跳过三个真人确认点或擅自进入下游。

其他问题只标为应修但不阻断、P6 观察或后续优化。Reviewer 不得创造 Master SPEC 中不存在的新要求。

从 P2 结束起，现有状态集合冻结；没有用户明确授权，P3—P5 不增加新状态。总量继续冻结：1 个入口、4 个内部 AI Skill、3 个真人确认点、1 个正常 Run、0 Reviewer、0 AI 临时程序、最多 6 个对外操作、1 份 Writer 正式输入包。

- P3：只建 `content-context-retriever`；最多一个 `content_context_store` Runtime；只产出一份 Context Pack。
- P4：只建 `content-writer`；原则上不加 Runtime；只产出正文及版本。
- P5：只建 `content-publish-pack`；最多一个 `vault_save` Runtime；只产出配套并保存两份 Markdown，不发布。
- P6、P7：不新增产品能力，只验证、删减、集成、构建和迁移。

超预算先停并取得用户授权；没有真实失败证据，不新增 Skill、Reviewer、状态、Schema、Artifact、Gate、句柄、语义分类器、用户字段或命令。

## 7. 全程禁止事项

除非 Master SPEC 对当前阶段明确授权，否则不得：

- 修改旧 Content V1 生产行为；
- 修改 `~/.codex/skills`、客户 Skill RC 或客户 Vault 的 01—05 业务资料；
- 构建、安装、升级、回滚、修复 Host doctor；
- 合并或替换 `main`，创建 Tag，推送或发布；
- 删除、覆盖或重签旧证据；
- 把旧 V1 红灯说成全绿；
- 增加独立 Reviewer、多 Agent 审核链、临时程序、第二层上下文包或旧 V1 运行依赖；
- 让 Writer 搜索 Vault，或把整个 Vault、整篇历史稿和无关资料塞给 Writer；
- 扫描客户配置未授权的 Obsidian 目录；
- 自动保存、提交、推送或发布客户内容。

## 8. 阶段关系

| 阶段 | 唯一主要能力 |
| --- | --- |
| P0 | 可信现场、风险基线、Master SPEC 和轻量上下文 |
| P1 | 通用 Runtime、Vault Manifest 与 `content-slim` |
| P2 | `content-analyzer`、04 前置检索与 Gate A |
| P3 | `content-context-retriever` 与唯一 Context Pack |
| P4 | `content-writer` 与正文确认 |
| P5 | `content-publish-pack`、最终确认与安全保存 |
| P6 | 集成、两条真实任务和反重型化验收 |
| P7 | 构建、安装、迁移与远端发布 Gate |

每个 Session 只执行用户明确授权的一个阶段。阶段结束后必须停下，返回固定回执，等待 Review 和下一阶段授权。
