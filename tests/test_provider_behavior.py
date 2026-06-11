"""DeepSeek Anthropic Provider 插件测试（v0.2.3 Tool 模式）。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import importlib.util
import json
import os
import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PLUGIN_PATH = PLUGIN_DIR / "plugin.py"
MANIFEST_PATH = PLUGIN_DIR / "_manifest.json"
CONFIG_PATH = PLUGIN_DIR / "config.toml"
PYPROJECT_PATH = PLUGIN_DIR / "pyproject.toml"
UV_LOCK_PATH = PLUGIN_DIR / "uv.lock"


def load_plugin_module():
    """加载插件模块。"""
    spec = importlib.util.spec_from_file_location("deepseek_anthropic_provider_plugin", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_plugin(config_overrides: dict[str, Any] | None = None):
    """创建插件实例并注入 mock ctx。"""
    module = load_plugin_module()
    plugin = module.create_plugin()
    config = plugin.get_default_config()
    if config_overrides:
        for section, values in config_overrides.items():
            config.setdefault(section, {}).update(values)
    plugin.set_plugin_config(config)
    logger = SimpleNamespace(
        debug=MagicMock(),
        info=MagicMock(),
        warning=MagicMock(),
        error=MagicMock(),
    )
    plugin._set_context(
        SimpleNamespace(
            logger=logger
        )
    )
    plugin.ctx.send = SimpleNamespace(text=AsyncMock())
    return module, plugin


# ================================================================
# Manifest 测试
# ================================================================

def test_manifest_has_no_llm_providers() -> None:
    """Manifest 不应该声明 llm_providers。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "llm_providers" not in manifest
    assert manifest["id"] == "LowValueTarget.deepseek-anthropic-provider"
    assert manifest["version"] == "0.2.3"
    assert "tool" in manifest["capabilities"]
    assert "i18n" in manifest
    assert manifest["i18n"]["default_locale"] == "zh-CN"


def test_config_template_does_not_contain_api_key() -> None:
    """配置模板不应提交真实 API Key。"""
    config_text = CONFIG_PATH.read_text(encoding="utf-8")

    assert 'api_key = ""' in config_text
    assert "sk-" not in config_text


def test_project_version_matches_manifest() -> None:
    """pyproject 版本应与 manifest 版本一致。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    lock_text = UV_LOCK_PATH.read_text(encoding="utf-8")

    assert f'version = "{manifest["version"]}"' in pyproject_text
    assert f'config_version = "{manifest["version"]}"' in config_text
    assert f'name = "deepseek-anthropic-provider"\nversion = "{manifest["version"]}"' in lock_text


def test_sdk_dependency_is_bounded_before_v3() -> None:
    """发布依赖应避免自动安装未来不兼容的 Plugin SDK 3。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    sdk_dependency = next(item for item in manifest["dependencies"] if item["name"] == "maibot-plugin-sdk")

    assert sdk_dependency["version_spec"] == ">=2.0.0,<3.0.0"
    assert '"maibot-plugin-sdk>=2.0.0,<3.0.0"' in pyproject_text


# ================================================================
# Config Schema 测试
# ================================================================

