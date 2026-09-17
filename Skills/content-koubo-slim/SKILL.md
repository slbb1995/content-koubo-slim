---
name: content-koubo-slim
description: Content 口播 Slim 的唯一用户入口。使用已连接的 Obsidian 或飞书知识库，开始、继续、恢复或查看单篇或多篇短视频口播任务，每篇以独立 Run 协调状态、版本和方向、正文、配套三次真人确认；确认配套后 create-only 保存纯口播稿和发布配套两份产物并保持未发布。仅做编排；不得亲自拆解、检索语义、写稿、发布或调用旧 Content V1 Skill。
---

# Content 口播 Slim

## 一句话目的

用一个入口管理单篇或多篇 Content 口播 Slim 任务，每篇独立推进；P5 推进到配套确认和两份产物安全保存：Obsidian 为两个 Markdown 文件，飞书为两份云文档，然后保持未发布并停下。

## 什么时候使用

- 开始或恢复单篇口播或多篇任务；
- 查看当前任务状态；
- 记录方向的认可、普通修改或不采用；
- 生成正文后记录“确认正文”或带具体意见的“需要修改”；
- 生成配套后记录“确认并保存”或带具体意见的“需要修改”；
- 配套确认后调用确定性保存，分别写入并回读纯口播稿、发布配套两份产物；
- 通过确定性 Runtime 复用同一个 Run、保存版本并推进合法状态。

## 什么时候不要使用

- 建设客户知识、内容方法或个人资料资产；
- 直接拆解对标、判断资料语义、写正文或生成配套文案；
- 构建、安装、发布、Git 操作或 Host 修复；
- 自己读取 03/05、写 Context Pack、正文、配套或客户保存。

## 输入

先理解这次要交付多少篇、是否全部保留，还是生成多个候选后选一篇。“出10版/三条不同角度”属于任务数量和组织要求，不是正文的 `must_keep`。普通改稿仍是原稿修订；多篇交付使用[多篇任务](references/batch-tasks.md)，每篇独立确认、配文和保存，不能拼成一篇或用修订版本代替篇数。数量或候选用途确实不清才询问；不要让客户填写内部批次字段。

一个文件包含多篇对标时，按[逐篇参考准备](references/reference-pieces.md)登记原文边界，再进入 Analyzer。不要把“一份文档”直接等同“一篇对标”。

单篇内容输入包含：

```json
{
  "topic": "用户原始选题",
  "references": [],
  "user_thoughts": null,
  "must_keep": [],
  "must_avoid": []
}
```

可选显式提供 `binding_id`、`client_id`、`speaker_mode` 和本次 `profile`。默认先读取公共 Registry `~/.codex/.content-workflows/knowledge-base-registry.json`，没有公共配置时兼容旧 `.content-koubo-slim/client-registry.json`。公共与旧配置指向不一致时停止；不扫描电脑或猜测知识库。

客户可以只给一段想法。`references` 为 0—5 篇本地 MD/TXT；没有参考不是输入错误，也不要求客户补结构编号。先区分用户要表达的观点和仅供 AI 执行的写作要求；`must_keep` 只放用户明确要求进入成稿的内容，不把“按这个结构写、先找同行”等操作指令当正文。

`personal_ip` 支持选择当前知识库任意 active Profile。顺序是：本次明确指定 → 已确认的口播默认 → primary → 唯一 active → 要求选择；primary 只是默认。选中的 `profile_id`、对象引用和内容哈希进入 Run 身份，换 IP 必须新建 Run。

确定性程序根据冻结的 binding、Profile、讲述模式、用户原始选题和参考来源集合生成 task-record；后续内部操作只接受已经落盘并通过完整性校验的相对句柄。不得让用户填写或让 AI 临时编造。

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

