# `content-writer` Skill 设计卡

## 名称

- Skill 名称：`content-writer`
- 用户语言名称：口播正文写作

## 唯一目的

在同一 Run 已生成唯一 Content Context Pack 后，按 Gate A 冻结的一个 `ganhuo / huati / zhuanhua` 主模式和少量辅助技巧，生成、修改并交给用户确认可直接朗读的口播正文。

本 Skill 只决定正文怎么说。它不创建 Run、不检索 Vault、不重选 Writer 模式、不修改已批准方向、不调用旧 Writer 或 Reviewer，也不生成标题、发布正文、标签、配套文案、保存或发布结果。

## 何时使用 / 何时不得使用

### 使用

- 当前 Run 状态为 `context_ready`，且唯一 `content_context_v1.json` 可回读；
- Context Pack 仍绑定当前客户、原始选题、批准方向、讲述模式、Writer 主模式和用户边界；
- 首稿只读取 Context Pack；修改稿额外接收当前正文与本次真人修改意见，但不创建第二份输入包；
- 只加载公共规则和当前冻结主模式的一份 mode reference。

### 不得使用

- Gate A 未批准、Context Pack 缺失、错绑、已变化或存在第二份正式输入包；
- 需要重新搜索 03/04/05、读取历史稿、网络、其他客户资料或客户输出目录；
- 需要重新选择主模式、同时加载三份模式、创建第四个混合 Writer；
- 需要生成配套文案、保存、发布、调用 Reviewer 或进入 P5。

## 输入 / 输出

### 唯一正式输入：`content_context_v1.json`

Writer 只使用 P3 保存的唯一 Context Pack。首稿不读取其他业务资料。修改稿可额外看到：当前 `draft_vN` 正文和用户这一次的自然语言修改意见；两者只是当前修改动作，不形成新的 Writer Pack、Schema 或长期任务句柄。

Writer 必须原样服从 Context Pack 中的：

- `topic_original`、`target_audience` 和 `approved_direction`；
- `user_thoughts`、`must_keep`、`must_avoid`；
- 03/04/05 已选片段及 `source_role_policy`；
- `speaker_mode`、`writer_mode` 和 `secondary_tactics`。

### AI 唯一输出：正文段落

```json
{
  "paragraphs": [
    {"text": "可直接朗读的自然口播正文。"}
  ]
}
```

AI 不输出版本号、哈希、状态、标题、标签、审核说明、事实账本或保存信息。程序校验后 create-only 保存同版本：

```text
draft_vN.json
draft_vN.md
```

用户确认时，程序另生成固定的 `approved_draft.json`，绑定用户实际看到的最新正文版本。它是正文确认收据，不是第二份正文或 Writer 输入。

## 公共写作规则

- 为耳朵写：短句为主，一句话推进一个主要意思，转场来自语义，不写报告、Markdown 标题或编辑说明；
- 开头尽快进入目标观众的具体问题、处境或判断，正文兑现 Gate A 的核心承诺；
- 只使用 Context Pack 已提供的客户业务与讲述者片段；缺少客户专属事实时使用一般性或条件性表达，不补造产品、数据、案例、身份、关系或结果；
- 04 只迁移通用内容价值和表达方法，不复制同行身份、经历、业务、案例、专属数据或识别性长句；
- 真实归属故事必须有 Profile 片段支持；关系未知用中性说法，假设场景要让观众听出是假设；
- `must_keep` 自然进入正文，`must_avoid` 不得出现；不得把原题换成更安全但无关的话题；
- 不使用内部流程词、空泛企业术语和工整 AI 套话，不靠恐惧、羞辱、假稀缺或结果保证推动观众；
- 没有明确获准的转化动作时自然结束；P4 不自行增加关注、评论、私信、领取、咨询或购买引导；
- 正文确认前不生成配套，确认后也由 P5 处理，本 Skill 到正文为止。

## 三种主模式

### `ganhuo`

让观众学会、理解或会判断。优先交付具体判断、步骤、检查问题、取舍条件或可执行动作；结构服务内容，不机械凑三点、清单或边界。

### `huati`

让观众对一个现象、冲突、情绪或两难形成更清楚的理解。围绕一个真实张力推进，情绪、故事和解释服务同一判断，不为结构完整硬造反方、金句或讨论问题。

### `zhuanhua`

先解决一个具体问题，再在 Context Pack 明确支持时自然承接一个动作。删掉最后动作后，正文仍应值得听；P4 没有明确动作授权时自然结束，不补第二动作或销售承诺。

三个模式共享公共底座，但每次只读取当前冻结主模式的一份 reference。辅助技巧只能局部影响开头、节奏或收束，不能变成第二主模式。

## AI 职责 / 程序职责

### AI 职责

- 根据冻结主模式选择最自然的内容推进方式；
- 把 Context Pack 的已选片段转成口语正文，删除重复和无关信息；
- 在不改变方向、身份、来源角色和用户边界的前提下生成或修改正文；
- 输出唯一 `paragraphs` 对象，失败时只返回简短阻断原因，不生成半篇正文。

### 程序职责

