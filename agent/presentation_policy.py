"""Presentation policy for channel/audience-specific user-facing output.

This module is intentionally dependency-light so both agent prompt assembly and
gateway rendering code can share the same policy language without importing
each other.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


PUBLIC_AUDIENCE_PROMPT_GUIDANCE = (
    "Optimize for ordinary consumers: lead with the result the user asked for, "
    "then add only the few details needed to understand it. Do not narrate your "
    "process, scripts, file paths, tools, commands, logs, or where you looked "
    "unless the user asks for debugging/provenance or those details materially "
    "affect the answer. For lookups, say what you found and the relevant "
    "value/time first; put optional caveats at the end."
)


@dataclass(frozen=True)
class PresentationPolicy:
    platform: str
    audience: str = "developer"
    language: str = "auto"
    result_first: bool = False
    details_on_demand: bool = False
    show_process: bool = True
    show_tool_trace: bool = True
    show_internal_paths: bool = True
    show_debug_errors: bool = True
    suppress_plain_text_busy_ack: bool = False
    approval_prompt_style: str = "technical"
    progress_notice_style: str = "technical"
    long_task_notice_delay_seconds: int | None = None
    long_task_heartbeat_seconds: int | None = None

    @property
    def is_public(self) -> bool:
        return self.audience == "public"


_DEVELOPER_DEFAULTS = PresentationPolicy(platform="")
_PUBLIC_DEFAULTS = PresentationPolicy(
    platform="",
    audience="public",
    language="zh-Hans",
    result_first=True,
    details_on_demand=True,
    show_process=False,
    show_tool_trace=False,
    show_internal_paths=False,
    show_debug_errors=False,
    suppress_plain_text_busy_ack=True,
    approval_prompt_style="summary",
    progress_notice_style="summary",
    long_task_notice_delay_seconds=30,
    long_task_heartbeat_seconds=90,
)

_PLATFORM_AUDIENCE_DEFAULTS = {
    "weixin": "public",
}


def platform_key(platform: Any) -> str:
    return str(getattr(platform, "value", platform) or "").strip().lower()


def _normalise_audience(value: Any, default: str) -> str:
    val = str(value or "").strip().lower()
    if val in {"public", "consumer", "customer", "大众", "普通用户"}:
        return "public"
    if val in {"developer", "dev", "technical", "operator", "debug"}:
        return "developer"
    return default


def _normalise_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _normalise_approval_style(value: Any, default: str) -> str:
    val = str(value or "").strip().lower()
    return val if val in {"technical", "summary"} else default


def _normalise_positive_int(value: Any, default: int | None) -> int | None:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else None


def _display_value(user_config: dict, platform: str, key: str) -> Any:
    display = user_config.get("display") or {}
    platforms = display.get("platforms") or {}
    platform_cfg = platforms.get(platform)
    if isinstance(platform_cfg, dict) and platform_cfg.get(key) is not None:
        return platform_cfg.get(key)
    return display.get(key)


def resolve_presentation_policy(user_config: dict | None = None, platform: Any = None) -> PresentationPolicy:
    """Resolve the presentation policy for a platform.

    Config lookup order:
      1. ``display.platforms.<platform>.<field>``
      2. ``display.<field>``
      3. built-in platform/audience defaults
    """
    cfg = user_config or {}
    plat = platform_key(platform)
    default_audience = _PLATFORM_AUDIENCE_DEFAULTS.get(plat, "developer")
    audience = _normalise_audience(_display_value(cfg, plat, "audience"), default_audience)

    base = _PUBLIC_DEFAULTS if audience == "public" else _DEVELOPER_DEFAULTS
    policy = replace(base, platform=plat, audience=audience)

    language = _display_value(cfg, plat, "language")
    if language is not None:
        policy = replace(policy, language=str(language))

    for field_name in (
        "result_first",
        "details_on_demand",
        "show_process",
        "show_tool_trace",
        "show_internal_paths",
        "show_debug_errors",
        "suppress_plain_text_busy_ack",
    ):
        val = _display_value(cfg, plat, field_name)
        if val is not None:
            policy = replace(policy, **{field_name: _normalise_bool(val, getattr(policy, field_name))})

    approval_style = _display_value(cfg, plat, "approval_prompt_style")
    if approval_style is not None:
        policy = replace(
            policy,
            approval_prompt_style=_normalise_approval_style(approval_style, policy.approval_prompt_style),
        )

    progress_style = _display_value(cfg, plat, "progress_notice_style")
    if progress_style is not None:
        policy = replace(
            policy,
            progress_notice_style=_normalise_approval_style(progress_style, policy.progress_notice_style),
        )

    for field_name in ("long_task_notice_delay_seconds", "long_task_heartbeat_seconds"):
        val = _display_value(cfg, plat, field_name)
        if val is not None:
            policy = replace(policy, **{field_name: _normalise_positive_int(val, getattr(policy, field_name))})

    return policy
