from pathlib import Path
from types import SimpleNamespace
from typing import Any

import importlib.util
import json


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PLUGIN_PATH = PLUGIN_DIR / "plugin.py"
MANIFEST_PATH = PLUGIN_DIR / "_manifest.json"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("deepseek_anthropic_provider_plugin", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_plugin(config_overrides: dict[str, Any] | None = None):
    module = load_plugin_module()
    plugin = module.create_plugin()
    config = plugin.get_default_config()
    if config_overrides:
        for section, values in config_overrides.items():
            config.setdefault(section, {}).update(values)
    plugin.set_plugin_config(config)
    plugin._set_context(
        SimpleNamespace(
            logger=SimpleNamespace(
                debug=lambda *args, **kwargs: None,
                info=lambda *args, **kwargs: None,
                warning=lambda *args, **kwargs: None,
                error=lambda *args, **kwargs: None,
            )
        )
    )
    return module, plugin


def test_manifest_and_code_register_same_llm_provider() -> None:
    module, plugin = make_plugin()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    manifest_client_types = [item["client_type"] for item in manifest["llm_providers"]]
    code_client_types = [item["client_type"] for item in plugin.get_llm_providers()]

    assert manifest["id"] == "LowValueTarget.deepseek-anthropic-provider"
    assert manifest_client_types == ["deepseek.anthropic"]
    assert code_client_types == manifest_client_types
    assert module.CLIENT_TYPE == "deepseek.anthropic"


def test_config_schema_uses_plain_chinese_selects() -> None:
    module = load_plugin_module()
    schema = module.DeepSeekAnthropicProviderPlugin.build_config_schema(
        plugin_id="LowValueTarget.deepseek-anthropic-provider",
        plugin_name="DeepSeek Anthropic Provider",
        plugin_version="0.1.0",
        plugin_description="测试",
        plugin_author="LowValueTarget",
    )

    sections = schema["sections"]
    assert sections["model"]["title"] == "模型设置"
    assert sections["thinking"]["title"] == "思考设置"
    assert sections["search"]["title"] == "联网搜索"

    model_field = sections["model"]["fields"]["model_choice"]
    thinking_field = sections["thinking"]["fields"]["thinking_mode"]
    effort_field = sections["thinking"]["fields"]["thinking_effort"]
    tool_field = sections["search"]["fields"]["web_search_tool"]

    assert model_field["ui_type"] == "select"
    assert thinking_field["ui_type"] == "select"
    assert effort_field["ui_type"] == "select"
    assert tool_field["ui_type"] == "select"
    assert model_field["choices"] == [
        "DeepSeek V4 Pro（更聪明，成本更高）",
        "DeepSeek V4 Flash（更快，更省钱）",
        "跟随 MaiBot 模型配置（高级）",
    ]
    assert thinking_field["choices"] == ["开启思考", "关闭思考"]
    assert effort_field["choices"] == ["标准思考 high", "深度思考 max"]


def test_build_request_preserves_system_and_adds_thinking_and_search() -> None:
    module, plugin = make_plugin(
        {
            "model": {"model_choice": "DeepSeek V4 Flash（更快，更省钱）"},
            "thinking": {"thinking_mode": "开启思考", "thinking_effort": "深度思考 max"},
            "search": {"enabled": True, "web_search_tool": "web_search_20260209", "max_uses": 4},
        }
    )
    request = {
        "api_provider": {"api_key": "provider-key", "base_url": "https://api.deepseek.com/anthropic"},
        "max_tokens": 4096,
        "model_info": {
            "model_identifier": "deepseek-v4-pro",
            "name": "replyer",
            "extra_params": {"temperature": 0.8},
        },
        "message_list": [
            {"role": "system", "parts": [{"type": "text", "text": "你是麦麦，要保持原有人格。"}]},
            {"role": "user", "parts": [{"type": "text", "text": "今天有什么新消息？"}]},
        ],
        "temperature": 0.9,
        "tool_options": [
            {
                "type": "function",
                "function": {
                    "name": "reply",
                    "description": "发送回复",
                    "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
                },
            }
        ],
    }

    provider_request = module.build_anthropic_request(plugin.config, request)

    assert provider_request["model"] == "deepseek-v4-flash"
    assert "你是麦麦，要保持原有人格。" in provider_request["system"]
    assert "更积极" in provider_request["system"]
    assert provider_request["messages"] == [{"role": "user", "content": "今天有什么新消息？"}]
    assert provider_request["thinking"] == {"type": "enabled"}
    assert provider_request["output_config"] == {"effort": "max"}
    assert "temperature" not in provider_request
    assert provider_request["tools"][0]["name"] == "reply"
    assert provider_request["tools"][1] == {"type": "web_search_20260209", "name": "web_search", "max_uses": 4}


def test_non_text_message_without_description_fails_loudly() -> None:
    module, plugin = make_plugin()
    request = {
        "api_provider": {"api_key": "provider-key", "base_url": "https://api.deepseek.com/anthropic"},
        "max_tokens": 4096,
        "model_info": {"model_identifier": "deepseek-v4-pro", "name": "replyer", "extra_params": {}},
        "message_list": [
            {"role": "user", "parts": [{"type": "image", "image_base64": "abc", "image_format": "png"}]},
        ],
    }

    try:
        module.build_anthropic_request(plugin.config, request)
    except ValueError as exc:
        assert "不支持直接发送图片或文档" in str(exc)
    else:
        raise AssertionError("图片内容没有文本描述时必须明确失败")


def test_parse_anthropic_response_extracts_text_thinking_tools_and_raw_data() -> None:
    module = load_plugin_module()
    response = SimpleNamespace(
        id="msg_1",
        model="deepseek-v4-pro",
        content=[
            SimpleNamespace(type="thinking", thinking="需要查一下最新信息。"),
            SimpleNamespace(
                type="server_tool_use",
                id="srv_1",
                name="web_search",
                input={"query": "DeepSeek V4"},
            ),
            SimpleNamespace(
                type="web_search_tool_result",
                tool_use_id="srv_1",
                content=[{"title": "DeepSeek 文档", "url": "https://api-docs.deepseek.com"}],
            ),
            SimpleNamespace(type="text", text="这是整理后的回复。"),
            SimpleNamespace(
                type="tool_use",
                id="tool_1",
                name="reply",
                input={"text": "你好"},
            ),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20, cache_creation_input_tokens=3, cache_read_input_tokens=4),
    )

    parsed = module.parse_anthropic_response(response)

    assert parsed["content"] == "这是整理后的回复。"
    assert parsed["reasoning_content"] == "需要查一下最新信息。"
    assert parsed["tool_calls"] == [
        {"id": "tool_1", "function": {"name": "reply", "arguments": {"text": "你好"}}}
    ]
    assert parsed["usage"]["prompt_tokens"] == 10
    assert parsed["usage"]["completion_tokens"] == 20
    assert parsed["usage"]["prompt_cache_hit_tokens"] == 4
    assert parsed["raw_data"]["server_tools"][0]["type"] == "server_tool_use"
    assert parsed["raw_data"]["citations"][0]["url"] == "https://api-docs.deepseek.com"