def test_config_schema_uses_select_labels() -> None:
    """WebUI 配置 schema 应包含中文 label 的 select 选项。"""
    module = load_plugin_module()
    schema = module.DeepSeekAnthropicProviderPlugin.build_config_schema(
        plugin_id="LowValueTarget.deepseek-anthropic-provider",
        plugin_name="DeepSeek Anthropic Provider",
        plugin_version="0.2.3",
        plugin_description="测试",
        plugin_author="LowValueTarget",
    )
    sections = schema["sections"]
    assert sections["model"]["title"] == "模型设置"
    assert sections["thinking"]["title"] == "思考设置"
    assert sections["search"]["title"] == "联网搜索"
    assert sections["auth"]["title"] == "密钥设置"

    model_field = sections["model"]["fields"]["model_choice"]
    thinking_field = sections["thinking"]["fields"]["thinking_mode"]
    effort_field = sections["thinking"]["fields"]["thinking_effort"]
    tool_field = sections["search"]["fields"]["web_search_tool"]
    policy_field = sections["search"]["fields"]["search_policy"]

    assert model_field["ui_type"] == "select"
    assert model_field["default"] == "deepseek-v4-flash"
    assert model_field["choice_labels"] == {
        "deepseek-v4-pro": "DeepSeek V4 Pro（更聪明，成本更高）",
        "deepseek-v4-flash": "DeepSeek V4 Flash（更快，更省钱）",
    }
    assert thinking_field["ui_type"] == "select"
    assert thinking_field["choice_labels"] == {"enabled": "开启思考", "disabled": "关闭思考"}
    assert effort_field["ui_type"] == "select"
    assert effort_field["choice_labels"] == {"high": "标准思考", "max": "深度思考"}
    assert tool_field["ui_type"] == "select"
    assert policy_field["ui_type"] == "select"
    assert policy_field["default"] == "balanced"
    assert policy_field["choice_labels"] == {
        "active": "更积极",
        "balanced": "按需搜索",
        "explicit": "仅显式请求",
    }
    assert sections["plugin"]["fields"]["config_version"]["hidden"] is True
    assert sections["model"]["fields"]["max_tokens"]["default"] == 4096
    assert sections["model"]["fields"]["max_tokens"]["hint"]
    for section_name, field_name in (
        ("model", "model_choice"),
        ("thinking", "thinking_mode"),
        ("thinking", "thinking_effort"),
        ("search", "web_search_tool"),
        ("search", "search_policy"),
    ):
        assert sections[section_name]["fields"][field_name]["hint"]


def test_legacy_model_tool_config_is_normalized() -> None:
    """0.2.0 的 model_tool 配置应迁移到新分组并保留选择。"""
    module = load_plugin_module()
    plugin = module.create_plugin()
    normalized, changed = plugin.normalize_plugin_config(
        {
            "plugin": {"enabled": True, "config_version": "0.2.0"},
            "model": {"model_choice": "deepseek-v4-flash"},
            "search": {
                "enabled": True,
                "web_search_tool": "web_search_20260209",
                "max_search_uses": 5,
                "search_policy": "balanced",
            },
            "model_tool": {
                "model_choice": "deepseek-v4-pro",
                "web_search_tool": "web_search_20250305",
                "max_search_uses": 3,
            },
        }
    )

    assert changed is True
    assert normalized["plugin"]["config_version"] == "0.2.3"
    assert normalized["model"]["model_choice"] == "deepseek-v4-pro"
    assert normalized["search"]["web_search_tool"] == "web_search_20250305"
    assert normalized["search"]["max_search_uses"] == 3
    assert "model_tool" not in normalized


def test_legacy_choice_values_and_fields_are_normalized() -> None:
    """旧中文值、follow_model_config 和 max_uses 应迁移为稳定内部值。"""
    module = load_plugin_module()
    plugin = module.create_plugin()
    normalized, changed = plugin.normalize_plugin_config(
        {
            "plugin": {"enabled": True, "config_version": "0.1.1"},
            "model": {"model_choice": "跟随 MaiBot 模型配置（高级）"},
            "thinking": {"thinking_mode": "关闭思考", "thinking_effort": "深度思考 max"},
            "search": {"enabled": True, "max_uses": 2, "search_policy": "更积极"},
        }
    )

    assert changed is True
    assert normalized["model"]["model_choice"] == "deepseek-v4-pro"
    assert normalized["thinking"] == {"thinking_mode": "disabled", "thinking_effort": "max"}
    assert normalized["search"]["max_search_uses"] == 2
    assert normalized["search"]["search_policy"] == "active"
    assert "max_uses" not in normalized["search"]


def test_future_config_version_is_preserved() -> None:
    """未来版本配置不能被旧插件降级或删除未知字段。"""
    module = load_plugin_module()
    plugin = module.create_plugin()
    raw_config = {
        "plugin": {"enabled": True, "config_version": "9.0.0"},
        "model": {"model_choice": "deepseek-v4-flash"},
        "future": {"keep": "me"},
    }

    normalized, changed = plugin.normalize_plugin_config(raw_config)

    assert normalized == raw_config
    assert normalized is not raw_config
    assert changed is False


# ================================================================
# API Key 解析测试
# ================================================================

def test_resolve_api_key_from_config_first() -> None:
    """插件配置里的 key 优先。"""
    module, plugin = make_plugin({"auth": {"api_key": "sk-config-key", "api_key_env": "FAKE_ENV"}})
    with patch.dict(os.environ, {"FAKE_ENV": "sk-env-key"}, clear=True):
        key = module._resolve_api_key(plugin.config)
    assert key == "sk-config-key"


