# P7 真人 Gate 脱敏证据

本文件只服务 `P7_REVIEW_FIX`，不是产品 Artifact、批准收据或发布授权。首轮机器演练 Run 和既有失败证据保持原样，本文件只绑定修复 Run 的三个独立真人轮次。

## 脱敏与原始证据边界

- 修复 Run：`run-20260819T042707.131601Z-e6c8ae07`。
- 原始会话引用：`codex-session:01a01819-2918-7882-b846-2a4044c8c840`。
- 原始会话 JSONL 不复制进仓库；表中只保留 Assistant 展示轮次、下一条用户消息轮次和用户短回复。
- 选题、正文、标题、客户身份、客户资料、本机绝对路径和原始会话其他内容均不进入本证据。
- 完整原始会话保留在当前 ChatGPT Pro Review 对话；Review 时用会话引用、轮次和 Artifact 文件逐项回读。
- 下表所有 Artifact SHA256 均为对应文件原字节 SHA256；用户回复 SHA256 按不带换行的 UTF-8 原文计算。

## 三轮绑定

| Gate | Run ID | 展示 Artifact | 展示 Artifact SHA256 | 会话轮次引用 | 用户原始回复 | 用户回复 SHA256 | 批准 Artifact | 批准 Artifact SHA256 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 方向 | `run-20260819T042707.131601Z-e6c8ae07` | `artifacts/direction_v1.json` | `9eff9e11454bfb909d95c07a63134de6cfd5beca2f99115dd668ff81243d7312` | `assistant:330 → user:337` | `认可整版方向` | `2527b9db3d4924198c4a99197485b836bd3d7beb53382d48659364031bec66db` | `artifacts/approved_direction.json` | `48b7ff6f3a4f805379b1704ec87b1350eec3e4ee7f43a1f3e0595ddb5e0b3019` |
| 正文 | `run-20260819T042707.131601Z-e6c8ae07` | `artifacts/draft_v1.md` | `194c01e33c30dc62439be226df9e281d2ed876a85e153fcc172f6f861a6df03c` | `assistant:419 → user:425` | `确认正文` | `b020db9af3e8401b4a9227ccc8347ebdb8e85f4e55c388c4fcf138aa0346fb9b` | `artifacts/approved_draft.json` | `33111a323b54bfea0ce2521748c3c8f16f5ba39ba4f13f1c9d3c5e701338eb03` |
| 配套与保存 | `run-20260819T042707.131601Z-e6c8ae07` | `artifacts/package_v1.json` | `7982fdc91d2e1ca4a76e718a0394daf00ed55321deffe9829b7a4681ce82f94a` | `assistant:463 → user:470` | `确认并保存` | `cb5c55b1348fbd491af3460b1d714d24e3b2cd14919288ac67f54f1798e40748` | `artifacts/approved_package.json` | `8fa265f25d48f0e46e6b3f15e7cb085c74af0352f275b8815e2d25c6e46d14b7` |

## 顺序结论

三个展示轮次均先结束；对应 `respond-*` 只在下一条真实用户消息之后调用。三轮批准 Artifact 均属于同一修复 Run，首轮机器演练的 Gate、Draft、Package 和批准 Artifact 未被复用、覆盖或重签。
