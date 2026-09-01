# Content 口播 Slim

Content 口播 Slim 是一套短视频口播内容工作流。

它只做一件事：读取已经明确绑定的本地内容资料和 1—5 篇参考，依次完成方向、正文、配套文案三次真人确认，最终只保存两份 Markdown，并保持未发布。

## 仓库边界

本仓库只包含 5 个 Content 口播 Slim Skill：

- **content-koubo-slim**：唯一公开入口，管理同一个 Run、版本和三次真人确认；
- **content-koubo-analyzer**：拆解参考并生成方向；
- **content-koubo-context-retriever**：按已确认方向装配唯一 Context Pack；
- **content-koubo-writer**：生成或修改纯口播正文；
- **content-koubo-publish-pack**：正文确认后生成标题、发布正文和标签。

本仓库不负责资料采集、资料分类、外部系统写入、数字人、视频剪辑、上传或发布。

`content-gzh-slim`、未来的 `content-huoke-slim` 等产品与它并列，互不覆盖。`content-slim` 暂不作为本仓库入口，保留给未来可能出现的 Content 家族总路由。

## 工作流程

~~~text
用户选题 + 1—5 篇本地参考
              ↓
       匹配已绑定内容资料
              ↓
        方向确认 Gate A
              ↓
          生成口播正文
              ↓
          正文真人确认
              ↓
       生成标题和配套文案
              ↓
        配套确认并保存
              ↓
      两份 Markdown，未发布
~~~

三个真人停点不能合并或跳过：

1. 方向：认可整版方向 / 需要修改 / 不采用
2. 正文：确认正文 / 需要修改
3. 配套：确认并保存 / 需要修改

“随便”“差不多”等模糊说法不算确认。

## 当前版本

| 版本 | Skill 数量 | 运行文件 | 状态 |
|---|---:|---:|---|
| 0.12.0-rc.1 | 5 | 34 | Content 口播 Slim 独立候选包 |

## 仓库结构

~~~text
Skills/
├── content-koubo-slim/
├── content-koubo-analyzer/
├── content-koubo-context-retriever/
├── content-koubo-writer/
└── content-koubo-publish-pack/

examples/
├── client-registry.example.json
└── content-koubo-client-manifest.example.json

tools/verify.py
tools/build_release_manifest.py
tests/
release-manifest.json
SHA256SUMS
VERSION
LICENSE
~~~

## 安装

先克隆并验证：

~~~bash
git clone https://github.com/slbb1995/content-koubo-slim.git
cd content-koubo-slim
python3 tools/verify.py
~~~

验证未通过就停止，不要继续安装。

然后把下面整段交给 Codex 或 WorkBuddy：

~~~text
请完整读取当前 content-koubo-slim 仓库的 README.md，只安装 Content 口播 Slim。

1. 先运行 python3 tools/verify.py；验证失败立即停止。
2. 检查当前 AI 宿主真实的 Skills 根目录，不要猜路径。
3. 只安装仓库 Skills 下这 5 个目录：
   content-koubo-slim、content-koubo-analyzer、
   content-koubo-context-retriever、content-koubo-writer、
   content-koubo-publish-pack。
4. 新名称不存在时才能 create-only 安装；已经存在时先比较差异，
   未经我确认不要覆盖。
5. 安装后回读 5 个 SKILL.md、content-koubo-slim 的 Runtime、Schema 和脚本。
6. 如果发现旧版五个 content-* Skill，先保留，不要删除；等新配置和真实测试通过后，
   再经我确认移动到当前宿主真实的 disabled Skills 目录。
7. 不安装仓库之外的其他 Skill，不读取业务正文，不生成口播，不保存成稿，
   不上传，不发布。
8. 最后告诉我是否需要重新打开任务。
~~~

不要只复制一个 `SKILL.md`。完整运行需要 5 个 Skill，以及 `content-koubo-slim` 目录内的 Runtime、Schema 和脚本。