def test_resolve_api_key_falls_back_to_env() -> None:
    """留空 key 时读取环境变量。"""
    module, plugin = make_plugin({"auth": {"api_key": "", "api_key_env": "DS_TEST_KEY"}})
    with patch.dict(os.environ, {"DS_TEST_KEY": "sk-env-key"}, clear=True):
        key = module._resolve_api_key(plugin.config)
    assert key == "sk-env-key"


def test_resolve_api_key_returns_empty_when_none() -> None:
    """无配置无环境变量时返回空串。"""
    module, plugin = make_plugin({"auth": {"api_key": "", "api_key_env": "NONEXISTENT"}})
    with patch.dict(os.environ, {}, clear=True):
        key = module._resolve_api_key(plugin.config)
    assert key == ""


# ================================================================
# Component 注册测试
# ================================================================

def test_three_tools_are_registered() -> None:
    """插件应通过 get_components() 注册三个 Tool。"""
    _module, plugin = make_plugin()
    components = plugin.get_components()
    tool_names = {c["name"] for c in components if c["type"] == "TOOL"}
    assert tool_names == {"search_and_summarize", "fetch_page", "deepseek_proxy"}


def test_commands_are_registered() -> None:
    """插件应注册两个测试命令。"""
    _module, plugin = make_plugin()
    components = plugin.get_components()
    command_names = {c["name"] for c in components if c["type"] == "COMMAND"}
    assert "deepseek_anthropic_ping" in command_names
    assert "deepseek_anthropic_search_test" in command_names


# ================================================================
# Tool 输入验证测试
# ================================================================

async def test_search_and_summarize_empty_query() -> None:
    """空 query 应有提示。"""
    _module, plugin = make_plugin()
    result = await plugin.handle_search_and_summarize(query="")
    assert "请提供搜索查询词" in result["content"]


async def test_fetch_page_empty_url() -> None:
    """空 URL 应有提示。"""
    _module, plugin = make_plugin()
    result = await plugin.handle_fetch_page(url="")
    assert "请提供要读取的网页 URL" in result["content"]


async def test_deepseek_proxy_empty_prompt() -> None:
    """空 prompt 应有提示。"""
    _module, plugin = make_plugin()
    result = await plugin.handle_deepseek_proxy(prompt="")
    assert "请提供要处理的 prompt" in result["content"]


async def test_tool_does_not_return_unexpected_raw_exception() -> None:
    """意外异常只写日志，不应原样展示给聊天用户。"""
    _module, plugin = make_plugin()

    with patch.object(
        plugin,
        "_call_deepseek",
        new=AsyncMock(side_effect=RuntimeError("SECRET_RAW_ERROR")),
    ):
        result = await plugin.handle_deepseek_proxy(prompt="测试")

    assert result["content"] == "DeepSeek 处理失败，请查看插件日志。"
    assert "SECRET_RAW_ERROR" not in result["content"]
    plugin.ctx.logger.error.assert_called()


# ================================================================
# _call_deepseek 请求拼装测试
# ================================================================

def test_build_search_time_context_uses_local_time_with_timezone() -> None:
    """搜索时间上下文应包含具体时间、时区名和带冒号的 UTC 偏移。"""
    module = load_plugin_module()
    fixed_time = datetime(
        2026,
        6,
        11,
        15,
        30,
        0,
        tzinfo=timezone(timedelta(hours=8), name="CST"),
    )

    with patch.object(
        module,
        "datetime",
        SimpleNamespace(now=lambda: SimpleNamespace(astimezone=lambda: fixed_time)),
    ):
        context = module._build_search_time_context()

    assert "2026年06月11日 15:30:00（CST，UTC+08:00）" in context
    assert "今天、最新、近期、今年" in context
    assert "核对搜索结果的发布日期" in context


