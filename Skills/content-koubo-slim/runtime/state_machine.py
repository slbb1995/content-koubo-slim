"""Minimal state machine that protects the three human decisions."""

from __future__ import annotations

from .error_model import SlimRuntimeError


USER_STATE_LABELS = {
    "started": "正在准备参考",
    "direction_pending": "等待你确认方向",
    "direction_approved": "正在准备客户内容资料",
    "context_pending": "正在准备客户内容资料",
    "context_ready": "正在生成正文",
    "draft_pending": "等待你确认正文",
    "draft_approved": "正在生成配套文案",
    "package_pending": "等待你确认并保存",
    "package_approved": "等待你确认并保存",
    "blocked": "需要你处理一个问题",
    "saved": "已完成",
    "abandoned": "已结束",
}

TRANSITIONS = {
    "started": {"direction_pending", "blocked"},
    "direction_pending": {"direction_pending", "direction_approved", "abandoned", "blocked"},
    "direction_approved": {"context_pending", "blocked"},
    "context_pending": {"context_pending", "context_ready", "blocked"},
    "context_ready": {"draft_pending", "blocked"},
    "draft_pending": {"draft_pending", "draft_approved", "blocked"},
    "draft_approved": {"package_pending", "blocked", "draft_pending"},
    "package_pending": {"package_pending", "package_approved", "blocked", "draft_pending"},
    "package_approved": {"saved", "blocked", "draft_pending"},
    "blocked": {
        "started",
        "direction_pending",
        "direction_approved",
        "context_pending",
        "context_ready",
        "draft_pending",
        "draft_approved",
        "package_pending",
        "package_approved",
    },
    "saved": {"draft_pending", "package_pending"},
    "abandoned": set(),
}


class SlimStateMachine:
    @staticmethod
    def validate_state(state: str) -> None:
        if state not in TRANSITIONS:
            raise SlimRuntimeError(
                "SLIM_STATE_TRANSITION_INVALID", "state_machine", detail=f"state={state!r}"
            )

    @classmethod
    def ensure_transition(
        cls,
        current: str,
        target: str,
        *,
        blocked_resume_state: str | None = None,
        artifacts_exist: bool = False,
    ) -> None:
        cls.validate_state(current)
        cls.validate_state(target)
        allowed = target in TRANSITIONS[current]
        if current == "blocked":
            allowed = allowed and target == blocked_resume_state
        if not allowed:
            raise SlimRuntimeError(
                "SLIM_STATE_TRANSITION_INVALID",
                "state_machine",
                detail=f"transition={current}->{target}",
                workflow_stage=USER_STATE_LABELS[current],
                run_exists=True,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            )

    @staticmethod
    def user_label(state: str) -> str:
        SlimStateMachine.validate_state(state)
        return USER_STATE_LABELS[state]
