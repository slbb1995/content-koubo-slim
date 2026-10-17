# P7 构建、安装、迁移、真实任务与回滚证据

## 固定候选与构建

- P7 起始基线：`c986a8a0123b221efb4e54ffb4e93dacc89197ef`。
- 首个安装候选：`dc55451c8568c0ddd69821ac179590276187a19c` / `0.11.0-rc.1`。真实安装任务暴露现行 Profile 的结构化 CTA 列表无法被读取，候选已完整回滚，没有复用版本号包装为通过。
- 最小修复候选：`d1072d9b027131f2334a56598b2208e01be8ea91` / `0.11.0-rc.2`。只让现有 frontmatter 读取器接受非空结构化列表项，并把回滚证明收回五个目标 Skill 与旧控制文件；没有新增 Skill、产品 Runtime、状态、Schema、Gate 或内容能力。
- rc.2 两次独立构建逐字节一致：inventory SHA256 `4115f98dfe3c464a87ee8d7a3f6dd6f422178a07ab8ea0b540dc558e511c53b7`。

| 项目 | rc.2 结果 |
| --- | --- |
| 版本 | `0.11.0-rc.2` 本地候选 |
| Skill | 5 |
| 运行文件 | 34 |
| Manifest SHA256 | `785bd0ecb95e61dd9f37fe1ce91d1b2653ecbc0418ce8f2a0a9c2537756fc250` |
| Runtime tree SHA256 | `2899f94d44cd1d0d07fafacba4efd171670b919156d37d8d070a0d0157eae397` |
| Release tree SHA256 | `c038f37b2e1b75f46a66380b3eb472a863ed058557958fbbb4ac49cfa403ba24` |
| 旧 V1 运行依赖 | 0 |
| Skill Creator 收据 | 5 / 5 可回读 |

运行包只含：`content-slim`、`content-analyzer`、`content-context-retriever`、`content-writer`、`content-publish-pack`。旧 14 个 Content V1 Skill、5 个保险资产 Skill、测试、备份、缓存和客户资料均未进入包。

## 临时 Host

- 从真实 Host 复制旧 V1 控制文件和 19 个旧受管 Skill 到临时 Host；安装前新五 Skill 均不存在。
- 完成 `backup → install → doctor → rollback → install`；安装和最终 doctor 均为 `healthy`，回滚为 `rolled_back`。
- 临时 Host 旧控制状态和旧 19 Skill 保持，五个 V2 Skill 可完整移除和重新安装。

## 真实 Host

- rc.1 安装前 create-only 快照：`~/.codex/backups/content-v2-slim-p7-20260819T094039+0800`。
- rc.2 安装前 create-only 快照：`~/.codex/backups/content-v2-slim-p7-rc2-20260819T095353+0800`。
- 旧 Host contract SHA256：`3f3bdb47fef7faa7115aa06cb3c68596d54de216dc4cdea7ba741e058571b6a9`。
- 旧管理 state SHA256：`00e525875264966ec2275e96f967a719afac9ca53dc4c76034f3cd09ceeb1e30`；安装、两次回滚和重新安装后均未变。
- rc.2 真实安装最终回读：`healthy`，5 Skill / 34 文件，绑定 `d1072d9...` 和 runtime tree `2899f94d...`。
- Legacy V1 严格 doctor 仍为前置红灯 `INSTALLED_TREE_DRIFT`，本阶段未修复、删除或重签历史状态。

真实回滚时，其他用户 Skill 仓库同时存在独立清理/同步变化，因此全局非目标树哈希发生变化。P7 没有覆盖这些外部变化；回滚只精确验证和恢复五个目标目录，并逐字核对旧 Host contract 与 management state。rc.1 和最终 rc.2 都完成了真实 `rolled_back`；rc.2 回滚时五个目标均恢复为安装前的不存在状态，两份已保存内容保持原哈希，随后从同一 rc.2 快照重新安装并最终 `healthy`。

## 客户配置迁移