async def test_call_deepseek_passes_correct_params_to_anthropic() -> None:
    """_call_deepseek 应传递正确的 model、system、tools 给 Anthropic SDK。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test", "base_url": "https://api.deepseek.com/anthropic"}})

    mock_response = SimpleNamespace(
        model="deepseek-v4-pro",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="回复内容", citations=[])],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )

    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await plugin._call_deepseek(
            "测试",
            system="你是助手",
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
        )

    assert result == "回复内容"
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "deepseek-v4-flash"
    assert call_kwargs["system"].startswith("你是助手\n\n【当前时间】")
    assert "今天、最新、近期、今年" in call_kwargs["system"]
    assert call_kwargs["max_tokens"] == 4096
    assert call_kwargs["messages"] == [{"role": "user", "content": "测试"}]
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0]["name"] == "web_search"
    assert call_kwargs["thinking"] == {"type": "enabled"}
    assert call_kwargs["output_config"] == {"effort": "high"}


async def test_call_deepseek_uses_configured_max_tokens() -> None:
    """最大输出长度应传给 Anthropic SDK。"""
    _module, plugin = make_plugin(
        {
            "auth": {"api_key": "sk-test"},
            "model": {"max_tokens": 8192},
        }
    )
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="长回复", citations=[])],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await plugin._call_deepseek("请详细回答")

    assert mock_client.messages.create.call_args.kwargs["max_tokens"] == 8192


async def test_call_deepseek_without_tools() -> None:
    """不传 tools 时请求 body 不应包含 tools 字段。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})

    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="简单的回复", citations=[])],
        usage=SimpleNamespace(input_tokens=5, output_tokens=10),
    )

    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await plugin._call_deepseek("你好")

    assert result == "简单的回复"
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "tools" not in call_kwargs
    assert "system" not in call_kwargs


async def test_call_deepseek_injects_time_for_web_search_type_without_system() -> None:
    """仅通过工具类型识别 Web Search 时，也应生成时间系统提示。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="搜索回答", citations=[])],
        usage=SimpleNamespace(input_tokens=5, output_tokens=10),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await plugin._call_deepseek(
            "搜索",
            tools=[{"type": "web_search_20260209", "name": "custom_search", "max_uses": 1}],
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"].startswith("【当前时间】")
    assert "UTC" in call_kwargs["system"]


async def test_call_deepseek_injects_time_for_web_search_name() -> None:
    """工具名称为 web_search 时应注入时间，即使类型不是标准版本名。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="搜索回答", citations=[])],
        usage=SimpleNamespace(input_tokens=5, output_tokens=10),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await plugin._call_deepseek(
            "搜索",
            system="保留这段系统提示。",
            tools=[{"type": "custom_tool", "name": "web_search"}],
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["system"].startswith("保留这段系统提示。\n\n【当前时间】")


async def test_call_deepseek_does_not_inject_time_for_non_search_tool() -> None:
    """非搜索工具请求不应获得当前时间上下文。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="普通回答", citations=[])],
        usage=SimpleNamespace(input_tokens=5, output_tokens=10),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await plugin._call_deepseek(
            "普通任务",
            system="原系统提示",
            tools=[{"type": "custom_tool", "name": "calculator"}],
        )

    assert mock_client.messages.create.call_args.kwargs["system"] == "原系统提示"


async def test_call_deepseek_passes_disabled_thinking_without_effort() -> None:
    """关闭思考时只传 disabled，不应传 output_config。"""
    _module, plugin = make_plugin(
        {
            "auth": {"api_key": "sk-test"},
            "thinking": {"thinking_mode": "disabled", "thinking_effort": "max"},
        }
    )
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="快速回复", citations=[])],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await plugin._call_deepseek("你好")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["thinking"] == {"type": "disabled"}
    assert "output_config" not in call_kwargs


async def test_call_deepseek_uses_configured_model() -> None:
    """应使用配置里选择的模型。"""
    _module, plugin = make_plugin({
        "auth": {"api_key": "sk-test"},
        "model": {"model_choice": "deepseek-v4-flash"},
    })

    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="Flash 回复", citations=[])],
        usage=SimpleNamespace(input_tokens=3, output_tokens=5),
    )

    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await plugin._call_deepseek("测试")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "deepseek-v4-flash"


async def test_call_deepseek_logs_web_search_tool_result_citations() -> None:
    """server web search 结果里的 URL 应进入搜索来源日志。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})

    mock_response = SimpleNamespace(
        model="deepseek-v4-pro",
        stop_reason="end_turn",
        content=[
            SimpleNamespace(
                type="web_search_tool_result",
                content=[{"title": "DeepSeek 文档", "url": "https://api-docs.deepseek.com"}],
            ),
            SimpleNamespace(type="text", text="搜索后的回复", citations=[]),
        ],
        usage=SimpleNamespace(input_tokens=5, output_tokens=10),
    )

    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await plugin._call_deepseek("搜索一下")

    assert result == "搜索后的回复"
    plugin.ctx.logger.info.assert_called_with(
        "DeepSeek Anthropic 搜索来源: %s",
        [{"title": "DeepSeek 文档", "url": "https://api-docs.deepseek.com"}],
    )