## 首次配置与自动绑定

Content 口播 Slim 只读取用户明确配置的本地内容工作目录，不搜索整台电脑，也不会仅凭“安装了 Skill”就猜一个知识库。

它需要两份配置：

1. **Client Manifest**：声明业务资料、内容方法、Profile 和输出目录；
2. **Client Registry**：把 `client_id` 绑定到一个本地工作目录和对应 Manifest。

通用示例：

- `examples/content-koubo-client-manifest.example.json`
- `examples/client-registry.example.json`

推荐配置步骤：

1. 准备一个明确的本地内容工作目录；
2. 在目录中准备 Manifest 授权的四个子目录；
3. 根据示例创建 `content-koubo-client-manifest.json`，也可以由遵守同一公开合同的上游配置工具生成；
4. 在当前 AI 宿主的持久配置位置创建 `client-registry.json`；
5. Registry 与 Manifest 的 `client_id` 必须完全一致；
6. 回读 Registry、Manifest 和四个授权目录后，才能开始第一条 Run。

Codex 默认使用：

~~~text
~/.codex/.content-koubo-slim/client-registry.json
~/.codex/.content-koubo-slim/runs
~~~

第一次运行时的判定规则是：

- Registry 只有一条有效客户记录：直接采用并锁定该记录；
- Registry 有多条有效记录：必须让用户明确选择；
- Registry 缺失、无有效记录或无法回读：立即停止，不扫描电脑、不猜路径。

所以，“自动锁定”成立的前提不是两个仓库的安装先后，而是新 Registry 和 Manifest 已经真实生成、且只有一个有效绑定。其他宿主必须使用自己的真实持久位置，不能照抄 Codex 路径。

## 从旧版 Content Slim 迁移

旧版与新版的名称对应如下：

| 旧名 | 新名 |
|---|---|
| `content-slim` | `content-koubo-slim` |
| `content-analyzer` | `content-koubo-analyzer` |
| `content-context-retriever` | `content-koubo-context-retriever` |
| `content-writer` | `content-koubo-writer` |
| `content-publish-pack` | `content-koubo-publish-pack` |

迁移遵守四条规则：

- 新旧 Skill 不同名，可以先并存验证；
- 新版只使用 `~/.codex/.content-koubo-slim/`，不覆盖旧 `.content-v2-slim`；
- 旧配置和旧 Run 不删除，用于回滚和读取历史任务；
- 新版真实测试通过后，再把旧五个 Skill 移入 disabled Skills 目录，不直接删除。

## 日常使用

只调用公开入口 `content-koubo-slim`：

~~~text
请使用 $content-koubo-slim，在已经配置好的本地内容工作目录中开始一条全新口播任务。

选题：
参考资料的本地绝对路径（1—5 篇 MD 或 TXT）：
我的想法：（可空）
必须保留：（可空）
不要写成：（可空）

请严格保留三个真人停点：
1. 完整展示方向后停下；
2. 完整展示正文后停下；
3. 完整展示标题和配套文案后停下。

只有我明确确认后才能进入下一步。
最终确认后只保存两份 Markdown，保持未发布。
~~~

## neutral 模式

没有个人 Profile 时可以使用 `neutral` 模式，只根据本次参考和授权目录生成内容。

`neutral` 模式仍然需要真实 Registry、Manifest、四个授权目录和 1—5 篇本地参考；它不是无配置运行模式。

## 更新与安全边界

- 更新前重新运行 `python3 tools/verify.py`；
- 同名 Skill 目录不得静默覆盖；
- Registry、Manifest、参考来源或当前 Run 不可信时立即停止；
- 参考内容只提炼可迁移机制，不冒充自己的身份、案例、数据或承诺；
- 方向、正文、配套三个真人确认不能由程序或 Agent 代替；
- 保存不等于发布，本仓库没有自动发布能力。

## 许可证

Content 口播 Slim 使用 [MIT License](LICENSE)。