- Registry：`~/.codex/.content-v2-slim/client-registry.json`，SHA256 `aa79016c8a7a319f338ab4d679be98d4edf269226a9db494b62a2bfc87e4428f`。
- Manifest：`06-Agent与Workflow/content-v2-client-manifest.json`，SHA256 `a189f778b5702ebf6a743b49958eeac1e6a0f2b53336a61dfdfdac41d556dd59`。
- Registry 只保存 `client_id → vault_root + manifest`；Manifest 只保存 03/04/05/07 逻辑根、三种 speaker_mode、唯一 active primary Profile 选择和输出策略。
- 旧 `content-v1-client-config.json` 保持 SHA256 `c52d599ff8ae605a970721b3c984300d11a3953cb4b900f9011301631f559ede`，用于回退。
- 客户 RC 只生成未提交、未 push 的 `package-v2-slim/` 本地候选；其 verify 结果与 rc.2 构建哈希完全一致。
- 客户 Vault 01—05 没有 P7 写入。P0 已登记的 `WIKI04-SRC-20260719-009` 前置脏文件仍是唯一 01—05 Git diff；P7 只新增或修改 06 配置说明，以及 07 中首轮机器演练的两份输出和人工 Gate 修复的两份新输出。

## 人工 Gate 修复与真实安装任务

- 最终 Review 发现首轮 `run-20260819T014658.412810Z-89525c84` 的三个决定由执行 Agent 直接传入，不能证明真人确认。该 Run 与两份已保存文件完整保留并降级为机器演练：真人确认点计为 0，不作为 P7 Gate 通过依据，也不冒充客户批准。
- 首轮机器演练的两份文件未删除、未覆盖、未重签；口播稿 SHA256 仍为 `78776cb15e85531722d56b10c245a5f701a3acc5742e82188967c4b62549c86e`，配套文案 SHA256 仍为 `2c1b099fe8b5d3dd10e0e3d3aa26991af4c82ce66e3241f3fc919a0483664559`。
- 修复 Run：`run-20260819T042707.131601Z-e6c8ae07`。它使用新的业务选题表述和新的确定性 task-record 创建，全程只使用这一个 Run，未复用首轮 Gate、Context、Draft、Package 或批准 Artifact。
- 真实参考仍为 `WIKI04-SRC-20260719-053`，SHA256 `2eb82cb2f92a1afa48453a95432767e80b3336a0f83231efbea78ca9102c3643`。
- 受控读取：一张 Gate A 冻结的 04、一张 03 `WIKI03-SRC-20260803-052`、唯一 active primary Profile；未读取 01/02，未写 01—05。
- 三个真人停点逐次发生：完整展示方向后用户回复 `认可整版方向`；完整展示正文后用户回复 `确认正文`；完整展示配套后用户回复 `确认并保存`。每次只在收到该轮回复后进入下游，分别生成 `approved_direction.json`、`approved_draft.json`、`approved_package.json`。
- 三轮脱敏绑定、会话轮次与展示/批准 Artifact SHA256 见 `designs/content-v2-slim/p7-human-gate-evidence.md`，文件 SHA256 为 `cf1d8154a680efb1d7a17a69ffa9ecf68040293d31bdee03fd19f0e1f6ba18b5`；原始会话不复制进仓库，完整对话证据交回当前 ChatGPT Pro Review。
- 跨轮次约束只更新 Factory 真源 `skills/content-mainline/content-slim/SKILL.md`、设计卡和 Skill Creator 收据；本修复未重建、重装或重签 `0.11.0-rc.2`，既有构建与 Host 哈希继续按原候选如实记录，不把 Factory 文本修复冒充已安装新版本。
- 正常 Artifact：一份 `content_context_v1.json`；Run scratch 临时 `.py` 为 0；Reviewer Artifact 为 0；旧 V1 Skill 调用为 0。
- 最终状态：`saved`；`publish_status=not_requested`。
- 新口播稿 SHA256：`194c01e33c30dc62439be226df9e281d2ed876a85e153fcc172f6f861a6df03c`，与修复 Run 的 `draft_v1.md` 逐字一致。
- 新配套文案 SHA256：`cd3cc4462e75498a39fd5c44302770e2d8d7abee5357af88e3d207858d6519f3`。
- 新文件保存位置：`07-生产与反馈/内容成稿/EXAMPLE-CLIENT/2026 年 8 月第 3 周/示例口播-{口播稿,配套文案}.md`；两个目标均为保存前不存在的 create-only 文件。

