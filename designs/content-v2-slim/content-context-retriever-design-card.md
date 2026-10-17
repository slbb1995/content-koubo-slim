# `content-context-retriever` Skill 设计卡

## 名称

- Skill 名称：`content-context-retriever`
- 用户语言名称：客户内容上下文装配

## 唯一目的

在 Gate A 已由真人批准后，复用 P2 冻结的 04，按 `business_context_needs` 读取当前客户 Manifest 授权的少量 03，并按冻结的 `speaker_mode` 条件读取 05，生成 Writer 唯一可见的一份 Content Context Pack。

本 Skill 只做来源角色判断、相关性筛选、同行内容一般化和最小上下文装配。它不创建 Run、不搜索或改选 04、不扫描文件系统、不保存客户内容、不调用 Writer，也不生成正文、标题、发布正文或标签。

## 何时使用 / 何时不得使用

### 使用

- 当前 Run 状态为 `direction_approved`，且 `approved_direction.json` 可回读；
- P2 已冻结 `selected_method_assets`、`business_context_needs`、`speaker_mode`、`writer_mode` 和用户看到的 Gate A；
- 确定性程序已重新校验已选 04 的相对路径与哈希，没有重新搜索或改选；
- `business_context_needs` 非空时，程序仅从 Manifest 的 `knowledge_root` 返回最多 5 张 03 局部候选；为空时 03 候选必须为空；
- `personal_ip` 时程序提供唯一 active primary Profile；`company_brand` 和 `neutral` 时 Profile 输入必须为空。

### 不得使用

- Gate A 未批准、批准版本错绑，或 P2 已选 04 已变化；
- 需要重新搜索 04、修改方向、切换 `speaker_mode` 或切换 Writer 主模式；
- 需要扫描 Manifest 未授权范围、读取其他客户、整个 Vault、整篇历史稿或无关资料；
- 需要创建第二层 Pack、Reviewer、状态、真人确认点、任务句柄或临时程序；
- 需要调用 Writer、生成正文或进入 P4。

## 唯一输入 / 唯一输出

### 唯一输入：`context_retriever_input_v1`

输入由确定性程序在内存中装配并校验，不保存为第二份正式 Pack：

```json
{
  "context_version": "slim-1.0",
  "client_id": "configured-client",
  "speaker_mode": "personal_ip",
  "task_input": {
    "topic_original": "用户原始选题",
    "user_thoughts": null,
    "must_keep": [],
    "must_avoid": []
  },
  "approved_direction": {},
  "selected_external_reference_mechanisms": [],
  "selected_04_assets": [],
  "business_context_needs": [],
  "knowledge_candidates": [],
  "profile_candidate": null,
  "writer_mode": "ganhuo",
  "secondary_tactics": []
}
```

约束：

- `approved_direction`、外部参考机制、Writer 模式和辅助技巧必须逐项来自 `approved_direction.json`；
- `selected_04_assets` 只允许 P2 已冻结项，并保留 `peer_content_asset` / `oral_method_asset` 角色；
- `knowledge_candidates` 只允许 Manifest 授权的 03 局部候选，最多 5 张；没有业务需求或没有相关候选时为空；
- `profile_candidate` 仅在 `personal_ip` 出现，且只能是唯一 active primary Profile；
- 输入可包含程序校验所需的相对路径和哈希，但不得包含绝对路径、其他客户资料或整个 Vault。

### 唯一输出：`content_context_v1`

```json
{
  "context_version": "slim-1.0",
  "client_id": "configured-client",
  "speaker_mode": "personal_ip",
  "topic_original": "用户原始选题",
  "target_audience": "已批准受众",
  "approved_direction": {},
  "user_thoughts": null,
  "must_keep": [],
  "must_avoid": [],
  "selected_external_reference_mechanisms": [],
  "selected_04_content_assets": [],
  "selected_04_method_assets": [],
  "selected_03_business_assets": [],
  "profile_context": null,
  "source_role_policy": {},
  "writer_mode": "ganhuo",
  "secondary_tactics": []
}
```

这是唯一正式 Content Context Pack，也是 P4 Writer 唯一允许读取的输入。程序 create-only 保存为 `content_context_v1.json`；不再生成 Writing Context、Packet、Markdown 副本或第二层中转。

## AI 职责 / 程序职责

### AI 职责

- 只从程序提供的 03 候选中选择真正支持当前批准方向的局部内容；
- 将 P2 已选 04 分成内容资产与表达方法资产，不重新搜索、不替换、不增加；
- 把 04 中可借鉴内容转成通用判断或表达方法，不转移同行身份、经历、案例、公司业务、专属数据和识别性原句；
- 在 `personal_ip` 时只提取当前 Profile 中 Writer 真正需要的已确认片段，并保持本人事实、项目设定和候选素材边界；
- 删除重复和无关内容，说明每条上下文如何用于正文；
- 形成一份轻量 Context Pack，不改变已批准方向、受众、讲述者模式或 Writer 主模式。

### 程序职责

- 只接受受控 task-record，校验同 Run、`direction_approved` 状态和批准版本；
- 从 Manifest 解析 03/04/05 逻辑根，不接受 AI 或用户提供路径；
- 04 只按 P2 冻结的相对路径和哈希回读，禁止调用 04 搜索；
- `business_context_needs` 为空时不解析或读取 03；非空时只在 `knowledge_root` 检索，最多返回 5 张局部候选；
- `personal_ip` 解析并读取唯一 active primary Profile；另两种模式不解析、不读取 05；
- 校验 Skill 输入输出的来源绑定、角色分离、方向同值、Profile 条件和 04 一般化边界；
- 使用现有 Run Store create-only 写入唯一 `content_context_v1.json`，再沿现有状态集合从 `direction_approved → context_pending → context_ready`；
- 路径越界、客户错绑、Profile 缺失或多份、04 漂移、输出越界时 fail closed。

