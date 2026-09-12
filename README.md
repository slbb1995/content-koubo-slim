# Content Slim

Content Slim 是一套短视频口播内容工作流。

它只做一件事：读取已经配置好的本地内容资料和 1—5 篇参考，依次完成方向、正文、配套文案三次真人确认，最终只保存两份 Markdown，并保持未发布。

## 仓库边界

本仓库只包含 5 个 Content Slim Skill：

- **content-slim**：唯一公开入口，管理同一个 Run、版本和三次真人确认；
- **content-analyzer**：拆解参考并生成方向；
- **content-context-retriever**：按已确认方向装配唯一 Context Pack；
- **content-writer**：生成或修改纯口播正文；
- **content-publish-pack**：正文确认后生成标题、发布正文和标签。

本仓库不负责资料采集、资料分类、外部系统写入、数字人、视频剪辑、上传或发布。

## 与 ZSK 的关系

Content Slim 不包含知识库 Router，也不把 ZSK 作为代码依赖。两者是可选的前后两个独立仓库：

- [zsk-knowledge-base-skill](https://github.com/slbb1995/zsk-knowledge-base-skill) 负责建库、入库和生成 03/04/05；
- Content Slim 只消费已经明确绑定的本地内容资产并生产口播；
- 客户连续使用时推荐先安装 ZSK，再安装 Content Slim；
- ZSK 的代码和更新只在独立 ZSK 仓库维护，不复制回本仓库；
- Content Slim 当前只直接读取本地文件系统，因此自动桥接只适用于 ZSK 的 Obsidian 本地知识库，不适用于飞书知识库。

两个仓库安装完成不等于已经自动绑定。首次缺少配置时，Content Slim 会先只读预检用户明确给出的知识库绝对路径；用户确认同一路径后才 create-only 保存 Registry、Manifest 和 runs，后续任务再自动复用。

## 工作流程

~~~text
用户选题 + 1—5 篇本地参考
              ↓
       匹配已配置内容资料
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
| 0.11.0-rc.5 | 5 | 36 | 独立 Content Slim 发布包，含一次持久绑定入口 |

## 仓库结构

~~~text
Skills/
├── content-slim/
├── content-analyzer/
├── content-context-retriever/
├── content-writer/
└── content-publish-pack/

examples/
├── client-registry.example.json
└── content-client-manifest.example.json

tests/
install.py
tools/verify.py
tools/verify_zsk_bridge.py
release-manifest.json
SHA256SUMS
VERSION
LICENSE
~~~

## 安装

先克隆并验证：

~~~bash
git clone https://github.com/slbb1995/content-slim.git
cd content-slim
python3 tools/verify.py
python3 install.py
~~~

验证未通过就停止，不要继续安装。安装器只安装 5 个 Content Slim Skill，发现同名目录、软链接、额外文件或哈希不一致时停止，不覆盖。

然后把下面整段交给 Codex 或 WorkBuddy：

~~~text
请完整读取当前 content-slim 仓库的 README.md，只安装 Content Slim。

1. 先运行 python3 tools/verify.py；验证失败立即停止。
2. 检查当前 AI 宿主真实的 Skills 根目录，不要猜路径。
3. 使用 python3 install.py 安装 5 个 Content Slim Skill；
   其他宿主使用 --dest 指定真实 Skills 目录。
4. 同名目录、软链接、额外文件或哈希不一致时停止，不覆盖。
5. 安装后回读 5 个 SKILL.md、content-slim 的 runtime、schemas 和脚本。
6. 不从本仓库安装 zsk-router，不读取业务正文，不生成口播，不保存成稿，
   不上传，不发布。
7. 最后告诉我是否需要重新打开任务。
~~~

不要只复制一个 SKILL.md。完整运行需要 5 个 Skill，以及 content-slim 目录内的 Runtime、Schema 和脚本。

## 首次配置

Content Slim 只读取用户明确指定的本地内容工作目录，不搜索整台电脑，也不猜测其他目录。

它需要两份配置：

1. **Client Manifest**：声明业务资料、内容方法、Profile 和输出目录；
2. **Client Registry**：把 client_id 绑定到一个本地工作目录和对应 Manifest。

通用示例：

- examples/content-client-manifest.example.json
- examples/client-registry.example.json

推荐配置步骤：

1. 准备一个明确的本地内容工作目录；
2. 在目录中准备 Manifest 授权的四个子目录；
3. 根据示例创建 content-client-manifest.json；
4. 在当前 AI 宿主的持久配置位置创建 client-registry.json；
5. Registry 与 Manifest 的 client_id 必须完全一致；
6. 回读 Registry、Manifest 和四个授权目录后，才能开始第一条 Run。

Codex 通常使用：

~~~text
~/.codex/.content-v2-slim/client-registry.json
~/.codex/.content-v2-slim/runs
~~~

其他宿主必须使用自己的真实持久位置，不能照抄 Codex 路径。路径缺失、冲突、越界、含软链接或无法回读时立即停止。

### 已先使用 ZSK 的客户

当用户要绑定 ZSK 创建的 Obsidian 本地知识库时，使用已安装的 content-slim/scripts/configure_client.py：

1. 传入 Registry、runs、Vault 绝对路径和讲述者模式，但先不传 confirm-vault-root；
2. 程序只检查 03—07 目录和 04/05 frontmatter，返回规范路径与动作预览，零写入；
3. 完整展示预览后停下，不得代用户确认；
4. 只有用户下一条消息明确确认同一路径后，才把预览中的规范绝对路径原样传给 confirm-vault-root；
5. 程序 create-only 写入并回读。完全一致则复用，任何冲突都停止，不覆盖、不改绑；
6. personal_ip 模式必须存在唯一 status active、is_primary true 的主 Profile。

两个准备交付的仓库还必须通过独立桥接验收：

~~~bash
python3 tools/verify_zsk_bridge.py \
  --zsk-root ../zsk-knowledge-base-skill
~~~

该验收会把 Content Slim 安装到全新临时 Skills 目录，让 ZSK 在全新 Obsidian Vault 真实写出 03/04/05，再检查 Content Slim 能读取三类资产、预检零写入、确认后复用绑定并创建新 Run；验收过程不得保存成稿或产生 07 输出。

## 日常使用

只调用公开入口 content-slim：

~~~text
请使用 $content-slim，在已经配置好的本地内容工作目录中开始一条全新口播任务。

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

没有个人 Profile 时可以使用 neutral 模式，只根据本次参考和授权目录生成内容。

neutral 模式仍然需要真实 Registry、Manifest、四个授权目录和 1—5 篇本地参考；它不是无配置运行模式。

## 更新与安全边界

- 更新前重新运行 python3 tools/verify.py；
- 同名 Skill 目录不得静默覆盖；
- Registry、Manifest、参考来源或当前 Run 不可信时立即停止；
- 不自动搜索知识库，不把飞书链接当成本地 Vault，不在不同客户之间静默改绑；
- 参考内容只提炼可迁移机制，不冒充自己的身份、案例、数据或承诺；
- 方向、正文、配套三个真人确认不能由程序或 Agent 代替；
- 保存不等于发布，本仓库没有自动发布能力。

## 许可证

Content Slim 使用 [MIT License](LICENSE)。