首轮机器演练的 Analyzer 语义提交曾因客户阅读版与融合字段不完全一致而 fail-closed；同一 Run 内只修正提交字段。Profile 读取失败形成红测并触发上述 rc.2 最小修复。阶段式内部 CLI 仍带有“等待 P2/P3 Review”的旧提示语，但 P7 人工修复按既有内部适配器在同一新 Run 推进，没有新增用户决定、产品状态或内容能力。

## P7_REVIEW_FIX_2：rc.3 交付与证据闭环

### 固定来源与双构建

- `0.11.0-rc.3` 只从干净提交 `2d77d82cdeaccdb2c0a3db63efe8b4eecb22cc0a` 构建；构建开始时 Factory HEAD、本地分支和远端 `origin/feature/content-v2-slim` 均精确指向该提交。
- 两个独立输出目录逐文件 `diff` 无差异，verify 结果逐字段一致。

| 项目 | rc.3 结果 |
| --- | --- |
| Skill | `5` |
| 运行文件 | `34` |
| 旧 V1 运行依赖 | `0` |
| Manifest SHA256 | `ed4383e05f982e973ef84735d5e81043d060d11376c0fcb3f178b6ec3538aae9` |
| Runtime tree SHA256 | `23b09c5e101d160163293cd3ada0fc00f9fd7e702e06db8b75bef3f2447ae68e` |
| Release tree SHA256 | `0ff21ed291bc190c4b0c4720e246a156e3a06486ebb28a6fbdd5e78a0810b0a5` |
| `content-slim/SKILL.md` SHA256 | `4c5c2505f75563163d76b3b6f4b4e828f67b4aee0119105f2154f610df732874` |

运行包仍精确为 `content-slim`、`content-analyzer`、`content-context-retriever`、`content-writer`、`content-publish-pack`；没有加入旧 V1 Skill、测试、客户资料、缓存或额外运行依赖。

### 临时与真实 Host

- 临时 Host 完成 `backup → install → doctor → rollback → install → doctor`；两次 doctor 均为 `healthy`，回滚为 `rolled_back`，旧 Host contract、management state 和复制的 Legacy Skill 哈希逐字不变。
- rc.2 真实 Host 先用其既有 create-only 快照精确回滚五个目标目录；旧控制文件和 Registry 保持原哈希。
- rc.3 新 create-only 快照：`~/.codex/backups/content-v2-slim-p7-rc3-20260819T164436+0800`，快照时五个目标 Skill 均不存在。
- rc.3 安装和首次 doctor 为 `healthy`；真实安装树 `content-slim/SKILL.md` SHA256 精确为 `4c5c2505f75563163d76b3b6f4b4e828f67b4aee0119105f2154f610df732874`。
- 真实 Run 保存后完成 rc.3 `doctor → rollback → install → doctor`。回滚精确移除五个目标目录，旧 Host contract `3f3bdb47fef7faa7115aa06cb3c68596d54de216dc4cdea7ba741e058571b6a9`、management state `00e525875264966ec2275e96f967a719afac9ca53dc4c76034f3cd09ceeb1e30` 和 Registry `aa79016c8a7a319f338ab4d679be98d4edf269226a9db494b62a2bfc87e4428f` 始终未变；最终重新安装 rc.3 并保持 `healthy`。
- 回滚期间其他用户 Skill 仍存在独立变化，工具报告 unrelated tree drift；本阶段只记录前后哈希，不覆盖这些外部变化。

### 客户本地候选与版本绑定

- 客户 RC 的未跟踪 `package-v2-slim/` 已本地替换为 rc.3，verify 与 Factory 构建完全一致；仍未提交、未 push。
- 客户 Vault `Skill-Version.md` 已绑定 rc.3 的来源提交、Manifest、Runtime tree 和 Release tree；客户 `content-v2-client-manifest.json` 合同仍为 `2.0`，SHA256 仍为 `a189f778b5702ebf6a743b49958eeac1e6a0f2b53336a61dfdfdac41d556dd59`，没有扩展 Schema 或写入版本字段。
- P0 登记的 04 前置脏文件仍保留；本次没有修改客户 Vault 01—05，也没有提交或 push 客户 RC/Vault。

