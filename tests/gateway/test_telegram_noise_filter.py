"""Gateway noise/secret filtering across chat surfaces (Telegram + siblings)."""

import pytest

from gateway.config import Platform
from gateway.run import (
    _destructive_slash_cancelled_reply,
    _destructive_slash_opt_out_note,
    _destructive_slash_prompt_message,
    _active_session_limit_reply,
    _activity_waits_for_user_response,
    _gateway_pairing_code_reply,
    _gateway_pairing_rate_limited_reply,
    _gateway_unexpected_error_reply,
    _gateway_update_prompt_message,
    _gateway_update_response_sent_reply,
    _long_running_notification_schedule,
    _prepare_gateway_status_message,
    _public_progress_notice,
    _public_progress_stage_label,
    _sanitize_gateway_final_response,
    _weixin_inactivity_timeout_reply,
    _weixin_inactivity_warning,
    _weixin_long_running_notice,
)

# Every human-facing chat surface that must receive noise-filtered,
# secret-redacted, provider-error-sanitized output (not just Telegram).
CHAT_PLATFORMS = [
    "telegram",
    "whatsapp",
    "discord",
    "slack",
    "signal",
    "matrix",
    "mattermost",
    "dingtalk",
    "feishu",
    "wecom",
    "weixin",
    "bluebubbles",
    "qqbot",
    "homeassistant",
    "sms",
]

NOISY_STATUS_MESSAGES = [
    "🗜️ Preflight compression check before sending...",
    "🗜️ Compacting context — summarizing earlier conversation so I can continue...",
    "⚠️  Session compressed 12 times — accuracy may degrade. Consider /new to start fresh.",
    "⚠ Compression summary failed: upstream error. Inserted a fallback context marker.",
    "⏱️ Rate limited. Waiting 30.0s (attempt 2/3)...",
    "⏳ Retrying in 4.2s (attempt 1/3)...",
]


def test_telegram_status_suppresses_auxiliary_and_retry_noise():
    """Auxiliary failures and retry backoff chatter should not hit Telegram."""
    noisy_messages = [
        "⚠ Auxiliary title generation failed: HTTP 400: Operation contains cybersecurity risk",
        "⚠ Compression summary failed: upstream error. Inserted a fallback context marker.",
        "🗜️ Compacting context — summarizing earlier conversation so I can continue...",
        "ℹ Configured compression model 'small-model' failed (timeout). Recovered using main model — check auxiliary.compression.model in config.yaml.",
        "⏳ Retrying in 4.2s (attempt 1/3)...",
        "⏱️ Rate limited. Waiting 30.0s (attempt 2/3)...",
        "⚠️ Max retries (3) exhausted — trying fallback...",
    ]

    for message in noisy_messages:
        assert _prepare_gateway_status_message(Platform.TELEGRAM, "warn", message) is None


def test_programmatic_surfaces_keep_raw_status():
    """Programmatic surfaces (local/api/webhook) must keep raw diagnostics.

    Negative case for the invariant: the chat-noise filter must not touch
    CLI/TUI diagnostics, API JSON, or webhook payloads.
    """
    message = "⏳ Retrying in 4.2s (attempt 1/3)..."

    for platform in ("local", "api_server", "webhook", "msgraph_webhook"):
        assert (
            _prepare_gateway_status_message(platform, "lifecycle", message) == message
        )


@pytest.mark.parametrize("platform", CHAT_PLATFORMS)
@pytest.mark.parametrize("message", NOISY_STATUS_MESSAGES)
def test_all_chat_gateways_suppress_noise(platform, message):
    """Operational lifecycle/retry noise must be suppressed on every chat surface."""
    assert _prepare_gateway_status_message(platform, "warn", message) is None


@pytest.mark.parametrize("platform", ["whatsapp", "slack", "signal", "matrix"])
def test_chat_gateways_redact_secret_in_provider_error(platform):
    """Provider-error bodies carrying secrets must never reach chat users.

    THE security invariant being widened from Telegram (#28533) to all chat
    surfaces (#39293): a leaked bearer token in a provider error body must be
    redacted/replaced before delivery on any chat platform.
    """
    raw = (
        "API call failed after 3 retries: HTTP 401 Unauthorized — "
        "Authorization: Bearer sk-ABCDEF0123456789abcdef0123"
    )

    sanitized = _sanitize_gateway_final_response(platform, raw)

    assert "sk-ABCDEF0123456789abcdef0123" not in sanitized
    assert "sk-ABCDEF" not in sanitized
    assert "HTTP 401" not in sanitized
    # The user gets the safe provider-error category instead of the raw body.
    assert "provider" in sanitized.lower()