1. 从公共或兼容旧 Registry 定位一个已连接的 binding；Obsidian 使用本地根，飞书使用空间和文档引用，原生读取 Manifest 与 Profile 索引，不猜本地同步目录。需要检查连接时使用 `preflight`，不创建 Run；尚未连接口播的已有飞书 binding 使用 `configure-feishu` 零写入预览，明确授权后才定向合并口播配置；
2. 校验 Manifest、Profile 索引，解析 `speaker_mode` 和本次 Profile；
3. 在创建 Run 前验证所有显式参考可读；显式给出的参考失效时停止，不静默切换库内来源；没有外部参考时进入库内选材；
4. 调用 `$content-koubo-analyzer` 的选材阶段，用 `discover-methods` 返回的同库少量目录与完整候选做语义判断。先找同行的问题、观点和内容价值，再按需要结合结构；有外部参考时优先分析用户参考。入口只传递资料和选择结果，不亲自做语义分析。细则读 `references/idea-first-materials.md`；
5. 将内部选择文件传给 `start --method-selection`；程序回读并校验最多 3 张同行、2 张方法和 3 份选材指引，冻结来源、哈希、原始想法和业务身份后创建或恢复 Run。有外部参考时 04 可空；无外部参考且没有可采用 04 时说明缺口并停止，不虚构素材；
6. 把标准化参考和 04 候选交给 `$content-koubo-analyzer`，接收完整结果后生成一次 Gate A；
7. Gate A 修改前由 AI 判断是否根本改变原始选题、目标受众、核心承诺、参考集合、客户或讲述者；根本变化时在现有 `respond-direction` 内部交接设置 `--task-identity-changed`，由程序要求新 Run；普通修改才在同一 Run 生成下一版，且 `direction_vN` 只消费同版本 `analyzer_input_vN`；
8. 认可时冻结用户实际看到的同版本 Gate A 或其确定性投影，不采用时结束；
9. Gate A 批准后，程序只按冻结清单回读 04，按业务需求读取少量 03，并在 `personal_ip` 模式只读取本次选定的 05 Profile；
10. 调用 `$content-koubo-context-retriever` 形成唯一 `content_context_v1.json`，校验并进入 `context_ready`；
11. P4 只把这份 Context Pack 交给 `$content-koubo-writer`，按冻结值加载一份 `ganhuo / huati / zhuanhua` 主模式规则；
12. 程序把 Writer 的自然段输出 create-only 保存为同版本 `draft_vN.json` 与 `draft_vN.md`，完整展示正文；
13. 用户选择“需要修改”时，保留旧版本，在同一 Run 用当前正文、同一 Context Pack 和本次具体意见生成下一版；
14. 用户选择“确认正文”时，程序生成绑定该正文版本的确认记录（首份兼容 `approved_draft.json`） 并进入 `draft_approved`；
15. P5 重新校验已确认正文，只把正文交给 `$content-koubo-publish-pack`，生成一份含 2 个封面标题、3 个发布标题、推荐项、默认 50—100 字、可按用户要求调整的发布说明和 5 个标签的 `package_vN.json`；
16. 用户选择“需要修改”时，保留旧版本，在同一 Run 用当前配套、同一已确认正文和本次具体意见生成下一版；
17. 用户选择“确认并保存”时，默认使用推荐标题，也可选当前其他候选；程序固定绑定当前配套版本的确认记录（首份兼容 `approved_package.json`），不再询问一次是否保存；
18. 程序重新校验 Registry、Manifest、Profile 索引及 P3 实际读取的 03/04/05 哈希，再从 Manifest 推导输出根，create-only 写入两份文件并分别回读；
19. 只有两份文件都成功才进入 `saved`；结果始终保持 `publish_status=not_requested`，P5 停止，不进入 P6。

## 真人停点

完整产品只有三个真人停点：方向、正文、配套与保存。P5 启用第三个真人停点，必须先完整展示配套，再接受“确认并保存”或带具体意见的“需要修改”；确认动作立即保存，不增加第四次询问。

Gate A 只接受：`认可整版方向 / 需要修改 / 不采用`。正文确认只接受：`确认正文 / 需要修改`。配套确认只接受：`确认并保存 / 需要修改`。程序校验不代替真人选择。

展示 Gate A 时，只把 Runtime 同版结果确定性归并成五组客户内容，不另做第二次分析：谁来说、讲给谁；核心观点和承诺；对标准备保留什么；哪些内容不照搬；准备怎么讲。五组必须与同版详细拆解报告一致；客户确认后，Runtime 将该版本的逐篇内容价值、钩子、结构、可迁移项、禁止迁移项和冲突处理投影进唯一 Context Pack，Writer 必须按详细蓝图执行，不能只根据五组摘要写作。展示后仍只接受既有三个选择，不增加确认拆解或确认资料等新 Gate。

每次完整展示方向、正文或配套 Gate 后，必须立即结束当前 Assistant 轮次；展示 Gate 的同一轮次禁止调用 `respond-direction`、`respond-draft` 或 `respond-package`。收到下一条真实用户消息后，先用原样 task-record 查询当前 Run 状态；普通确认走对应 `respond-*`，明确要求修改已确认/已保存正文时走 `respond-draft` 的修订分支；不得按上一轮的记忆猜入口。只有该消息明确包含当前 Gate 允许的决定或具体修改意见后，才可调用对应 `respond-*`。对合法选择只去除首尾空白和句末常见中英文标点；“随便”“差不多”等模糊表述仍不视为确认。Agent 不得代写、推断、预填或从阶段授权、测试授权、结构校验、既有记忆中派生批准决定。

## 错误与停止