### rc.3 真实安装 Run

- 全新 Run：`run-20260819T084554.071263Z-622cd1b3`；只使用 rc.3 真实安装树和一个受控 task-record，未复用前两条 Run 的 Gate、Context、Draft、Package 或批准 Artifact。
- 三次完整展示分别结束 Assistant 轮次；只在下一条真实 User 消息后调用对应 `respond-direction`、`respond-draft`、`respond-package`。
- 六轮脱敏原始会话、消息/轮次引用和 Artifact 绑定见 `designs/content-v2-slim/p7-rc3-human-gate-evidence.md`，文件 SHA256 为 `581b00ed960c15385f0e453f94f1f828bd2823de19646357690d38323d80ff57`；原始 JSONL 未复制进仓库，完整展示留在当前 ChatGPT Pro Review 对话。
- 展示 / 批准 Artifact SHA256：方向 `897833efe3ce8dbc16fe48905e464abd50cb9ed5738dea2a588ca1668e024aac` / `2df37b241a5e67ddcb5e4d347c3ab98db93c05bd2748d98d859c72860e2aa13a`；正文 `70efb55a08656355aa11b8edab8f3775566619e5eecfec36940cff97094bafce` / `979f8b4e4dcc84e8ef94b37c491a10ef4d28b3e7729399decb18e9c25a563dfd`；配套 `ca0ec4aa8a3545696d6cd8dc066cc0dc88931fe705a89a4591042551712a4ea1` / `30cc7c305a1d547df2bd741caf3759cd33891c8159824dfc6ded94a06cf229dd`。
- 最终状态为 `saved`，`publish_status=not_requested`；一份 `content_context_v1.json`，无 Reviewer、无 Run scratch `.py`、无旧 V1 Skill 调用。
- 两份新 create-only 文件：`百万医疗险续保前，客服电话要问清哪四类条件？-{口播稿,配套文案}.md`。口播稿 SHA256 `70efb55a08656355aa11b8edab8f3775566619e5eecfec36940cff97094bafce`，与确认正文逐字一致；配套文案 SHA256 `e0dc512d6b6462226d01ffbcb9208876a2a94e122d14f886575b47321cbb34b7`。两份文件在真实 Host 回滚和重装后哈希不变。
- Gate A 前一次内部调用误把绝对 task-record 路径传给只接受受控相对 locator 的命令；Runtime 在创建方向 Artifact 前 fail-closed。纠正后复用同一 Run，没有新建替代 Run、覆盖 Artifact 或改变产品能力。
- 最终验证：P7 聚焦测试 `4/4 OK`，P1—P7 Slim 回归 `102/102 OK`，五个 Skill `5/5 valid`；Factory 五 Skill 源码树、rc.3 构建包和真实安装树均无 Python 缓存。`tests/p1`、`tests/p2` 下两份时间为 2026-08-17 的前置 ignored `.pyc` 保持不动，不进入 Git、构建包或安装树，也不包装成本轮产物。

## 远端与停止边界

- Factory 当前分支按用户本轮授权提交并 push；不 merge main。
- 客户 RC 不提交、不 push；客户 Vault 不提交、不 push。
- 未创建 Tag，未正式发布构建包，未上传或发布客户内容。
- Legacy V1 只有在 P7 最终 Review 通过、另行批准的稳定观察期完成、回滚快照再次验证且用户再次授权后，才可讨论删除或归档。本阶段保留全部旧 Skill、配置、Run 和证据。

## 最终独立 Review 与主线 PR 授权

- 最终独立 Review 结论：`PASS`。
- 固定审核提交：`2c284b708be34f016057530195bee2d82fbd09c4`。
- Review Session：`codex-session:01a0199f-2157-7a00-a66b-1b6034be53e9`。
- 远端 `feature/content-v2-slim` HEAD 在收口前回读为同一提交；两者完全一致。
- 用户已明确授权进入主线 Draft PR 阶段；该授权不包含合并 PR、创建 Tag、正式 release、发布客户内容或 push 客户仓库。