def test_extracts_and_deduplicates_real_sdk_search_sources() -> None:
    """真实 Anthropic SDK 对象形式的来源应按 URL 去重。"""
    from anthropic.types import CitationsWebSearchResultLocation, WebSearchResultBlock

    module = load_plugin_module()
    citation = CitationsWebSearchResultLocation(
        cited_text="DeepSeek 文档",
        encrypted_index="index",
        title="DeepSeek 文档",
        type="web_search_result_location",
        url="https://api-docs.deepseek.com",
    )
    result = WebSearchResultBlock(
        encrypted_content="content",
        page_age="2026-06-11",
        title="重复来源",
        type="web_search_result",
        url="https://api-docs.deepseek.com",
    )

    sources = module._extract_citations_from_block(
        {"citations": [citation], "content": [result, result]}
    )

    assert sources == [{"title": "DeepSeek 文档", "url": "https://api-docs.deepseek.com"}]


async def test_call_deepseek_logs_deduplicated_real_sdk_search_sources() -> None:
    """真实 SDK text citation 和搜索结果对象应合并去重后写入日志。"""
    from anthropic.types import (
        CitationsWebSearchResultLocation,
        TextBlock,
        WebSearchResultBlock,
        WebSearchToolResultBlock,
    )

    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    citation = CitationsWebSearchResultLocation(
        cited_text="DeepSeek 文档",
        encrypted_index="index",
        title="DeepSeek 文档",
        type="web_search_result_location",
        url="https://api-docs.deepseek.com",
    )
    result = WebSearchResultBlock(
        encrypted_content="content",
        page_age="2026-06-11",
        title="重复来源",
        type="web_search_result",
        url="https://api-docs.deepseek.com",
    )
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[
            WebSearchToolResultBlock(
                content=[result],
                tool_use_id="toolu_1",
                type="web_search_tool_result",
            ),
            TextBlock(citations=[citation], text="搜索回答", type="text"),
        ],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result_text = await plugin._call_deepseek("搜索")

    assert result_text == "搜索回答"
    plugin.ctx.logger.info.assert_called_with(
        "DeepSeek Anthropic 搜索来源: %s",
        [{"title": "重复来源", "url": "https://api-docs.deepseek.com"}],
    )


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("max_uses_exceeded", "联网搜索失败：已达到每轮最多搜索次数。"),
        ("unavailable", "联网搜索失败：搜索服务暂时不可用。"),
    ],
)
async def test_call_deepseek_returns_clear_search_error_without_final_text(
    error_code: str,
    expected: str,
) -> None:
    """搜索工具失败且没有最终回答时，应返回清晰中文错误。"""
    from anthropic.types import WebSearchToolResultError

    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[
            SimpleNamespace(
                type="web_search_tool_result",
                content=WebSearchToolResultError(
                    type="web_search_tool_result_error",
                    error_code=error_code,
                ),
            )
        ],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await plugin._call_deepseek("搜索")

    assert result == expected
    plugin.ctx.logger.warning.assert_called()


async def test_call_deepseek_keeps_final_text_when_search_tool_failed() -> None:
    """搜索工具失败但已有最终回答时，只记录警告并保留回答。"""
    from anthropic.types import WebSearchToolResultError

    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="end_turn",
        content=[
            SimpleNamespace(
                type="web_search_tool_result",
                content=WebSearchToolResultError(
                    type="web_search_tool_result_error",
                    error_code="unavailable",
                ),
            ),
            SimpleNamespace(type="text", text="仍然可用的回答", citations=[]),
        ],
        usage=SimpleNamespace(input_tokens=2, output_tokens=3),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await plugin._call_deepseek("搜索")

    assert result == "仍然可用的回答"
    plugin.ctx.logger.warning.assert_called()


