# Content Slim

一套可以安装到 Codex 的短视频口播内容工作流。

它会在同一个任务中完成：参考内容拆解、写作方向确认、口播正文、标题与发布配套，并严格停在三次真人确认处。最终只保存文件，不自动发布。

当前版本：`0.11.0-rc.4`

## 这不是一个单文件 Skill

完整运行需要下面 5 个 Skill，不能只复制 `content-slim/SKILL.md`：

- `content-slim`：唯一用户入口和工作流状态管理；
- `content-analyzer`：拆解 1—5 篇参考并准备写作方向；
- `content-context-retriever`：按已确认方向装配受控资料；
- `content-writer`：生成和修改口播正文；
- `content-publish-pack`：生成封面标题、发布标题、发布正文和标签。

仓库不包含任何客户知识库、个人 Profile、历史任务、成稿、账号或密钥。

## 适合谁

- 使用 Codex，并希望把参考资料稳定变成短视频口播的人；
- 愿意先建立一个本地内容资料库，并保留真人确认的人；
- 需要“方向 → 正文 → 配套与保存”三个明确停点的人。

它不是零配置在线服务。第一次使用前，需要安装 5 个 Skill，并绑定你自己的本地资料库。

## 最省事的安装方法

先克隆仓库：

```bash
git clone https://github.com/slbb1995/content-slim.git
cd content-slim
python3 tools/verify.py
```

然后把下面整段话交给 Codex。安装时不要直接覆盖同名 Skill：

```text
请读取当前 content-slim 仓库的 README.md，帮我完成第一次安装和绑定：

1. 先运行 python3 tools/verify.py，校验版本、34 个运行文件和 5 个 Skill。
2. 将 Skills 下的 5 个 Skill create-only 安装到当前账户的 ~/.codex/skills。
3. 如果任何同名 Skill 已存在，立即停止并报告差异，不要覆盖。
4. 询问我准备用作内容资料库的本地绝对路径；没有得到路径前不要猜测或搜索。
5. 参考 examples/content-client-manifest.example.json，在资料库中创建 workflow-config/content-client-manifest.json；默认先使用 neutral 模式。
6. 参考 examples/client-registry.example.json，把唯一客户绑定写入 ~/.codex/.content-v2-slim/client-registry.json，并把运行目录设为 ~/.codex/.content-v2-slim/runs。
7. 确认 knowledge-data、method-data、profile-data、output-data 四个目录真实存在；缺失时先告诉我准备创建什么，得到确认后再创建。
8. 回读 Registry、Manifest、5 个已安装 Skill 和四个资料目录，确认一致后停止。
9. 安装阶段不读取业务正文，不生成口播，不保存成稿，不发布。
```

配置示例中的 `/ABSOLUTE/PATH/TO/YOUR-CONTENT-VAULT` 必须替换为这台电脑上的真实绝对路径，不能原样使用。

## 资料库最小结构

```text
your-content-vault/
├── workflow-config/
│   └── content-client-manifest.json
├── knowledge-data/    # 自己可核验的业务知识，可为空
├── method-data/       # 已整理的内容方法，可为空
├── profile-data/      # personal_ip 模式才需要有效主 Profile
└── output-data/       # 最终口播稿和配套文案
```

第一次建议使用 `neutral` 模式。它不要求个人 Profile；以后需要用个人身份表达时，再配置 `personal_ip` 和唯一有效主 Profile。

## 写第一条口播

准备 1—5 篇本地参考文件，然后把下面内容交给 Codex：

```text
请使用 $content-slim，在安装时绑定好的默认资料库中开始一条全新口播任务。

选题：
参考资料的本地绝对路径（1—5 篇）：
我的想法：（可空）
必须保留：（可空）
不要写成：（可空）

请严格保留三个真人停点：
1. 完整展示方向后停下；
2. 完整展示正文后停下；
3. 完整展示标题和配套文案后停下。

只有我明确确认后才能进入下一步。最终确认后只保存两份 Markdown，保持未发布。
```

三个真人选择分别是：

- 方向：`认可整版方向 / 需要修改 / 不采用`
- 正文：`确认正文 / 需要修改`
- 配套：`确认并保存 / 需要修改`

“随便”“差不多”等模糊说法不算确认。

## 更新

拉取新版本前，先查看版本说明并重新运行：

```bash
python3 tools/verify.py
```

不要直接覆盖正在使用的同名 Skill。先比较差异、备份现有版本，再由 Codex 执行升级和回读。

## 安全边界

- 参考内容只用于提炼可迁移的结构和表达机制，不得冒充自己的身份、案例、数据或承诺；
- 客户资料、讲述者 Profile 和运行记录只保存在使用者本机，不应提交到本仓库；
- 保存不等于发布，仓库不包含自动发布能力；
- Registry、Manifest、来源、版本或客户归属无法确认时，工作流会停止，不会猜测路径继续运行。

## 许可证

本项目使用 [MIT License](LICENSE)。