@pytest.mark.parametrize("platform", ["whatsapp", "slack", "signal", "matrix"])
def test_chat_gateways_redact_secret_in_non_error_body(platform):
    """Secrets must be redacted even when no provider-error rewrite fires.

    The provider-error case above is rewritten wholesale to a generic
    category string, so it cannot, on its own, prove the secret-redaction
    layer works — the rewrite would strip the body regardless. This case
    feeds ordinary assistant prose that merely *echoes* a bearer token (not
    a provider-error envelope), so `_redact_gateway_user_facing_secrets` is
    the only thing standing between the token and the user. Removing the
    redaction patterns makes this fail (genuine regression guard); the
    surrounding prose must survive intact.
    """
    raw = (
        "Sure — here is the example request you asked for: "
        "curl -H 'Authorization: Bearer sk-ABCDEF0123456789abcdef0123' "
        "https://api.example.com/v1/models"
    )

    sanitized = _sanitize_gateway_final_response(platform, raw)

    assert "sk-ABCDEF0123456789abcdef0123" not in sanitized
    assert "sk-ABCDEF" not in sanitized
    # The secret body is gone — assert the invariant, not the specific mask
    # marker. The outbound redactor delegates to redact_sensitive_text (#23810),
    # which masks as `***`/partial; the local pattern fallback uses `[REDACTED]`.
    assert "***" in sanitized or "[REDACTED]" in sanitized
    # Non-secret prose is preserved — redaction is surgical, not a wholesale
    # rewrite, on bodies that are not provider-error envelopes.
    assert "here is the example request you asked for" in sanitized


def test_plugin_platform_string_suppresses_noise():
    """Unknown/plugin chat platforms fail closed to the chat-filter path."""
    message = "⏳ Retrying in 4.2s (attempt 1/3)..."

    assert _prepare_gateway_status_message("irc", "warn", message) is None


@pytest.mark.parametrize("platform", CHAT_PLATFORMS)
def test_chat_gateways_keep_normal_answers(platform):
    """Normal assistant content must pass through unchanged on chat surfaces."""
    answer = "Here is the clean summary you asked for."

    assert _sanitize_gateway_final_response(platform, answer) == answer


def test_telegram_status_sanitizes_raw_provider_security_errors():
    """Provider policy/security bodies should be replaced before chat delivery."""
    raw = (
        "❌ API failed after 3 retries — HTTP 400: request blocked because "
        "Operation contains cybersecurity risk. request_id=req_123"
    )

    sanitized = _prepare_gateway_status_message(Platform.TELEGRAM, "lifecycle", raw)

    assert sanitized is not None
    assert "provider rejected" in sanitized.lower()
    assert "cybersecurity risk" not in sanitized.lower()
    assert "HTTP 400" not in sanitized
    assert "req_123" not in sanitized


def test_telegram_final_response_sanitizes_raw_provider_errors():
    """Final Telegram replies should not expose raw provider/security details."""
    raw = (
        "API call failed after 3 retries: HTTP 400: This request was blocked "
        "under the provider cybersecurity risk policy. request_id=req_abc"
    )

    sanitized = _sanitize_gateway_final_response(Platform.TELEGRAM, raw)

    assert "provider rejected" in sanitized.lower()
    assert "cybersecurity risk" not in sanitized.lower()
    assert "HTTP 400" not in sanitized
    assert "req_abc" not in sanitized


def test_weixin_final_response_sanitizes_provider_errors_in_chinese():
    raw = (
        "API call failed after 3 retries: HTTP 401 Unauthorized — "
        "Authorization: Bearer sk-ABCDEF0123456789abcdef0123"
    )

    sanitized = _sanitize_gateway_final_response(Platform.WEIXIN, raw)

    assert "sk-ABCDEF" not in sanitized
    assert "HTTP 401" not in sanitized
    assert "Provider" not in sanitized
    assert "服务" in sanitized
    assert "请稍后再试" in sanitized


