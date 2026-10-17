"""Explicit opt-in checks using the DeepSeek provider from MaiBot model settings."""

import json
import os

import pytest

from test_provider_behavior import make_plugin

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_DEEPSEEK_INTEGRATION") != "1", reason="真实 API 测试需显式启用，可能产生费用"),
]


def make_live_plugin():
    overrides = {"debug": {"log_search_sources": False}}
    path = os.getenv("DEEPSEEK_TEST_MODEL_CONFIG")
    if path:
        overrides["provider"] = {"model_config_path": path}
    return make_plugin(overrides)


async def test_live_search():
    _, plugin = make_live_plugin()
    try:
        result = await plugin.handle_search_and_summarize(query="DeepSeek site:deepseek.com", count=1)
        assert result["success"], result["content"]
        assert json.loads(result["content"])["results"]
    finally:
        await plugin.on_unload()


async def test_live_fetch():
    _, plugin = make_live_plugin()
    try:
        result = await plugin.handle_fetch_page(url="https://example.com/")
        assert result["success"], result["content"]
        data = json.loads(result["content"])
        assert data["content"].strip() and "Example" in data["title"]
    finally:
        await plugin.on_unload()
