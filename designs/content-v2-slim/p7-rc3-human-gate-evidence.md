# P7 rc.3 真人 Gate 六轮脱敏证据

本文件只服务 `P7_REVIEW_FIX_2` 的最终 Review，不是产品 Artifact、客户批准收据或发布授权。首轮机器演练、既有失败证据和前一次真人修复 Run 均保持原样；本文件只绑定 rc.3 真实安装树上的全新 Run。

## 证据边界

- Run：`run-20260819T084554.071263Z-622cd1b3`。
- 安装候选：`0.11.0-rc.3`，固定来源 `2d77d82cdeaccdb2c0a3db63efe8b4eecb22cc0a`。
- 原始会话引用：`codex-session:01a01819-2918-7882-b846-2a4044c8c840`。
- 原始 JSONL 不复制进仓库。下表只保存六个消息的行号、消息 ID、轮次 ID、原始文本 SHA256 和脱敏片段；方向、正文、标题、客户身份、客户资料及本机绝对路径均不进入本文件。
- Assistant 原始文本 SHA256 对完整展示消息的 UTF-8 原字节计算；User 原始文本 SHA256 保留会话 JSONL 中的结尾换行及第三轮决定在换行前的一个空格。
- 完整三次展示保留在当前 ChatGPT Pro Review 对话；Reviewer 可按会话引用、行号、消息 ID 和 Artifact SHA256 逐项回读。

## 六轮原始会话片段与 Artifact 绑定

| 顺序 | 角色 / Gate | 会话行 | 消息与轮次引用 | 脱敏原始片段 | 原始文本 SHA256 | Artifact 绑定 |
| ---: | --- | ---: | --- | --- | --- | --- |
| 1 | Assistant / 方向展示 | `993` | `msg_0f6102ae3e02cc9e016a856dc5ee3087d1800b4eefe7e9c736` / `turn:01a0192f-1755-7272-890d-56f1b2b52b15` | `[完整方向 Gate 已展示；业务内容脱敏。末尾只给出认可、修改或不采用三种选择。]` | `92a58761cc279a0dffbbfa89e424c17fe82c68460482e48ac95fd0f97db2bb65` | `artifacts/direction_v1.json` → `897833efe3ce8dbc16fe48905e464abd50cb9ed5738dea2a588ca1668e024aac` |
| 2 | User / 方向决定 | `1002` | `msg_01a0193d-73ee-7100-b074-38573fcbc3f4` / `turn:01a0193d-6e64-7430-a7eb-57210829f547` | `认可整版方向\n` | `cb9b3eda98177bca97b3d45a83bfd2d1896a56916e07519f97f020eb5668a36c` | `respond-direction` 仅在后续行 `1012` 调用；`artifacts/approved_direction.json` → `2df37b241a5e67ddcb5e4d347c3ab98db93c05bd2748d98d859c72860e2aa13a` |
| 3 | Assistant / 正文展示 | `1057` | `msg_0f6102ae3e02cc9e016a8570787dac87d1b09435e7b4e8e017` / `turn:01a0193d-6e64-7430-a7eb-57210829f547` | `[完整正文已展示；正文脱敏。末尾只给出确认正文或具体修改两种选择。]` | `ef140abf89da425ae43c467ce3615407c8964bce038295c1da20ca27667943a5` | `artifacts/draft_v1.md` → `70efb55a08656355aa11b8edab8f3775566619e5eecfec36940cff97094bafce` |
| 4 | User / 正文决定 | `1064` | `msg_01a01940-28d7-7a03-a3a1-57f68861e214` / `turn:01a01940-24bb-7d43-bec4-c6b6b15aa327` | `确认正文\n` | `e0c38c73bf61908d98737a6ba44760cbd869fc4b7dd5903f4a46297fa7dbe68b` | `respond-draft` 仅在后续行 `1074` 调用；`artifacts/approved_draft.json` → `979f8b4e4dcc84e8ef94b37c491a10ef4d28b3e7729399decb18e9c25a563dfd` |
| 5 | Assistant / 配套展示 | `1088` | `msg_0f6102ae3e02cc9e016a8570dc649087d197f2aa12b7922515` / `turn:01a01940-24bb-7d43-bec4-c6b6b15aa327` | `[完整配套已展示；标题与发布文案脱敏。末尾只给出确认并保存或具体修改两种选择。]` | `f27eef2385d85a9440c127db25e120730006cbe5a4c03cf51f51fd59efa1d7fd` | `artifacts/package_v1.json` → `ca0ec4aa8a3545696d6cd8dc066cc0dc88931fe705a89a4591042551712a4ea1` |
| 6 | User / 配套与保存决定 | `1095` | `msg_01a01941-ec4c-7a93-916e-32c47a2fd525` / `turn:01a01941-e7fe-7ec3-8a94-af8300316a45` | `确认并保存 \n` | `9210cc0f51ce92d668590a505344ffd7878c0ac02fddbc2fbe8d4ef86cb7cc10` | `respond-package` 仅在后续行 `1101` 调用；`artifacts/approved_package.json` → `30cc7c305a1d547df2bd741caf3759cd33891c8159824dfc6ded94a06cf229dd` |

## 结果与负证据

- 三个展示消息均先结束 Assistant 轮次；三个 `respond-*` 均在下一条真实 User 消息之后调用。
- Run 最终 `state=saved`，`publish_status=not_requested`；口播保存文件 SHA256 为 `70efb55a08656355aa11b8edab8f3775566619e5eecfec36940cff97094bafce`，与 `draft_v1.md` 逐字一致；配套保存文件 SHA256 为 `e0dc512d6b6462226d01ffbcb9208876a2a94e122d14f886575b47321cbb34b7`。
- Gate A 前曾把绝对 task-record 路径误传给内部命令；Runtime 在创建方向 Artifact 前 fail-closed。纠正为受控相对 locator 后继续同一 Run，没有新建替代 Run、覆盖 Artifact 或把失败包装为通过。
- 首轮机器演练 `run-20260819T014658.412810Z-89525c84` 仍计真人确认点 0；前一次真人修复 `run-20260819T042707.131601Z-e6c8ae07` 及其证据均未删除、覆盖或重签。