- 只接受受控 task-record，校验同 Run、`context_ready / draft_pending` 状态和唯一 Context Pack；
- 保持客户 Vault 与 Manifest 绑定，不向 Writer提供路径、搜索或 Vault 工具；
- 校验 AI 输出只含非空正文段落并生成一致的 JSON/Markdown；
- create-only 写入 `draft_vN.json` 与 `draft_vN.md`，旧版本不得覆盖；
- 修改时绑定当前最新正文和本次真人意见，仍使用同一 Context Pack；
- 用户确认时生成 `approved_draft.json` 并从 `draft_pending` 进入既有 `draft_approved`；
- 非法状态、版本覆盖、空修改意见、Context Pack 错绑或试图进入 P5 时 fail closed。

## 依赖工具

- 创建期：完整回读本设计卡后显式调用 `skill-creator`；
- 运行期：只接收 `content-slim` 准备的 Context Pack、可选当前正文和本次修改意见；
- 确定性依赖：现有 `run_store`、`state_machine`、`schema_validation` 和 `error_reporting`；
- P4 不新增 Runtime 模块，仅扩展现有模块；
- 三个旧 Writer 的运行依赖为 0。

## 禁止访问范围

- Registry、Manifest、03/04/05 物理目录、整个 Vault、历史成稿、网络和其他客户资料；
- 三个旧 Writer 的运行调用、旧 V1 Packet、trusted loader 和 Reviewer；
- P5 的标题、发布正文、标签、保存和发布能力；
- 客户 Vault、客户 RC、Host、Git、远端、构建和安装；
- 任何由 AI 临时生成的执行程序。

## 错误与返修

- Context Pack 缺失、重复、错绑或 Run 非法时停止，不生成正文；
- 主模式不是 Context Pack 冻结值，或要求同时加载多个主模式时停止；
- 核心承诺必须依赖缺失的客户专属事实时，不换题、不虚构，说明缺口并回 Gate A；
- AI 输出为空、包含额外字段或无法直接朗读时拒绝保存，保留当前 Run 和已有版本；
- “需要修改”必须有具体真人意见；在同一 Run 基于最新正文生成下一版，不覆盖旧版；
- “确认正文”只确认用户实际看到的最新版本；重复确认或确认旧版本时停止；
- 任一失败不创建配套、不进入 P5。

## 最小示例

1. 当前 Run 为 `context_ready`，唯一 Context Pack 冻结 `writer_mode=ganhuo`；
2. 程序只把这份 Context Pack 交给 `$content-writer`，并只加载公共规则与 `modes/ganhuo.md`；
3. Writer 输出自然段正文，程序保存 `draft_v1.json` 与 `draft_v1.md`，状态变为 `draft_pending`；
4. 用户说“第二段太绕，改成一个能马上照做的判断问题”，Writer 在同一 Run 读取 Context Pack、`draft_v1` 和该意见，生成 `draft_v2`；
5. 用户确认 `draft_v2`，程序生成 `approved_draft.json`，状态变为 `draft_approved`；
6. P4 到此停止，不生成标题、发布正文或标签。

## P4 验收标准

- 本设计卡先于 Skill 创建，已完整回读并通过 Master SPEC/PHASE-P4 边界校验；
- `skill-creator` 初始化命令、输出、源文件哈希和设计卡哈希可回读；
- P4 只新增 `content-writer` 一个 Skill，新增 Runtime 模块为 0；
- 公共规则与三种 mode references 分离，三种主模式均可用且每次只加载一个；
- Writer 正式输入只有唯一 Context Pack，修改动作不创建第二份 Pack；
- 正文可直接朗读，不搜索 Vault、不改变方向、不调用 Reviewer或旧 Writer；
- `draft_v1/v2/v3` 留在同一 Run，JSON/Markdown 同版本一致且旧版本可回读；
- 正文确认只绑定最新可见版本，未确认不得进入 P5；
- 新增状态、真人确认点、Reviewer、Runtime 模块、P5 产物和旧 V1 运行调用均为 0；
- 一条真实黑盒 P4 路径先通过，再通过 P4 聚焦测试和必要 P1—P3 回归；
- P4 结束时只记录 `P4 completed / review pending`，不得自行宣布 Gate P4 PASS 或进入 P5。

## 新增项的消费者与替代关系

| 新增项 | 保护的业务结果 | 消费者 | 替代的旧步骤 | 不增加时的可复现问题 | 为何不能并入其他职责 |
| --- | --- | --- | --- | --- | --- |
| `content-writer` | 一份按已确认方向生成、可修改和确认的口播正文 | 用户与 P5 `content-publish-pack` | 三个旧 Writer 与 V1 Packet 运行链 | Writer 要么依赖旧重链，要么自行重选模式和搜索资料 | 写正文是独立语义职责，不能并入检索或配套生成 |
| `draft_vN.json / .md` | 同 Run 正文版本可回读且不覆盖 | 用户、正文确认与 P5 | 机器 Source、Draft、Review 多层中转 | 修改会覆盖正文或缺少用户可见版本绑定 | JSON 保护版本与绑定，Markdown 是用户实际确认的正文 |
| `approved_draft.json` | 正文确认绑定用户实际看到的版本 | P5 `content-publish-pack` | Gate B 与独立 Review 收据 | P5 无法确定哪一版正文获准进入配套 | 这是既有第二真人确认点的确定性收据，不是新 Gate |