def test_weixin_final_response_strips_file_mutation_verifier_footer_only():
    raw = (
        "验证结果：\n\n"
        "- `opencli-ipv4-bridge.service`：active (running)\n"
        "- `opencli doctor`：Everything looks good\n\n"
        "⚠️ File-mutation verifier: 1 file(s) were NOT modified this turn "
        "despite any wording above that may suggest otherwise. Run `git status` "
        "or `read_file` to confirm.\n"
        "  • `/etc/systemd/system/opencli-ipv4-bridge.service` — [write_file] "
        "Refusing to write to sensitive system path."
    )

    sanitized = _sanitize_gateway_final_response(Platform.WEIXIN, raw)

    assert "File-mutation verifier" not in sanitized
    assert "Refusing to write to sensitive system path" not in sanitized
    assert "active (running)" in sanitized
    assert "Everything looks good" in sanitized
    assert "`opencli doctor`" in sanitized


def test_weixin_runtime_notices_are_public_friendly_chinese():
    assert _weixin_long_running_notice(3) == "⏳ 我还在处理，已用约 3 分钟。"
    assert _public_progress_notice(elapsed_seconds=30, first=True) == "收到，我正在处理，可能需要一会儿。"
    assert _public_progress_notice(elapsed_seconds=95) == "还在处理，已用约 1 分钟。"
    assert (
        _public_progress_notice(elapsed_seconds=125, activity="terminal")
        == "还在处理，当前在准备或执行操作，已用约 2 分钟。"
    )
    assert _public_progress_stage_label("web_search") == "查找资料"
    assert _public_progress_stage_label("read_file") == "读取和整理数据"
    assert _public_progress_stage_label("pytest") == "验证结果"
    warning = _weixin_inactivity_warning(15)
    timeout = _weixin_inactivity_timeout_reply()

    assert "15 分钟" in warning
    assert "继续等待" in warning
    assert "/new" in warning
    assert "处理时间太长" in timeout
    assert "/new" in timeout
    assert "agent" not in warning.lower()
    assert "gateway_timeout" not in timeout


def test_user_wait_activity_suppresses_long_running_heartbeat():
    assert _activity_waits_for_user_response("waiting for user clarify response") is True
    assert _activity_waits_for_user_response("waiting for user approval") is True
    assert _activity_waits_for_user_response("terminal: npm install") is False
    assert _activity_waits_for_user_response("") is False


def test_weixin_gateway_control_prompts_are_public_friendly_chinese():
    pairing = _gateway_pairing_code_reply(
        Platform.WEIXIN,
        platform_name="weixin",
        code="123456",
    )
    assert "配对码" in pairing
    assert "I don't recognize" not in pairing

    assert _gateway_pairing_rate_limited_reply(Platform.WEIXIN) == "配对请求太频繁了，请稍后再试。"

    update_prompt = _gateway_update_prompt_message(
        Platform.WEIXIN,
        prompt="是否继续？",
        default="n",
        prefix="/",
    )
    assert "更新需要你确认" in update_prompt
    assert "Reply" not in update_prompt
    assert _gateway_update_response_sent_reply(Platform.WEIXIN, "y") == "已把 `y` 发给更新流程。"

    confirm = _destructive_slash_prompt_message(
        Platform.WEIXIN,
        command="new",
        detail="This starts a fresh session and discards the current conversation history.",
        prefix="/",
    )
    assert "请确认 /new" in confirm
    assert "开启一个全新的对话" in confirm
    assert "Choose:" not in confirm
    assert _destructive_slash_cancelled_reply(Platform.WEIXIN, "new") == "🟡 已取消 /new，当前聊天没有变化。"
    assert "以后 /clear" in _destructive_slash_opt_out_note(Platform.WEIXIN)
    assert "会话已满" in _active_session_limit_reply(
        Platform.WEIXIN,
        active_count=2,
        max_sessions=2,
    )
    assert "处理时遇到异常" in _gateway_unexpected_error_reply(
        Platform.WEIXIN,
        status_code=429,
        history_len=1,
    )
    assert "聊天内容太长" in _gateway_unexpected_error_reply(
        Platform.WEIXIN,
        status_code=400,
        history_len=80,
    )


def test_non_weixin_gateway_control_prompts_keep_existing_english():
    pairing = _gateway_pairing_code_reply(
        Platform.TELEGRAM,
        platform_name="telegram",
        code="123456",
    )
    assert "Here's your pairing code" in pairing

    update_prompt = _gateway_update_prompt_message(
        Platform.TELEGRAM,
        prompt="Continue?",
        default="n",
        prefix="/",
    )
    assert "Update needs your input" in update_prompt
    assert "Reply `/approve`" in update_prompt

    confirm = _destructive_slash_prompt_message(
        Platform.TELEGRAM,
        command="new",
        detail="This starts a fresh session.",
        prefix="/",
    )
    assert "Confirm /new" in confirm
    assert "Choose:" in confirm
    assert "active session limit" in _active_session_limit_reply(
        Platform.TELEGRAM,
        active_count=2,
        max_sessions=2,
    )
    assert "unexpected error" in _gateway_unexpected_error_reply(
        Platform.TELEGRAM,
        status_code=429,
        history_len=1,
    )


