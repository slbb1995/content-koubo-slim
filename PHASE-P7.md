# Content V2 Slim — PHASE P7

本阶段卡只摘录 Master SPEC 的 P7 要求和本次用户明确授权，不新增产品能力。执行前依次读取 `SLIM-COMPASS.md`、`project-state.json` 和本文件。Gate P6 通过与 `next: P7` 只表示可以申请进入 P7；只有用户明确授权 `EXECUTE_PHASE: P7` 才能执行。

## 1. 唯一业务结果

> 从固定干净提交完成可复算构建、可完整回滚的安装、客户配置迁移和真实安装验证，并停在最终 Review 前。

## 2. 前置条件

- 当前分支为 `feature/content-v2-slim`，工作树无未知修改；
- `project-state.json` 已正式记录 P6 Review 通过、`passed_gates` 包含 P6，并进入 P7；
- Master SPEC SHA256 与项目状态一致；
- 五个新 Skill、Skill Creator 证据、P6 真实运行证据和现有发布/Host 状态可回读；
- 客户 Registry、Vault Manifest、必要配置及其授权写入范围可精确定位；
- 用户明确授权 `EXECUTE_PHASE: P7`、提交并 push 当前 Factory 分支。

任一关键依赖不满足即停止，不用旧 V1 包或合成结果冒充 Slim 安装，不修改客户 01—05 业务资料。

## 3. 复杂度预算

- 新 Skill、产品 Runtime 模块、状态机状态、产品 Schema、Reviewer、真人确认点和对外内容操作均为 0；
- P7 只允许构建、安装、迁移、验证、回滚和有真实失败证据的最小修复；
- 不增加内容产品能力，不让新主链依赖旧 V1 Skill；
- 需要两个以上新产品概念时停止并请求架构决策。

## 4. 执行路径

1. 审计固定干净 Factory 候选与五个新 Skill 清单；
2. 从同一固定提交执行两次独立构建并逐字节比较；
3. 验证运行包只有 `content-slim`、`content-analyzer`、`content-context-retriever`、`content-writer`、`content-publish-pack`，旧 V1 运行依赖为 0；
4. 在临时 Host 完成安装、健康回读、回滚和再次升级；
5. 安装前 create-only 备份真实 Host 当前受管状态和目标 Skill，回读备份完整性；
6. 安装真实 Host 并执行健康回读；
7. 迁移客户 Registry、Vault Manifest 和必要配置，只更新配置与版本绑定；
8. 生成客户 RC 本地候选，不提交、不 push 客户仓库；
9. 在真实安装树上从新 Run 执行一条真实任务，依次验证方向、正文、配套与保存三个真人确认点和两份 create-only Markdown，保持未发布；
10. 回滚真实 Host，验证安装前状态完整恢复；必要时只按阶段目标重新安装已验证 Slim 候选；
11. 回读 Factory、构建包、真实 Host、客户 RC 与客户 Vault 配置的一致性；
12. 记录 Legacy V1 观察与退役条件、P7 证据、测试和复杂度回执；
13. 更新 `project-state.json` 为 `P7 execution completed / review pending`，提交并 push 当前 Factory 分支后停止。

## 5. 安装、迁移与真实任务边界

- 安装包只含 1 个入口和 4 个内部 AI Skill；确定性 Runtime 只随 `content-slim` 打包；
- 真实 Host 备份必须先于安装，备份须绑定文件清单、字节哈希和状态，回滚后逐项回读；
- Registry 只负责 `client_id → vault_root + manifest`；Manifest 只描述逻辑资产根、speaker_mode、Profile 选择、输出策略与版本绑定；
- 不修改客户 Vault 的 01—05，不把客户事实、IP 或绝对路径写入 Skill 源码；
- 真实验证只读 Manifest 授权的 03/04/05，只写授权输出目录，并用全新 Run、全新保存目标；
- 三个真人确认点必须逐项记录，结构校验不得冒充真人确认；
- 保存后保持 `publish_status=not_requested`，不 Git、不同步、不上传、不发布客户内容；
- 旧 V1 只作为安装前快照、回滚目标和审计证据，不进入 V2 Slim 运行依赖。

## 6. Gate P7

只有以下四类问题可以阻止 Gate：

1. 不能得到一致的五 Skill 构建，或真实安装任务不能完成三个确认点与双文件保存；
2. 存在串客户、配置越界、Vault 越界或旧 V1 隐性运行依赖；
3. 安装、迁移、保存或回滚会覆盖、丢失或错误冻结已确认内容与安装前状态；
4. 会跳过真人确认、自动发布、擅自 merge main、创建 Tag、发布或 push 客户仓库。

通过 Gate 还必须证明：双构建逐字一致；临时与真实 Host 安装验证通过；运行包精确为五个新 Skill；Skill Creator 证据齐全；客户 01—05 未修改；旧 V1 可完整回退。

用户已单独授权提交并 push `feature/content-v2-slim` Factory 分支；这不授权 merge main、创建 Tag、正式发布或 push 客户仓库。

## 7. 阶段回执与停止条件

在既有阶段回执中记录构建、安装、迁移、真实任务、回滚、四端回读和简短复杂度表。P7 不创建新的复杂度系统、独立 Reviewer或产品能力。

完成后只记录 `P7 execution completed / review pending`；不得自行宣布 Gate P7 PASS，不得 merge main、创建 Tag、发布或 push 客户仓库。提交并 push 当前 Factory 分支后停止，等待最终 Review。
