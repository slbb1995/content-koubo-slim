# Content 口播 Slim 单仓维护规则

本仓库 slbb1995/content-koubo-slim 是五个 content-koubo-* Skill 的唯一源码、测试、安装和发行来源。Skills/ 是唯一现役源码目录；本机安装目录只是运行副本。用户已授权从旧开发仓迁移，旧仓只保留历史，不再维护口播。

- 在分支开发，运行 python3 -B tools/build_release_manifest.py 更新完整来源清单，再运行 python3 -B tools/verify.py。完整依赖在 requirements-test.txt，CI 同时验证 Linux 和 Windows。
- tools/content_koubo_slim_release.py 提供固定干净提交构建、备份、安装、doctor 和回滚；只安装五个 Skill。tools/package_release.py 从固定干净提交生成完整 ZIP 并回读验证。
- 历史阶段材料 project-state.json、designs/、PHASE-P7.md 和测试证据为不可变历史，不代表当前发布状态。旧开发仓完整 Git 历史保留在私有归档和本地 Git bundle；停用 V1/BX 仅从历史提交恢复，禁止混装。
- public-methods 的上游仍为 zsk-knowledge-base-skill，按 SOURCE.json 固定版本核验；资料更新需客户授权，保留自定义资料。
- 保留 Registry、Manifest、Profile、历史任务与已保存稿件；安装前备份，安装后逐文件核对 release-manifest.json。三个人工确认点保持，保存不等于发布。
