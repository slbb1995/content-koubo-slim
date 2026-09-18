# Content 口播 Slim

Content 口播 Slim 是一套短视频口播内容工作流。

它从明确或已确认默认的 Obsidian 或飞书知识库中选择本次 IP，把客户的一段想法结合少量内容资料写成口播，依次完成方向、正文、配套文案三次真人确认，每篇最终保存口播和配套两份产物，并保持未发布。Obsidian 保存 Markdown，飞书保存原生云文档。有参考优先拆解参考；没有参考，由 Agent 从库内同行和方法中选材。

支持一次提出多篇口播要求：每篇分别拆解方向、确认、修改、生成配套和保存，同名标题也不会合并。多篇可集中展示供确认；未展示或未获明确确认的稿件不会自动推进。一个文档包含多篇对标时，按原文篇目准备参考，不把合集当成单篇。

本次更新只涉及这五个口播 Skill。现有知识库资料、ZSK 和公众号流程不需要随本版本修改。内部批次与参考映射的执行说明分别见 [多篇任务](Skills/content-koubo-slim/references/batch-tasks.md) 和 [逐篇参考](Skills/content-koubo-slim/references/reference-pieces.md)。

## 仓库边界

本仓库只包含 5 个 Content 口播 Slim Skill：

- **content-koubo-slim**：唯一公开入口，管理单篇或批次，每篇独立 Run、版本和三次真人确认；
- **content-koubo-analyzer**：拆解参考并生成方向；
- **content-koubo-context-retriever**：按已确认方向装配唯一 Context Pack；
- **content-koubo-writer**：生成或修改纯口播正文；
- **content-koubo-publish-pack**：正文确认后生成标题、发布正文和标签。

本仓库不负责资料采集、资料分类、数字人、视频剪辑或发布。内容保存只写 Manifest 授权的本地输出根或飞书输出节点。

`content-gzh-slim`、未来的 `content-huoke-slim` 等产品与它并列，互不覆盖。`content-slim` 暂不作为本仓库入口，保留给未来可能出现的 Content 家族总路由。

## 工作流程

~~~text
用户选题或一段想法 + 可选 0—5 篇本地参考
              ↓
   有参考优先拆解；无参考先找库内同行
          按需要结合结构方法
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
      两份产物，未发布
~~~

三个真人停点不能合并或跳过：

1. 方向：认可整版方向 / 需要修改 / 不采用
2. 正文：确认正文 / 需要修改
3. 配套：确认并保存 / 需要修改

“随便”“差不多”等模糊说法不算确认。

## 当前版本

| 版本 | Skill 数量 | 功能 |
|---|---:|---|
| 1.3.0 | 5 | 批量口播、逐篇参考、飞书接入与保存恢复 |

## 仓库结构

~~~text
Skills/
├── content-koubo-slim/
├── content-koubo-analyzer/
├── content-koubo-context-retriever/
├── content-koubo-writer/
└── content-koubo-publish-pack/

examples/
├── knowledge-base-registry.example.json
├── content-source-manifest.example.json
├── content-profile-index.example.json
├── client-registry.example.json（旧 v2 兼容）
└── content-koubo-client-manifest.example.json（旧 v2 兼容）

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

Content 口播 Slim 只读取用户明确配置或经过真人确认的 Obsidian 或飞书知识库，不搜索整台电脑，也不会仅凭“安装了 Skill”就猜一个知识库。

新版公共合同有三份配置：

1. **Knowledge Base Registry**：`~/.codex/.content-workflows/knowledge-base-registry.json`，按 `binding_id` 区分客户与知识库；
2. **Content Source Manifest**：声明 03、04、05、06、07 和工作流输出；
3. **Content Profile Index**：保存多个 active Profile 的稳定 ID、别名、对象引用和哈希。

公共合同示例：

- `examples/knowledge-base-registry.example.json`
- `examples/content-source-manifest.example.json`
- `examples/content-profile-index.example.json`

原有两个 v2 示例仅用于兼容旧客户配置。

只安装本仓库也能独立配置一个兼容知识库：

```bash
python3 Skills/content-koubo-slim/scripts/content_koubo_slim.py configure \
  --vault /绝对路径/知识库
```

第一次只返回 `wrote=false` 预览和确认值。检查无误后，把返回值传给同一命令的 `--confirmation`；确认前不会创建 Manifest、Profile 索引或 Registry。

Codex 默认使用：

~~~text
~/.codex/.content-workflows/knowledge-base-registry.json
~/.codex/.content-koubo-slim/runs
~~~

第一次运行时的判定规则是：

