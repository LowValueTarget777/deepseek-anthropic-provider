"""DeepSeek Anthropic Provider 插件测试（v0.2.1 Tool 模式）。"""

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
    assert manifest["version"] == "0.2.1"
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

    assert f'version = "{manifest["version"]}"' in pyproject_text


# ================================================================
# Config Schema 测试
# ================================================================

def test_config_schema_uses_select_labels() -> None:
    """WebUI 配置 schema 应包含中文 label 的 select 选项。"""
    module = load_plugin_module()
    schema = module.DeepSeekAnthropicProviderPlugin.build_config_schema(
        plugin_id="LowValueTarget.deepseek-anthropic-provider",
        plugin_name="DeepSeek Anthropic Provider",
        plugin_version="0.2.1",
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
    assert normalized["plugin"]["config_version"] == "0.2.1"
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


# ================================================================
# _call_deepseek 请求拼装测试
# ================================================================

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
    assert call_kwargs["system"] == "你是助手"
    assert call_kwargs["max_tokens"] == 4096
    assert call_kwargs["messages"] == [{"role": "user", "content": "测试"}]
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0]["name"] == "web_search"
    assert call_kwargs["thinking"] == {"type": "enabled"}
    assert call_kwargs["output_config"] == {"effort": "high"}


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


async def test_search_test_command_when_disabled() -> None:
    """测试命令禁用时应返回 False。"""
    _module, plugin = make_plugin({"debug": {"enable_test_commands": False}})
    ok, msg, _ = await plugin.handle_search_test(stream_id="test")
    assert ok is False
    assert "测试命令已在插件配置中关闭" in msg
