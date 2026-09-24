"""Plain-language user errors with isolated technical diagnostics."""

from __future__ import annotations

from typing import Any


ERROR_CATALOG = {
    "SLIM_REGISTRY_NOT_READABLE": (
        "当前客户索引无法读取，本次任务尚未开始。",
        "检查客户索引是否存在、格式是否正确，然后重试。",
    ),
    "SLIM_CLIENT_NOT_CONFIGURED": (
        "当前客户没有可用配置，本次任务尚未开始。",
        "先在客户索引中完成唯一配置，再重新开始。",
    ),
    "SLIM_BACKEND_UNSUPPORTED": (
        "当前知识库后端不能由 Content 口播 Slim 直接读取，本次任务尚未开始。",
        "请改选已连接口播的 Obsidian 或飞书知识库。",
    ),
    "SLIM_MANIFEST_INVALID": (
        "当前客户的内容配置不完整或不安全，本次任务没有进入内容阶段。",
        "修正客户 Manifest 后，在同一次任务中重试。",
    ),
    "SLIM_SPEAKER_MODE_INVALID": (
        "当前讲述者模式不受这份客户配置支持，本次任务没有进入内容阶段。",
        "改用客户 Manifest 允许的讲述者模式后重试。",
    ),
    "SLIM_RUN_STORE_INVALID": (
        "本次任务的运行记录无法安全读取或写入。",
        "保留现场并修正 Run Store 后，使用同一个任务标识重试。",
    ),
    "SLIM_TASK_KEY_UNTRUSTED": (
        "当前提供的受控任务句柄无效，无法据此判断是否已有运行记录。",
        "请复用入口返回的原 task-record；不要传入绝对路径、手工填写或让 AI 临时生成的值。",
    ),
    "SLIM_TASK_IDENTITY_CHANGED": (
        "本次请求与已经冻结的任务身份不一致，已有内容不会被覆盖。",
        "如果原始选题、参考集合、客户或讲述者模式确实改变，请开始一个新 Run。",
    ),
    "SLIM_REFERENCE_INVALID": (
        "参考件数量、文件或来源边界不符合要求，本次任务尚未进入拆解。",
        "请修复本次明确提供的参考，最多 5 篇且每篇来源独立；本来没有外部参考时可用库内资料，但不能静默跳过已经给出的失效参考。",
    ),
    "SLIM_METHOD_ROOT_INVALID": (
        "当前客户授权的内容方法目录无法安全读取。",
        "检查客户 Manifest 的 method_root 后，在同一个 Run 重试。",
    ),
    "SLIM_METHOD_ASSET_INVALID": (
        "当前内容方法候选存在越界、错绑或格式问题，尚未交给拆解。",
        "修正授权范围内的方法页后，在同一个 Run 重新检索。",
    ),
    "SLIM_KNOWLEDGE_ASSET_INVALID": (
        "当前客户业务资料无法在授权范围内安全读取。",
        "检查客户 Manifest 的知识目录和相关页面后，在同一个 Run 重试。",
    ),
    "SLIM_PROFILE_INVALID": (
        "当前个人讲述模式没有解析到唯一可用的 IP。",
        "请明确选择一个 active IP；primary 只作为默认值，不限制其他 IP。",
    ),
    "SLIM_CONTEXT_INPUT_INVALID": (
        "准备给上下文装配器的资料不完整或来源错绑。",
        "保留当前 Run，修正已批准方向或授权资料后重新装配。",
    ),
    "SLIM_CONTEXT_OUTPUT_INVALID": (
        "本次上下文包改变了已批准方向或越过了资料边界。",
        "保留当前 Run，按已批准方向和现有候选重新生成唯一上下文包。",
    ),
    "SLIM_WRITER_OUTPUT_INVALID": (
        "本次正文无法作为可直接确认的口播稿保存。",
        "保留当前 Run 和已有版本，按当前方向重新生成完整正文。",
    ),
    "SLIM_DRAFT_RESPONSE_INVALID": (
        "正文确认或修改意见与当前最新版本不一致。",
        "请确认当前正文，或给出一条具体修改意见后重试。",
    ),
    "SLIM_PACKAGE_OUTPUT_INVALID": (
        "本次配套文案不完整或超出了已确认正文。",
        "保留当前正文和已有配套版本，按当前正文重新生成完整配套。",
    ),
    "SLIM_PACKAGE_RESPONSE_INVALID": (
        "配套确认或修改意见与当前最新版本不一致。",
        "请确认当前配套并保存，或给出一条具体修改意见后重试。",
    ),
    "SLIM_SAVE_FAILED": (
        "本次需要保存或复用的产物没有全部安全回读，本次任务未标记完成。",
        "保留已确认正文和配套，修正输出目录或重名问题后在同一个 Run 重试。",
    ),
    "SLIM_ANALYZER_INPUT_INVALID": (
        "准备给拆解器的资料不完整或来源边界不清。",
        "保留当前 Run，修正参考或方法候选后重新准备方向。",
    ),
    "SLIM_ANALYZER_OUTPUT_INVALID": (
        "本次拆解结果不完整或越过了来源边界，尚未进入方向确认。",
        "保留当前 Run，按缺失项重新生成完整方向。",
    ),
    "SLIM_DIRECTION_RESPONSE_INVALID": (
        "方向确认没有使用当前允许的选择，或修改意见不完整。",
        "请选择认可整版方向、需要修改或不采用；修改时请给出具体意见。",
    ),
    "SLIM_STATE_TRANSITION_INVALID": (
        "当前步骤不能直接进入你请求的下一步。",
        "回到当前等待确认的步骤处理，不要跳过真人确认。",
    ),
    "SLIM_VERSION_WRITE_FAILED": (
        "新版本没有安全写入，已有版本没有被覆盖。",
        "保留当前 Run，检查输入后生成下一个版本。",
    ),
    "SLIM_P1_DOWNSTREAM_NOT_AVAILABLE": (
        "基础运行环境已准备，但 P1 尚未启用内容生成阶段。",
        "等待对应阶段获得明确授权后再继续。",
    ),
}