- 本次明确选择 binding：采用该知识库；
- 否则采用已确认的口播默认 binding；没有默认但只有一条兼容 binding 时采用；仍不唯一就要求选择；
- `personal_ip` 按“本次明确指定 → 口播默认 → primary → 唯一 active → 要求选择”解析；
- Feishu binding 使用原生 Manifest/Profile/文档引用，不降级到同步目录。已有飞书 binding 的定向配置与只读预检见 [飞书接入](Skills/content-koubo-slim/references/feishu-backend.md)。

所以，“自动锁定”成立的前提不是仓库安装先后，而是 Registry、Manifest、Profile 索引已经真实生成并能唯一解析。primary 只是默认 IP，不是唯一可用 IP。

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
参考资料的本地绝对路径（可空；有则最多 5 篇 MD 或 TXT）：
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

`neutral` 模式仍然需要真实 Registry、Manifest 和授权目录；它不是无配置运行模式。没有外部参考时需要可用的库内内容或方法。

## 没有对标时怎么工作

例如客户只说“我想讲讲，买完之后，后续服务还有什么价值？”Agent 先理解这条内容要回答的问题，在当前知识库 04 找相关同行的问题主线、通用观点和细节，再按需要借结构组织；03 支撑实际业务，05 支撑本次 IP。客户不需要选结构编号，也不用先补一篇对标。

选材不是按关键词机械套模板。入口把授权目录与完整候选交给内部 Analyzer 语义判断；最多采用 3 张同行、2 张方法，另可冻结 3 份选材指引。同行不是当前客户的经历或服务承诺；索引、实验项、过期资料不能混成已核验事实。没有可用来源时说明实际缺口；明确给出却读不了的参考必须先解决，不能静默绕过。

内部接口为 `discover-methods` → 完整回读候选 → `start --method-selection`。选择文件只供 Agent 使用，详见 `Skills/content-koubo-slim/references/idea-first-materials.md`。旧 CLI 不传选择文件仍保留字面检索兼容；旧 Run、三次真人确认、唯一 Context 和双文件未发布保存不变。

## 1.1.0 修复内容

- 已确认或已保存的正文支持在原任务继续改稿。旧稿、旧确认及原保存文件保留；新正文和配套分别重新确认，修订版文件名带版本号。
- 发布说明的 50—100 字改为默认建议，允许明确要求更短、更长、分段；不影响口播时长。
- 普通评论交流和观点收尾不再被商业转化授权规则一并禁止；私信、领取、预约等动作仍按用户授权和事实依据处理。
- CLI 自动以隔离 Python 重启，避免宿主 PYTHONPATH/sitecustomize 钩子影响本地文件读写。显式区分宿主配置目录，不修改用户全局 Python 环境。
- 具体产品/服务结论必须保留适用条件和对应事实依据；知识库没有依据时说明缺口，不把同行观点当成已核验业务事实。

## 更新到修复版

在仓库目录先检查 `git status --short`。有本地改动先保留并比较，不覆盖；干净时运行 `git pull --ff-only`，然后 `python3 tools/verify.py`。

验证通过后，完整更新上述 5 个 Skill 目录，并先将旧目录备份到宿主不加载的位置。保留知识库、Registry、Manifest、Profile 索引和历史任务，不把 Git 拉取成功当作安装完成。更新后按 release manifest 逐文件核对实际宿主目录。

WorkBuddy 调用入口时使用：

```bash
python3 Skills/content-koubo-slim/scripts/content_koubo_slim.py --host workbuddy --help
```

Codex 使用 `--host codex`；自定义安装环境使用 `--host-root /已确认的宿主目录`。这些参数适用于全部子命令，宿主根决定默认配置和任务目录；显式 `--registry`、`--runs-root` 仍优先。使用已安装副本时将脚本位置改为宿主实际 Skills 根。`configure`、`start`、`status` 和继续任务必须保持同一宿主。不要把示例路径原样当成客户路径。

客户可以直接说“把刚才确认的稿子扩写一些，保留原版”，入口会继续原任务；新正文确认前不能拿旧配套完成新版保存。

## 更新与安全边界

- 更新前重新运行 `python3 tools/verify.py`；
- 同名 Skill 目录不得静默覆盖；
- Registry、Manifest、Profile 索引、参考来源或当前 Run 不可信时立即停止；
- Gate 后任何已冻结 03/04/05 资料或绑定哈希变化，保留旧产物并停止；
- 参考内容只提炼可迁移机制，不冒充自己的身份、案例、数据或承诺；
- 方向、正文、配套三个真人确认不能由程序或 Agent 代替；
- 保存不等于发布，本仓库没有自动发布能力。

## 许可证

Content 口播 Slim 使用 [MIT License](LICENSE)。
