# 单仓维护与迁移

从 1.5.1 起，content-koubo-slim 同时维护源码、测试、工具、说明和发行包。1.5.1 的 56 个运行文件与 1.5.0 完全一致，本次只收拢维护结构。

## 日常开发与发行

1. 从 main 创建开发分支，直接修改 Skills/ 下五个技能。
2. 安装 requirements-test.txt；更新后运行 `python -B tools/build_release_manifest.py` 和 `python -B tools/verify.py`。测试涵盖 P1—P7、既有发行回归、方向设计、多篇任务、保存及安装回滚。
3. 提交后等 Linux/Windows CI 通过，再从干净固定提交执行 `python -B tools/package_release.py --out /absolute/path/content-koubo-slim-vX.Y.Z.zip`。使用 Tag 和 GitHub Releases 分发。
4. 本机升级先备份五个运行目录，再安装经过验证的固定版本并运行 doctor，逐文件比对。共享 WorkBuddy 使用同一目录。

SOURCE.json 只记录本仓归属、公共资料固定来源、迁移历史和完整文件哈希。当前源码提交以 Git Tag/Release 为准，避免文件自引用提交哈希。重建清单是维护操作，不能代替代码审查；发布时必须从干净固定提交打包。

## 历史保留

旧开发仓的全部 Git 历史、分支和标签保留在原私有仓库和经验证的本地 Git bundle 中，不并入本公开仓库。SOURCE.json 的 migration.former_commit 为迁移前原始提交，在私有归档仓可使用 `git ls-tree`、`git show` 或历史 checkout 回查所有旧技能、测试及审计。现役口播的全部 P1—P7 测试已迁到 tests/ 并加入统一验证；旧 V1/BX 源码和测试继续保留在私有归档，不加载为现役技能。公开迁移只包含口播所需的合成测试和脱敏历史证据。

project-state.json、设计卡和旧阶段验收证据保留原文供历史测试验证，不是当前维护指令。本次迁移后的权威维护说明为本文件和 AGENTS.md。旧 content-workflow-skills 仓库验收后设置为 archived，保留可恢复历史。
