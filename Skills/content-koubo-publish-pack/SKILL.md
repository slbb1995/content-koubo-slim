---
name: content-koubo-publish-pack
description: Content 口播 Slim 的三平台配套文案生成 Skill。用于同一 Run 的口播正文已获真人确认后，为抖音、小红书、视频号生成或局部修改各一套可直接使用的标题、发布正文和 Tag，并可提供封面文字。不得修改正文、重搜客户资料、保存、发布或进入 P6。
---

# Content Publish Pack

## 目的与边界

把一份已确认口播正文整理成目标平台各一套可直接复制的发布配套。正文是事实、数字、身份、产品能力、案例、承诺和 CTA 的唯一边界；平台规则、受众、内容目的、讲述模式、口吻样例及用户禁区只决定写法，不能给新事实开口子。

只读取编排器的 `content-koubo-publish-pack-input-v2`，字段合同见 [输入 Schema](schemas/publish-pack-input-v2.schema.json)，输出合同见 [结果 Schema](schemas/publish-pack-result-v2.schema.json)。不打开 Registry、Manifest、03/04/05、Vault、网络、历史稿或其他客户资料，不调用旧标题/分发 Skill、Reviewer、保存或发布能力。`company_brand` 与 `neutral` 没有个人口吻样例时照常工作，不虚构个人经历。

## 平台规则

根据 `target_platforms` 只读对应规则；规则版本必须与输入一致：

- `douyin`：[抖音](references/douyin.md)
- `xiaohongshu`：[小红书](references/xiaohongshu.md)
- `wechat_channels`：[视频号](references/wechat-channels.md)

这些文件区分官方可核验边界与内部编辑建议。未核验的字符限制、固定 Tag 数量、算法权重、热度和流量保证都不能自行补充。普通生成不搜索热词；没有真实数据时只输出相关话题建议。

## 输入

```json
{
  "package_contract_version": "content-koubo-publish-pack-input-v2",
  "approved_draft": {"draft_version": 2, "body": "完整确认正文"},
  "writing_context": {
    "target_audience": "已确认受众",
    "content_goal": "explain | discuss | convert",
    "speaker_mode": "personal_ip | company_brand | neutral",
    "voice_guidance": null,
    "must_avoid": [],
    "fact_boundary": "approved_draft_only"
  },
  "target_platforms": ["douyin", "xiaohongshu", "wechat_channels"],
  "platform_rule_versions": {},
  "base_package_version": 0,
  "previous_package": null,
  "revision_request": null,
  "revision_scope": null
}
```

`voice_guidance` 存在时只学习表达习惯，其中的例句不能成为配套事实。`revision_scope` 为 `平台.字段` 列表，例如 `xiaohongshu.publish_copy`；未列出的字段必须逐值保留。增减平台、整套重做或修改封面文字不靠模糊推断，分别使用明确目标平台或 `cover_texts` scope。

## 输出

只返回一个 JSON 对象，不附解释：

```json
{
  "contract_version": "content-koubo-publish-pack-result-v2",
  "platforms": {
    "douyin": {"title": "一条成品标题", "publish_copy": "成品正文", "tags": ["#主题词"]},
    "xiaohongshu": {"title": "一条成品标题", "publish_copy": "成品正文", "tags": ["#主题词"]},
    "wechat_channels": {"title": "一条成品标题", "publish_copy": "成品正文", "tags": ["#主题词"]}
  },
  "cover_texts": [],
  "recommended_cover_text": null
}
```

只输出 `target_platforms` 中的平台。每个平台默认一条标题、一段正文、1—5 个相关 Tag；数量是编辑默认，不是平台硬限制。主题词允许跨平台重复。封面文字可为 0—2 条；有候选时推荐项必须来自候选。备选标题只在真人明确要求时通过新配套版本处理，不把评分、来源说明或推荐理由混进可复制成品。

## 写作与自检

先从正文提取具体对象、实际问题、核心判断、视频能兑现的答案和影响结论的条件，再按内容目的与平台阅读方式组织。三个平台应改变切入重点或信息组织，不能只换同义词、emoji 或 Tag。

- `explain` 可突出步骤、条件或判断依据；
- `discuss` 可呈现正文已有观点与处境，不强行改成清单；
- `convert` 只承接正文已有且获授权的动作，不新增私信、领取、预约、购买等 CTA。

返回前一次自检：标题可由正文兑现；正文没有扩大承诺；Tag 只来自本稿主题、问题、场景或人群；没有虚构亲测、客户结果、热点和联系方式；不同平台不是机械换词；`revision_scope` 外字段完全不变。

## 修改、确认与停止

修改时接收当前完整配套与真人意见，返回完整新对象，旧版本保留。若意见要求改正文、换题、换客户、换讲述者或增加正文没有的事实，停止并回相应阶段。

完整展示三平台配套后仍只有第三个真人停点。用户说“三个平台都采用推荐项”精确表示确认当前各平台成品；相近的模糊回复不算确认。说“只改小红书正文”时编排器必须传 `xiaohongshu.publish_copy` scope，并由 Runtime 持久绑定到下一版本。确认由入口记录，本 Skill 不创建收据、不保存、不发布。

旧 v1 通用配套由 Runtime 原样读取和恢复，不在本 Skill 中凭空补成三平台，也不替换旧批准记录。设计原因保存在 Factory 设计卡；版本与保存由 `content-koubo-slim` Runtime 管理。
