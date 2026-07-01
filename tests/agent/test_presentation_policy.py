"""Tests for channel/audience presentation policy resolution."""

from agent.presentation_policy import (
    PUBLIC_AUDIENCE_PROMPT_GUIDANCE,
    resolve_presentation_policy,
)


def test_weixin_defaults_to_public_consumer_policy():
    policy = resolve_presentation_policy({}, "weixin")

    assert policy.platform == "weixin"
    assert policy.audience == "public"
    assert policy.language == "zh-Hans"
    assert policy.result_first is True
    assert policy.details_on_demand is True
    assert policy.show_process is False
    assert policy.show_tool_trace is False
    assert policy.show_internal_paths is False
    assert policy.show_debug_errors is False
    assert policy.suppress_plain_text_busy_ack is True
    assert policy.approval_prompt_style == "summary"
    assert policy.progress_notice_style == "summary"
    assert policy.long_task_notice_delay_seconds == 30
    assert policy.long_task_heartbeat_seconds == 90


def test_unknown_platform_defaults_to_developer_policy():
    policy = resolve_presentation_policy({}, "custom")

    assert policy.platform == "custom"
    assert policy.audience == "developer"
    assert policy.result_first is False
    assert policy.show_process is True
    assert policy.show_tool_trace is True
    assert policy.show_internal_paths is True
    assert policy.suppress_plain_text_busy_ack is False
    assert policy.approval_prompt_style == "technical"
    assert policy.progress_notice_style == "technical"
    assert policy.long_task_notice_delay_seconds is None
    assert policy.long_task_heartbeat_seconds is None


def test_platform_audience_override_can_restore_developer_detail():
    cfg = {
        "display": {
            "platforms": {
                "weixin": {
                    "audience": "developer",
                }
            }
        }
    }

    policy = resolve_presentation_policy(cfg, "weixin")

    assert policy.audience == "developer"
    assert policy.show_process is True
    assert policy.show_internal_paths is True
    assert policy.suppress_plain_text_busy_ack is False
    assert policy.approval_prompt_style == "technical"
    assert policy.progress_notice_style == "technical"
    assert policy.long_task_notice_delay_seconds is None
    assert policy.long_task_heartbeat_seconds is None


def test_public_policy_fields_can_be_overridden():
    cfg = {
        "display": {
            "platforms": {
                "weixin": {
                    "audience": "public",
                    "show_internal_paths": True,
                    "suppress_plain_text_busy_ack": False,
                    "approval_prompt_style": "technical",
                    "progress_notice_style": "technical",
                    "long_task_notice_delay_seconds": 45,
                    "long_task_heartbeat_seconds": 120,
                }
            }
        }
    }

    policy = resolve_presentation_policy(cfg, "weixin")

    assert policy.audience == "public"
    assert policy.show_process is False
    assert policy.show_internal_paths is True
    assert policy.suppress_plain_text_busy_ack is False
    assert policy.approval_prompt_style == "technical"
    assert policy.progress_notice_style == "technical"
    assert policy.long_task_notice_delay_seconds == 45
    assert policy.long_task_heartbeat_seconds == 120


def test_public_prompt_guidance_is_result_first_and_hides_process():
    lowered = PUBLIC_AUDIENCE_PROMPT_GUIDANCE.lower()

    assert "lead with the result" in lowered
    assert "do not narrate your process" in lowered
    assert "scripts" in lowered
    assert "file paths" in lowered
    assert "tools" in lowered