def test_public_presentation_schedule_enables_weixin_reassurance_by_default():
    first_delay, heartbeat, policy = _long_running_notification_schedule({}, Platform.WEIXIN, 180)

    assert policy.progress_notice_style == "summary"
    assert first_delay == 60.0
    assert heartbeat == 300.0


def test_public_presentation_schedule_respects_explicit_disable():
    cfg = {"display": {"platforms": {"weixin": {"long_running_notifications": False}}}}

    first_delay, heartbeat, policy = _long_running_notification_schedule(cfg, Platform.WEIXIN, 180)

    assert policy.progress_notice_style == "summary"
    assert first_delay is None
    assert heartbeat is None


def test_public_presentation_schedule_can_be_tuned():
    cfg = {
        "display": {
            "platforms": {
                "weixin": {
                    "long_task_notice_delay_seconds": 45,
                    "long_task_heartbeat_seconds": 120,
                }
            }
        }
    }

    first_delay, heartbeat, _policy = _long_running_notification_schedule(cfg, Platform.WEIXIN, 180)

    assert first_delay == 45.0
    assert heartbeat == 120.0


def test_telegram_final_response_redacts_auth_secrets():
    """Authentication errors should be useful without leaking key material."""
    raw = (
        "⚠️ Provider authentication failed: Incorrect API key provided: "
        "sk-live_abcdefghijklmnopqrstuvwxyz1234567890"
    )

    sanitized = _sanitize_gateway_final_response(Platform.TELEGRAM, raw)

    assert "authentication failed" in sanitized.lower()
    assert "check the configured credentials" in sanitized.lower()
    assert "sk-live" not in sanitized


def test_telegram_final_response_keeps_normal_answers():
    """Normal assistant content should not be rewritten."""
    answer = "Here is the clean summary you asked for."

    assert _sanitize_gateway_final_response(Platform.TELEGRAM, answer) == answer


# Synthetic credential shapes from #23810. Bodies are placeholder gibberish —
# never real tokens — but they match the canonical redaction patterns. The
# outbound gateway redactor previously used a narrow local pattern subset that
# leaked the GitHub fine-grained PAT and Telegram bot-token shapes; it now
# delegates to agent.redact.redact_sensitive_text, the authoritative redactor
# already used for logs/tool-output/approval prompts.
_ISSUE_23810_SECRET_SHAPES = {
    "openai_sk": "sk-" + "a1b2c3d4e5f6a7b8c9d0",
    "github_fine_grained_pat": "github_pat_" + "1A" * 41,
    "github_classic_pat": "ghp_" + "Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx",
    "telegram_bot_token": "bot1234567890:" + "AAH" * 13 + "x",
    "openrouter_v1": "sk-or-v1-" + "Z9" * 36 + "q",
}


@pytest.mark.parametrize("platform", CHAT_PLATFORMS)
@pytest.mark.parametrize("shape_name", sorted(_ISSUE_23810_SECRET_SHAPES))
def test_chat_gateways_redact_all_issue_23810_credential_shapes(platform, shape_name):
    """Outbound chat must mask every credential shape the banner promises.

    Regression guard for #23810: the gateway claimed "chat responses are
    scrubbed before delivery", but the outbound redactor used a divergent
    narrow pattern set that leaked the GitHub fine-grained PAT and Telegram
    bot-token shapes verbatim. Feed each shape as ordinary assistant prose
    (not a provider-error envelope, so no wholesale rewrite fires) and assert
    the secret body never reaches the user while surrounding prose survives.
    """
    secret = _ISSUE_23810_SECRET_SHAPES[shape_name]
    raw = f"Sure, here is the token you asked me to echo: {secret} — done."

    sanitized = _sanitize_gateway_final_response(platform, raw)

    assert secret not in sanitized, f"{shape_name} leaked verbatim on {platform}"
    # Prose around the secret is preserved — redaction is surgical.
    assert "here is the token you asked me to echo" in sanitized
    assert sanitized.endswith("done.")
