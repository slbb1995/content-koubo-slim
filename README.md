# ZSK + Content Slim

一个仓库，两套边界清楚、可以连续配合的通用能力：

- **ZSK Knowledge Base**：创建知识库、登记来源，把资料整理成业务知识、内容方法和个人 Profile；
- **Content Slim**：只读已经绑定的知识资产，结合 1—5 篇参考生成口播，并保留三次真人确认。

仓库不包含任何客户知识库、个人 Profile、历史任务、成稿、账号、凭据或密钥。

## 它们怎么配合

```text
原始资料
   ↓
zsk-router
   ↓
01 来源索引 / 02 待审核
   ├── zsk-zhishi  → 03 业务知识库
   ├── zsk-duibiao → 04 内容方法库
   └── zsk-profile → 05 IP Profile
                         ↓
                 Registry + Manifest
                         ↓
                    content-slim
                         ↓
          方向确认 → 正文确认 → 配套确认并保存
                         ↓
                  07 生产与反馈
```

ZSK 负责“把资料变成可用资产”，Content Slim 负责“消费这些资产生成口播”。两者不会互相越权：ZSK 不写口播，Content Slim 不建设知识库。

## 当前版本和状态

| 模块 | 版本 | 内容 | 状态 |
|---|---|---|---|
| Content Slim | `0.11.0-rc.4` | 5 个 Skill，34 个运行文件 | 已通过公开包校验与三次真人 Gate 链路 |
| ZSK Knowledge Base | `0.2.2-stage11-preview` | 5 个 Skill，1 个 shared 运行目录，28 个运行文件 | 预览版；技术矩阵通过，独立新用户首次使用和真人质量验收仍待完成 |

ZSK 预览版当前支持：

- Obsidian 本地知识库；
- 飞书知识库（需要 `lark-cli`、用户身份和相应权限）；
- MD、TXT、严格 CSV 的确定性来源登记；
- 01—07、AGENTS、README 的首次建库；
- 01/02 来源与异常、03 知识卡、04 方法卡、05 三层主 Profile。

Content Slim 当前只直接读取本地文件系统，所以“ZSK → Content Slim”自动衔接目前针对 **Obsidian 本地知识库**。飞书可以使用 ZSK 建库和入库，但 Content Slim 暂不能直接读取飞书文档。

## 仓库结构

```text
Skills/                                  # Content Slim 的 5 个 Skill
Packages/zsk-knowledge-base/
├── Skills/                              # ZSK 的 5 个 Skill + shared 运行目录
├── tools/zsk_delivery.py                # 安装、诊断、升级和回退
└── zsk-manifest.json                    # ZSK 文件清单和哈希
examples/                                # 两种知识库配置示例
tools/verify.py                          # 整仓验证和跨模块真实临时 Vault 测试
```

## 最省事的使用方法

先克隆并验证：

```bash
git clone https://github.com/slbb1995/content-slim.git
cd content-slim
python3 tools/verify.py
```

然后把下面整段话交给 Codex 或 WorkBuddy。不要只复制单个 `SKILL.md`：

```text
请完整读取当前 zsk + content-slim 仓库的 README.md，帮我安装并绑定这套知识库口播工作台。

1. 先运行 python3 tools/verify.py；验证未通过立即停止。
2. 检查当前 AI 宿主的 Skill 根目录。Codex 通常是 ~/.codex，WorkBuddy 必须读取它自己的真实本地 Skill 位置，不得猜测。
3. 使用 Packages/zsk-knowledge-base/tools/zsk_delivery.py 安装 ZSK 包；如果已存在同名未托管目录或版本不同，停止并报告，不要覆盖。
4. 将仓库根 Skills 下的 5 个 Content Slim Skill create-only 安装到当前宿主的 skills 目录；发现同名 Skill 时停止并报告差异。
5. 安装后执行 ZSK doctor，并回读 5 个 ZSK Skill、shared 目录、5 个 Content Slim Skill。
6. 询问我已有 ZSK/Obsidian 知识库的本地绝对路径；没有得到路径前不得搜索、猜测或改用其他 Vault。
7. 核对知识库中真实存在 03-业务知识库、04-内容方法库、05-IP-Profile、06-Agent与Workflow、07-生产与反馈。
8. 参考 examples/zsk-content-client-manifest.example.json，在 06-Agent与Workflow 中 create-only 创建 content-v2-client-manifest.json。
9. 参考 examples/zsk-content-client-registry.example.json 保存唯一知识库绑定。Codex 使用 ~/.codex/.content-v2-slim/client-registry.json 和 ~/.codex/.content-v2-slim/runs；WorkBuddy 必须使用它自己的持久本地配置位置，并把 Registry 与运行目录的精确位置写入该知识库的 06 使用说明，不得照抄 Codex 路径。
10. 回读 Registry、Manifest 和四个授权目录；不得因为目录名相似就声明绑定成功。
11. 安装与绑定阶段不读取业务正文、不入库、不生成口播、不保存成稿、不发布。
```

如果还没有知识库，安装后调用 `$zsk-router`，说“帮我创建一个知识库”。它会询问飞书或 Obsidian、知识库名称和必要位置，并在真正创建前展示目标让你确认。

## 日常只记两个入口

### 1. 建库或把资料放进知识库

```text
请使用 $zsk-router 把下面资料入库：

资料路径：
资料用途：业务知识 / 内容参考方法 / 个人 Profile（不确定可以留空）

先核对来源、权限、隐私、版本和归属。不确定时停在 02，不要猜测；入库完成后停止，不写口播。
```

后台职责：

- `zsk-ruku`：登记01来源，异常只进02；
- `zsk-zhishi`：把已登记业务来源整理进03；
- `zsk-duibiao`：把参考资料提炼成04表达方法，不搬运身份、案例和承诺；
- `zsk-profile`：把本人资料整理成05唯一主 Profile。

普通用户只调用 `$zsk-router`，不手工选择四个后台 Skill。

### 2. 使用知识库写一条口播

```text
请使用 $content-slim，在安装时绑定好的唯一 ZSK/Obsidian 知识库中开始一条全新口播任务。

选题：
参考资料的本地绝对路径（1—5 篇 MD 或 TXT）：
我的想法：（可空）
必须保留：（可空）
不要写成：（可空）

请严格保留三个真人停点：
1. 完整展示方向后停下；
2. 完整展示正文后停下；
3. 完整展示标题和配套文案后停下。

只有我明确确认后才能进入下一步。最终确认后只保存两份 Markdown 到 07，保持未发布。
```

三个真人选择分别是：

- 方向：`认可整版方向 / 需要修改 / 不采用`
- 正文：`确认正文 / 需要修改`
- 配套：`确认并保存 / 需要修改`

“随便”“差不多”等模糊说法不算确认。

## 没有知识资产也能先写

Content Slim 可以在 `neutral` 模式下只使用本次提供的 1—5 篇参考生成口播。03、04可以暂时为空，05不需要 Profile。但它仍要求 Registry、Manifest 和授权目录真实存在。

## 更新和安全边界

- 更新前先拉取仓库并重新运行 `python3 tools/verify.py`；
- ZSK 使用自己的交付工具 upgrade/doctor/rollback；
- Content Slim 同名目录不得直接覆盖，先比较、备份、再升级并回读；
- 参考内容只提炼可迁移机制，不冒充自己的身份、案例、数据或承诺；
- 隐私、权限、归属、版本或客户绑定无法确认时停止；
- 保存不等于发布，本仓库没有自动发布能力。

## 许可证

本仓库中的 ZSK 与 Content Slim 均使用 [MIT License](LICENSE)。