async def test_call_deepseek_reports_max_tokens_without_final_text() -> None:
    """没有最终文本且达到输出上限时，应提示调高最大输出长度。"""
    _module, plugin = make_plugin({"auth": {"api_key": "sk-test"}})
    mock_response = SimpleNamespace(
        model="deepseek-v4-flash",
        stop_reason="max_tokens",
        content=[],
        usage=SimpleNamespace(input_tokens=2, output_tokens=4096),
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.close = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        result = await plugin._call_deepseek("长回答")

    assert result == "DeepSeek 输出达到最大长度，请在插件配置中调高“最大输出长度”。"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, "DeepSeek 请求格式错误，请检查插件配置。"),
        (401, "DeepSeek API 密钥无效或没有权限。"),
        (402, "DeepSeek 账户余额不足。"),
        (422, "DeepSeek 请求参数无效，请检查模型和工具配置。"),
        (429, "DeepSeek 请求过于频繁，请稍后再试。"),
        (500, "DeepSeek 服务暂时异常，请稍后再试。"),
        (503, "DeepSeek 服务繁忙，请稍后再试。"),
    ],
)
def test_api_status_errors_are_classified(status_code: int, expected: str) -> None:
    """DeepSeek 官方状态码应转换为不泄露原始异常的中文提示。"""
    module = load_plugin_module()

    class FakeStatusError(Exception):
        def __init__(self) -> None:
            super().__init__("SECRET_RAW_ERROR")
            self.status_code = status_code

    error = module.DeepSeekRequestError.from_exception(FakeStatusError())

    assert str(error) == expected
    assert "SECRET_RAW_ERROR" not in str(error)


@pytest.mark.parametrize(
    ("exception_name", "expected"),
    [
        ("APITimeoutError", "连接 DeepSeek 超时，请稍后再试。"),
        ("APIConnectionError", "无法连接 DeepSeek，请检查网络后重试。"),
    ],
)
def test_network_errors_are_classified(exception_name: str, expected: str) -> None:
    """连接失败和超时应转换为清晰中文提示。"""
    module = load_plugin_module()
    error_type = type(exception_name, (Exception,), {})

    error = module.DeepSeekRequestError.from_exception(error_type("SECRET_RAW_ERROR"))

    assert str(error) == expected


async def test_call_deepseek_raises_when_disabled() -> None:
    """插件关闭时 _call_deepseek 应抛出 RuntimeError。"""
    _module, plugin = make_plugin({"plugin": {"enabled": False}})
    with pytest.raises(RuntimeError, match="已在插件配置中关闭"):
        await plugin._call_deepseek("测试")


async def test_call_deepseek_raises_when_no_api_key() -> None:
    """无密钥时 _call_deepseek 应抛出 RuntimeError。"""
    _module, plugin = make_plugin({"auth": {"api_key": "", "api_key_env": ""}})
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="缺少 DeepSeek API 密钥"):
            await plugin._call_deepseek("测试")


async def test_fetch_page_uses_web_search_tool() -> None:
    """fetch_page 应给 DeepSeek 传入 web_search server tool。"""
    _module, plugin = make_plugin(
        {
            "auth": {"api_key": "sk-test"},
            "search": {"web_search_tool": "web_search_20260209", "max_search_uses": 4},
        }
    )

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="页面摘要")) as mock_call:
        result = await plugin.handle_fetch_page(url="https://api-docs.deepseek.com", explanation="核实文档")

    assert result == {"name": "fetch_page", "content": "页面摘要"}
    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]


async def test_search_and_summarize_uses_web_search_tool() -> None:
    """专用搜索工具应通过统一请求管道传入 Web Search server tool。"""
    _module, plugin = make_plugin(
        {
            "auth": {"api_key": "sk-test"},
            "search": {"web_search_tool": "web_search_20260209", "max_search_uses": 3},
        }
    )

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="搜索摘要")) as mock_call:
        result = await plugin.handle_search_and_summarize(query="最新消息")

    assert result == {"name": "search_and_summarize", "content": "搜索摘要"}
    assert mock_call.call_args.kwargs["tools"] == [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}
    ]


@pytest.mark.parametrize(
    "url",
    [
        "example.com",
        "ftp://example.com",
        "javascript:alert(1)",
        "https://example.com bad",
        "https://[invalid",
    ],
)
async def test_fetch_page_rejects_invalid_web_url(url: str) -> None:
    """网页读取只接受有效 HTTP/HTTPS URL，避免无效调用产生费用。"""
    _module, plugin = make_plugin()

    with patch.object(plugin, "_call_deepseek", new=AsyncMock()) as mock_call:
        result = await plugin.handle_fetch_page(url=url)

    assert result["content"] == "请提供有效的 HTTP 或 HTTPS 网页地址。"
    mock_call.assert_not_awaited()


