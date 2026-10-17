# Content 口播 Slim 发行仓

本仓库是唯一对外下载、安装和升级入口。运行源码由 slbb1995/content-workflow-skills 的 skills/content-mainline/content-koubo-* 维护；发布工具从同一个固定提交导出五个技能、测试及安装说明。不要在发行仓独立开发第二条运行源码。

- SOURCE.json 记录开发提交、公共方法资料提交和导出文件清单；修改必须先回到相应规范源码，再导出发行包。
- 发行前运行 python3 -B tools/verify.py；需要完整 Schema 检查时先安装 requirements-test.txt。
- 只安装 Skills 下五个 content-koubo-* 目录；先备份同名运行版。public-methods 单独用于客户授权的 04 资料更新，保留自定义内容，不能覆盖整个知识库。
- 保留 Registry、Manifest、Profile、历史任务和已保存稿件；安装后逐文件核对 release-manifest.json。
- 三个人工确认点仍由客户执行，合成测试不代替客户确认；保存不等于发布。