## 依赖工具

- 创建期：完整回读本设计卡后显式调用 `skill-creator`；
- 运行期：只接收 `content-slim` Runtime 准备的结构化输入；
- 确定性依赖：现有 `client_registry`、`client_manifest`、`run_store`、`state_machine`、`vault_search`、`vault_reader` 和 `schema_validation`；
- P3 不新增 Runtime 模块；仅使用 Python 标准库；
- 旧 Content V1 Skill 运行依赖为 0。

## 禁止访问范围

- P2 未选择的 04 页面和 Gate A 后的 04 全库搜索；
- `business_context_needs` 为空时的 03，或 Manifest 未授权的知识目录；
- `company_brand`、`neutral` 模式下的 05；
- 其他客户 Registry、Manifest、03/04/05 和输出；
- 整个 Vault、历史成稿、客户输出目录、`~/.codex/skills`、客户 RC、旧 V1 Run 和 Host 管理状态；
- Writer、P4/P5、Git、远端、构建、安装、保存和发布能力；
- 任何由 AI 临时生成的执行程序。

## 错误与返修

- 未批准方向、批准快照错绑、非 `direction_approved` 状态或 task-record 不可信时停止，不创建 Context Pack；
- P2 已选 04 路径、角色或哈希变化时停止，不重新搜索替代项；
- 03 没有同名资料不是错误，使用空业务资产继续，但不得虚构客户业务、案例、数据或承诺；
- `personal_ip` 缺少唯一 active primary Profile 时阻断；另两种模式不因 05 为空阻断；
- 03/05 与已批准核心立场、身份或 Writer 模式发生重大冲突时，不静默改方向、不进入 Writer，回到 Gate A；
- 输出改变已批准方向、选择未提供资产、混淆来源角色、复制同行专属内容或包含绝对路径时拒绝；
- Context Pack create-only 写入失败时保留当前 Run 和已有产物，在同一阶段重试，不创建新 Run 或第二份 Pack。

## 最小示例

1. 当前 Run 已批准 `direction_v1`，P2 冻结 1 张同行内容资产和 1 张口播方法资产；
2. 程序仅按已存相对路径和哈希回读这两张 04，不执行 04 搜索；
3. `business_context_needs` 指向一个客户服务问题，程序只在 03 返回 1 张相关局部候选；
4. `speaker_mode=personal_ip`，程序读取唯一 active primary Profile；
5. `$content-context-retriever` 选择相关 03、一般化 04、提取最小 Profile 片段，输出一份 `content_context_v1`；
6. 程序校验并 create-only 保存 `content_context_v1.json`，状态变为 `context_ready`；
7. P3 到此停止，不调用 Writer、不生成正文、不进入 P4。

## P3 验收标准

- 本设计卡先于 Skill 创建，已完整回读并通过 Master SPEC/PHASE-P3 边界校验；
- `skill-creator` 初始化命令、输出、源文件哈希和设计卡哈希可回读；
- P3 只新增 `content-context-retriever` 一个 Skill，新增 Runtime 模块为 0；
- 04 只按 P2 冻结清单与哈希回读，没有搜索、替换或新增；
- 03 只在 `business_context_needs` 非空时从授权根局部检索，最多 5 张；空需求和无相关结果都可继续；
- `personal_ip` 必须且只读取唯一 active primary Profile；`company_brand`、`neutral` 不读取 05；
- 03、04、05 来源角色分离，同行身份、经历、案例、公司业务、专属数据和识别性原句不转移；
- 只保存一份正式 `content_context_v1.json`，不生成第二层 Pack、Markdown 副本或 Writer 输入副本；
- Context Pack 不含绝对路径和内部哈希，保持已批准方向、受众、speaker_mode 和 Writer 模式同值；
- 状态集合不变，只使用既有 `direction_approved → context_pending → context_ready`；
- 新增真人确认点、Reviewer、对外操作、任务句柄、临时程序和旧 V1 调用均为 0；
- 一条真实黑盒 P3 路径先通过，再通过 P3 聚焦测试和必要 P1/P2 回归；
- P3 结束时只把 `project-state` 记录为 `P3 completed / review pending`，不得自行宣布 Gate P3 PASS 或进入 P4。

## 新增项的消费者与替代关系

| 新增项 | 保护的业务结果 | 消费者 | 替代的旧步骤 | 不增加时的可复现问题 | 为何不能并入其他职责 |
| --- | --- | --- | --- | --- | --- |
| `content-context-retriever` | 一份来源分离且够 Writer 使用的客户上下文 | P4 `content-writer` | V1 Request、Packet、trusted loader 与两层上下文中转 | Writer 要么扫 Vault，要么拿不到批准方向所需的客户资料 | 03/04/05 的语义选择与一般化是 P3 唯一 AI 职责 |
| `content_context_v1.json` | Writer 只有一个正式输入 | P4 `content-writer` | Context Pack + Writing Context 双层结构 | 多份中转会漂移、膨胀或改变已批准方向 | 单一 Pack 是 Slim 主链冻结合同 |
