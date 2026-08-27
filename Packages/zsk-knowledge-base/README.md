# ZSK Knowledge Base

这是 ZSK 通用知识库预览交付包，版本 `0.2.2-stage11-preview`。

它包含 5 个用户可见 Skill：

- `zsk-router`：唯一公开入口，负责首次建库和资料路由；
- `zsk-ruku`：01来源登记与02安全异常；
- `zsk-zhishi`：03业务知识卡；
- `zsk-duibiao`：04内容方法卡；
- `zsk-profile`：05唯一主 Profile。

`Skills/shared` 是五个 Skill 共用的确定性运行目录，必须与它们一起安装，不能只复制入口文件。

## 安装

对 Codex，宿主根通常是 `~/.codex`：

```bash
python3 Packages/zsk-knowledge-base/tools/zsk_delivery.py install \
  --host-root "$HOME/.codex" \
  --package Packages/zsk-knowledge-base
```

诊断：

```bash
python3 Packages/zsk-knowledge-base/tools/zsk_delivery.py doctor \
  --host-root "$HOME/.codex"
```

WorkBuddy 必须使用它自己的真实本地宿主根目录。拿不准时让 WorkBuddy 读取当前安装位置，不要照抄 Codex 路径。

安装器发现同名未托管目录时会停止，不会覆盖。飞书后端需要可用的 `lark-cli`；Obsidian 后端不需要飞书依赖。

## 当前边界

技术矩阵已经覆盖 Obsidian/飞书的01→03、01→04、01→05和重复复用；Stage 11 增加了首次建库。独立新用户首次使用和真人质量验收仍未完成，所以当前明确标记为预览版。

ZSK 不生成口播。需要口播时，由仓库根目录的 Content Slim 通过 Registry/Manifest 只读03/04/05，并把成稿保存到07。