async def test_search_tools_return_clear_message_when_search_disabled() -> None:
    """关闭联网后，两个联网工具不应调用 DeepSeek。"""
    _module, plugin = make_plugin({"search": {"enabled": False}})

    with patch.object(plugin, "_call_deepseek", new=AsyncMock()) as mock_call:
        search_result = await plugin.handle_search_and_summarize(query="最新消息")
        page_result = await plugin.handle_fetch_page(url="https://example.com")

    assert "联网搜索已在插件配置中关闭" in search_result["content"]
    assert "联网搜索已在插件配置中关闭" in page_result["content"]
    mock_call.assert_not_awaited()


async def test_deepseek_proxy_uses_search_policy_and_tools_when_enabled() -> None:
    """通用代理开启搜索后应传入搜索工具和对应策略提示。"""
    _module, plugin = make_plugin({"search": {"enabled": True, "search_policy": "explicit"}})

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="代理回复")) as mock_call:
        await plugin.handle_deepseek_proxy(prompt="分析这个问题")

    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["tools"][0]["name"] == "web_search"
    assert "只有任务明确要求联网" in call_kwargs["system"]


@pytest.mark.parametrize(
    ("policy", "expected_text"),
    [
        ("active", "优先使用联网搜索"),
        ("balanced", "信息可能变化、需要核实"),
        ("explicit", "只有任务明确要求联网"),
    ],
)
async def test_deepseek_proxy_uses_each_search_policy(policy: str, expected_text: str) -> None:
    """通用代理应把三种搜索策略转换为对应中文提示。"""
    _module, plugin = make_plugin({"search": {"enabled": True, "search_policy": policy}})

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="代理回复")) as mock_call:
        await plugin.handle_deepseek_proxy(prompt="分析这个问题")

    assert expected_text in mock_call.call_args.kwargs["system"]


async def test_deepseek_proxy_has_no_search_tool_when_disabled() -> None:
    """通用代理关闭搜索后不应传入搜索工具。"""
    _module, plugin = make_plugin({"search": {"enabled": False}})

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="代理回复")) as mock_call:
        await plugin.handle_deepseek_proxy(prompt="分析这个问题")

    call_kwargs = mock_call.call_args.kwargs
    assert call_kwargs["tools"] is None
    assert "联网搜索策略" not in call_kwargs["system"]


# ================================================================
# 测试命令注册测试
# ================================================================

async def test_ping_command_when_disabled() -> None:
    """测试命令禁用时应返回 False。"""
    _module, plugin = make_plugin({"debug": {"enable_test_commands": False}})
    ok, msg, _ = await plugin.handle_ping(stream_id="test")
    assert ok is False
    assert "测试命令已在插件配置中关闭" in msg


async def test_ping_command_does_not_use_web_search_tool() -> None:
    """连接测试不应携带 Web Search 工具，因此不会注入搜索时间。"""
    _module, plugin = make_plugin()

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="pong")) as mock_call:
        ok, _msg, _ = await plugin.handle_ping(stream_id="test")

    assert ok is True
    assert "tools" not in mock_call.call_args.kwargs


async def test_search_test_command_when_disabled() -> None:
    """测试命令禁用时应返回 False。"""
    _module, plugin = make_plugin({"debug": {"enable_test_commands": False}})
    ok, msg, _ = await plugin.handle_search_test(stream_id="test")
    assert ok is False
    assert "测试命令已在插件配置中关闭" in msg


async def test_search_test_command_uses_web_search_tool() -> None:
    """搜索测试命令应携带 Web Search 工具并经过统一请求管道。"""
    _module, plugin = make_plugin({"search": {"web_search_tool": "web_search_20260209"}})

    with patch.object(plugin, "_call_deepseek", new=AsyncMock(return_value="搜索正常")) as mock_call:
        ok, _msg, _ = await plugin.handle_search_test(
            stream_id="test",
            text="/deepseek_anthropic_search_test DeepSeek 最新消息",
        )

    assert ok is True
    assert mock_call.call_args.kwargs["tools"] == [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}
    ]
