"""Tests that /new (and its /reset alias) clears session-scoped overrides."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource, build_session_key


def _make_source(platform: Platform = Platform.TELEGRAM) -> SessionSource:
    return SessionSource(
        platform=platform,
        user_id="u1",
        chat_id="c1",
        user_name="tester",
        chat_type="dm",
    )


def _make_event(text: str, platform: Platform = Platform.TELEGRAM) -> MessageEvent:
    return MessageEvent(text=text, source=_make_source(platform), message_id="m1")


def _make_runner(platform: Platform = Platform.TELEGRAM):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={platform: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.send = AsyncMock()
    runner.adapters = {platform: adapter}
    runner._voice_mode = {}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    runner._session_model_overrides = {}
    runner._session_reasoning_overrides = {}
    runner._pending_model_notes = {}
    runner._background_tasks = set()

    session_key = build_session_key(_make_source(platform))
    session_entry = SessionEntry(
        session_key=session_key,
        session_id="sess-1",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=platform,
        chat_type="dm",
    )
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = session_entry
    runner.session_store.reset_session.return_value = session_entry
    runner.session_store._entries = {session_key: session_entry}
    runner.session_store._generate_session_key.return_value = session_key
    runner._running_agents = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._session_db = None
    runner._agent_cache_lock = None  # disables _evict_cached_agent lock path
    runner._is_user_authorized = lambda _source: True
    runner._format_session_info = lambda: ""

    return runner


@pytest.mark.asyncio
async def test_new_command_clears_session_model_override():
    """/new must remove the session-scoped model override for that session."""
    runner = _make_runner()
    session_key = build_session_key(_make_source())

    # Simulate a prior /model switch stored as a session override
    runner._session_model_overrides[session_key] = {
        "model": "gpt-4o",
        "provider": "openai",
        "api_key": "***",
        "base_url": "",
        "api_mode": "openai",
    }
    runner._session_reasoning_overrides[session_key] = {"enabled": True, "effort": "high"}
    runner._pending_model_notes[session_key] = "[Note: switched to gpt-4o.]"

    await runner._handle_reset_command(_make_event("/new"))

    assert session_key not in runner._session_model_overrides
    assert session_key not in runner._session_reasoning_overrides
    assert session_key not in runner._pending_model_notes


@pytest.mark.asyncio
async def test_new_command_no_override_is_noop():
    """/new with no prior model override must not raise."""
    runner = _make_runner()
    session_key = build_session_key(_make_source())

    assert session_key not in runner._session_model_overrides
    assert session_key not in runner._session_reasoning_overrides

    await runner._handle_reset_command(_make_event("/new"))

    assert session_key not in runner._session_model_overrides
    assert session_key not in runner._session_reasoning_overrides


@pytest.mark.asyncio
async def test_new_command_only_clears_own_session():
    """/new must only clear the override for the session that triggered it."""
    runner = _make_runner()
    session_key = build_session_key(_make_source())
    other_key = "other_session_key"

    runner._session_model_overrides[session_key] = {
        "model": "gpt-4o",
        "provider": "openai",
        "api_key": "sk-test",
        "base_url": "",
        "api_mode": "openai",
    }
    runner._session_model_overrides[other_key] = {
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "api_key": "***",
        "base_url": "",
        "api_mode": "anthropic",
    }
    runner._session_reasoning_overrides[session_key] = {"enabled": True, "effort": "high"}
    runner._session_reasoning_overrides[other_key] = {"enabled": True, "effort": "low"}
    runner._pending_model_notes[session_key] = "[Note: switched to gpt-4o.]"
    runner._pending_model_notes[other_key] = "[Note: switched to claude-sonnet-4-6.]"

    await runner._handle_reset_command(_make_event("/new"))

    assert session_key not in runner._session_model_overrides
    assert other_key in runner._session_model_overrides
    assert session_key not in runner._session_reasoning_overrides
    assert other_key in runner._session_reasoning_overrides
    assert session_key not in runner._pending_model_notes
    assert other_key in runner._pending_model_notes


@pytest.mark.asyncio
async def test_weixin_new_command_returns_public_friendly_chinese_reply():
    """Weixin /new should not expose developer runtime metadata to end users."""
    runner = _make_runner(Platform.WEIXIN)
    runner._format_session_info = lambda: (
        "◆ Model: `gpt-5.4`\n"
        "◆ Provider: openai-codex\n"
        "◆ Context: 1.0M tokens (config)"
    )

    result = await runner._handle_reset_command(_make_event("/new", Platform.WEIXIN))
    reply = str(result)

    assert reply.startswith("✨ 已开启新对话")
    assert "\n\n我已经清空刚才这轮聊天的上下文。\n\n" in reply
    assert "你可以直接发送新的问题或需求。" in reply
    assert "Model:" not in reply
    assert "Provider:" not in reply
    assert "Context:" not in reply
    assert "tokens" not in reply
    assert "提示" not in reply
    assert "/image" not in reply


@pytest.mark.asyncio
async def test_weixin_new_command_uses_saved_title_in_public_reply():
    """Weixin title display should come from structured reset state."""
    runner = _make_runner(Platform.WEIXIN)
    runner._session_db = AsyncMock()

    result = await runner._handle_reset_command(
        _make_event("/new 我的旅行计划", Platform.WEIXIN)
    )
    reply = str(result)

    runner._session_db.set_session_title.assert_called_once_with("sess-1", "我的旅行计划")
    assert reply.startswith("✨ 已开启新对话：我的旅行计划")
    assert "Model:" not in reply
    assert "Provider:" not in reply