class SlimRuntimeError(Exception):
    """Fail closed while keeping component details out of user responses."""

    def __init__(
        self,
        error_code: str,
        component: str,
        *,
        detail: str = "",
        workflow_stage: str = "任务准备",
        run_exists: bool = False,
        run_created_now: bool = False,
        artifacts_exist: bool = False,
        artifacts_preserved: bool = False,
        technical_report_path: str | None = None,
        recovery_action: str | None = None,
    ) -> None:
        if error_code not in ERROR_CATALOG:
            raise ValueError(f"unknown Slim error code: {error_code}")
        if run_created_now and not run_exists:
            raise ValueError("a newly created Run must exist")
        if artifacts_preserved and not artifacts_exist:
            raise ValueError("absent artifacts cannot be marked preserved")
        if recovery_action is not None and (
            not isinstance(recovery_action, str) or not recovery_action.strip()
        ):
            raise ValueError("recovery_action must be a non-empty string when present")
        self.error_code = error_code
        self.component = component
        self.detail = detail
        self.workflow_stage = workflow_stage
        self.run_exists = run_exists
        self.run_created_now = run_created_now
        self.artifacts_exist = artifacts_exist
        self.artifacts_preserved = artifacts_preserved
        self.technical_report_path = technical_report_path
        self.recovery_action = recovery_action
        super().__init__(ERROR_CATALOG[error_code][0])

    def user_response(self) -> dict[str, Any]:
        message, catalog_action = ERROR_CATALOG[self.error_code]
        action = self.recovery_action or catalog_action
        if self.error_code == "SLIM_TASK_KEY_UNTRUSTED":
            run_text = "当前句柄无效，无法据此判断是否已有运行记录。"
        else:
            run_text = "本次任务已有运行记录。" if self.run_exists else "本次任务尚未创建运行记录。"
        if self.artifacts_exist:
            artifact_text = "已有产物已保留。" if self.artifacts_preserved else "已有产物状态未确认。"
        else:
            artifact_text = "当前没有已生成产物。"
        return {
            "status": "blocked",
            "status_label": "需要你处理一个问题",
            "workflow_stage": self.workflow_stage,
            "message": f"当前阶段：{self.workflow_stage}。{message}{run_text}{artifact_text}",
            "next_action": action,
            "run_exists": self.run_exists,
            "run_created_now": self.run_created_now,
            "artifacts_exist": self.artifacts_exist,
            "artifacts_preserved": self.artifacts_preserved,
        }

    def technical_record(self) -> dict[str, Any]:
        message, catalog_action = ERROR_CATALOG[self.error_code]
        action = self.recovery_action or catalog_action
        return {
            "error_code": self.error_code,
            "component": self.component,
            "detail": self.detail,
            "workflow_stage": self.workflow_stage,
            "user_message": message,
            "suggested_action": action,
            "run_exists": self.run_exists,
            "run_created_now": self.run_created_now,
            "artifacts_exist": self.artifacts_exist,
            "artifacts_preserved": self.artifacts_preserved,
            "technical_report_path": self.technical_report_path,
        }