- 任意 CLI 字符串被当作宿主身份或 task-record 时，在创建 Run 或恢复前停止；
- Registry、Manifest、Run 索引、参考来源或 `method_root` 不可信时立即停止；
- Registry 含多个可用知识库且没有工作流默认或显式选择时停止；多个 active IP 且没有默认或显式选择时也停止；
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
- P2 调用 `content-koubo-analyzer`；P3 调用 `content-koubo-context-retriever`；P4 调用 `content-koubo-writer`；P5 只新增并调用 `content-koubo-publish-pack`；
- 不增加 Reviewer、第二层上下文包或临时程序；
- 不扫描未授权目录，不把客户名、行业或物理路径写死进共享 Skill；
- Writer 只允许读取一份 `content_context_v1.json`；不调用三个旧 Writer，不搜索 Vault，不重选模式；
- 配套 Skill 不读取 Vault、不修改或重复输出已确认正文；
- P5 只写 Manifest 授权输出根下的两份最终产物，不修改客户 01—05；飞书只保存到授权的 07 下，两个文档全部回读匹配才完成；
- 不调用旧标题、分发或保存 Skill，不增加 Reviewer、状态、发布能力或 P6 产物；
- 不修改客户 RC、Host、main、Tag，不执行客户内容的 Git、推送、同步、上传或发布。

## 最小示例

正文 `draft_v2` 已确认后，P5 只根据它生成 `package_v1` 并展示。用户给出具体意见时，在同一 Run 生成 `package_v2`，旧版保留；用户确认并默认采用推荐标题后，程序一次保存纯口播稿和配套文案，两份都回读成功才完成，结果保持未发布。

## 文件导航

- `scripts/content_koubo_slim.py`：方向、Context Pack、正文、配套版本与三次真人确认的编排；
- `runtime/content_source.py`、`client_registry.py`、`client_manifest.py`：公共合同、独立配置器、知识库和任意 active Profile 选择；
- `runtime/run_store.py`、`state_machine.py`：锁、单 Run、正文/配套版本和状态；
- `references/idea-first-materials.md`：一段话起步、内部语义选材和指引冻结；
- `runtime/reference_prep.py`：0—5 篇显式参考的独立准备；
- `runtime/vault_search.py`、`vault_reader.py`：Manifest 限定的 04 搜索/回读，以及 P3 授权 03 的局部检索和条件 05 回读；
- `runtime/schema_validation.py`：Analyzer、Gate A、唯一 Context Pack、正文与配套输出边界；
- `runtime/vault_save.py`：Manifest 授权输出根下的双文件 create-only 保存与回读；
- `runtime/local_save_receipt.py`、`references/local-save-recovery.md`：本地保存回执、已核验文件复用和未知结果停止边界；
- `references/feishu-backend.md`：飞书配置、只读预检、来源边界与双文档失败恢复；
- `runtime/error_model.py`：用户响应与技术记录分离；
- `schemas/`：公共 Registry、Manifest、Profile 索引与旧 v2 兼容合同。

设计原因保存在 Factory 设计卡；实现细节读 `runtime/`；字段约束读 `schemas/`。不要把这些内容复制回本文件。

## 客户修订与宿主运行

- 调用入口脚本时，WorkBuddy 明确使用 `python3 scripts/content_koubo_slim.py --host workbuddy <命令>`，Codex 使用 `--host codex`；不同安装位置、测试环境可用 `--host-root <已确认的绝对目录>`。宿主参数适用于所有子命令，不改变已显式传入的 registry/runs-root。脚本自动以 Python 隔离模式重新启动，避免 PYTHONPATH/sitecustomize 注入干扰本地读写；不让客户手工改环境变量，不把客户目录写入 Skill。
- 先检查安装版本、任务所在宿主和原始句柄。历史任务保持原路径，不能因报错另建任务或自动切换另一个宿主。运行记录损坏、权限不足等真实错误仍需准确报告，不一律解释为 Python 注入。
- 用户明确要求调整已确认或已保存的正文时，复用原 task-record，调用 `respond-draft` 的“需要修改”并传具体意见；支持扩写、缩短、改结尾、纠错。程序返回当前正文与原 Context，Writer 生成下一版；不得告知“确认后锁死，只能从头来”。选题、客户、讲述者或方向根本变化才新开方向流程。
- 改稿不重做已经有效的方向确认；新正文必须完整展示并再次确认，然后基于新正文重新生成、展示、确认配套。旧稿、旧确认记录及旧保存文件全部保留；新版文件带正文版本标记。修改开始后，旧配套不得直接用于新正文的保存或下游制作。
- 发布说明默认 50—100 字，用户的明确长度/格式要求可通过首次或后续配套的 feedback 传入；不要把它解释成口播字数。用户要求口播时长时，在正文确认前给出字数和按实际语速估算的时长区间；不能承诺精确秒数。
- 一篇口播须有自然收尾。普通观点总结或与主题有关的评论交流不应被商业转化规则一律禁掉；按用户当次要求及已有项目偏好执行。引流私信、领取、预约、购买、免费和名额等仍须有相应事实与授权，不由程序自造。

配套结果提交必须把 `prepare-package` 返回的 `approved_draft.draft_version` 原样作为 `record-package --based-on-draft-version` 传回；不得在提交时改填当前版本。正文已修改后，旧配套结果必须丢弃并重新生成。

对外只展示当前业务进度、方向、正文、配套与实际保存结果；不把内部思考、工具日志或调试标记当交付内容。正文提交前由 Writer 检查确为本篇单条可录口播；程序格式校验不能代替语义检查。
