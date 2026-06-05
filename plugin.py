"""DeepSeek Anthropic Provider 插件。

这个插件只负责把 MaiBot 已经构造好的 LLM 请求转换为 DeepSeek
Anthropic 兼容接口请求，不重新拼接人格、记忆或聊天上下文。
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from maibot_sdk import Command, Field, LLMProvider, MaiBotPlugin, PluginConfigBase

import os


PLUGIN_VERSION = "0.1.0"
CLIENT_TYPE = "deepseek.anthropic"
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"

MODEL_PRO = "DeepSeek V4 Pro（更聪明，成本更高）"
MODEL_FLASH = "DeepSeek V4 Flash（更快，更省钱）"
MODEL_FOLLOW = "跟随 MaiBot 模型配置（高级）"
MODEL_ID_BY_CHOICE = {
    MODEL_PRO: "deepseek-v4-pro",
    MODEL_FLASH: "deepseek-v4-flash",
}

THINKING_ENABLED = "开启思考"
THINKING_DISABLED = "关闭思考"
EFFORT_HIGH = "标准思考 high"
EFFORT_MAX = "深度思考 max"
EFFORT_BY_CHOICE = {
    EFFORT_HIGH: "high",
    EFFORT_MAX: "max",
}

SEARCH_POLICY_ACTIVE = "更积极"
SEARCH_POLICY_BALANCED = "按需搜索"
SEARCH_POLICY_EXPLICIT = "仅显式请求"
SEARCH_POLICY_TEXT = {
    SEARCH_POLICY_ACTIVE: "默认更积极：只要问题可能依赖近期或外部事实，就优先联网搜索。",
    SEARCH_POLICY_BALANCED: "默认按需搜索：近期信息、变化较快的事实或用户明确要求时联网搜索。",
    SEARCH_POLICY_EXPLICIT: "默认克制搜索：只有用户明确要求联网、查询、最新信息时才搜索。",
}


class PluginSectionConfig(PluginConfigBase):
    """插件开关。"""

    __ui_label__ = "基础设置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="关闭后，这个 Provider 不会处理任何模型请求。",
        json_schema_extra={"label": "启用插件", "x-widget": "switch"},
    )
    config_version: str = Field(
        default=PLUGIN_VERSION,
        description="配置文件版本，通常不需要手动修改。",
        json_schema_extra={"label": "配置版本", "x-widget": "input", "advanced": True},
    )


class AuthConfig(PluginConfigBase):
    """DeepSeek 密钥和地址。"""

    __ui_label__ = "密钥设置"
    __ui_icon__ = "key-round"
    __ui_order__ = 1

    api_key: str = Field(
        default="",
        description="可选。填写后优先使用这里的密钥；留空时读取环境变量，再读取 MaiBot 模型供应商密钥。",
        json_schema_extra={"label": "DeepSeek API 密钥", "x-widget": "password"},
    )
    api_key_env: str = Field(
        default="DEEPSEEK_API_KEY",
        description="插件配置里没有密钥时，会从这个环境变量读取。",
        json_schema_extra={"label": "环境变量名", "x-widget": "input"},
    )
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="DeepSeek Anthropic 兼容接口地址。一般保持默认即可。",
        json_schema_extra={"label": "接口地址", "x-widget": "input"},
    )
    key_source_help: str = Field(
        default="优先级：插件密钥 > 环境变量 DEEPSEEK_API_KEY > MaiBot 模型供应商密钥。",
        description="展示给 WebUI 的说明文字，不参与运行逻辑。",
        json_schema_extra={"label": "密钥读取说明", "x-widget": "textarea", "rows": 2},
    )


class ModelConfig(PluginConfigBase):
    """选择 DeepSeek V4 模型。"""

    __ui_label__ = "模型设置"
    __ui_icon__ = "brain-circuit"
    __ui_order__ = 2

    model_choice: Literal[MODEL_PRO, MODEL_FLASH, MODEL_FOLLOW] = Field(
        default=MODEL_PRO,
        description="选择插件实际请求 DeepSeek 时使用的模型。",
        json_schema_extra={"label": "模型", "x-widget": "select"},
    )


class ThinkingConfig(PluginConfigBase):
    """思考模式。"""

    __ui_label__ = "思考设置"
    __ui_icon__ = "brain"
    __ui_order__ = 3

    thinking_mode: Literal[THINKING_ENABLED, THINKING_DISABLED] = Field(
        default=THINKING_ENABLED,
        description="开启后模型会先思考再回答；关闭后回复更快、更省输出。",
        json_schema_extra={"label": "思考模式", "x-widget": "select"},
    )
    thinking_effort: Literal[EFFORT_HIGH, EFFORT_MAX] = Field(
        default=EFFORT_HIGH,
        description="仅在开启思考时生效。max 更深入，也更慢、更贵。",
        json_schema_extra={"label": "思考深度", "x-widget": "select"},
    )


class SearchConfig(PluginConfigBase):
    """DeepSeek Anthropic 联网搜索。"""

    __ui_label__ = "联网搜索"
    __ui_icon__ = "search"
    __ui_order__ = 4

    enabled: bool = Field(
        default=True,
        description="开启后，模型可以按需要调用 DeepSeek Anthropic 的网页搜索工具。",
        json_schema_extra={"label": "允许模型联网搜索", "x-widget": "switch"},
    )
    web_search_tool: Literal["web_search_20260209", "web_search_20250305"] = Field(
        default="web_search_20260209",
        description="DeepSeek 支持的 Anthropic 网页搜索工具版本。",
        json_schema_extra={"label": "搜索工具版本", "x-widget": "select"},
    )
    max_uses: int = Field(
        default=5,
        ge=1,
        description="每轮模型请求最多允许搜索几次。越大越聪明，但更慢、更贵。",
        json_schema_extra={"label": "每轮最多搜索次数", "x-widget": "input"},
    )
    search_policy: Literal[SEARCH_POLICY_ACTIVE, SEARCH_POLICY_BALANCED, SEARCH_POLICY_EXPLICIT] = Field(
        default=SEARCH_POLICY_ACTIVE,
        description="控制系统提示里鼓励模型搜索的积极程度。",
        json_schema_extra={"label": "搜索积极程度", "x-widget": "select"},
    )


class DebugConfig(PluginConfigBase):
    """调试与日志。"""

    __ui_label__ = "调试与日志"
    __ui_icon__ = "bug"
    __ui_order__ = 5

    log_search_sources: bool = Field(
        default=True,
        description="搜索来源只写入日志和 raw_data，不主动发给聊天用户。",
        json_schema_extra={"label": "记录搜索来源", "x-widget": "switch"},
    )
    log_raw_summary: bool = Field(
        default=False,
        description="开启后会记录简短原始响应摘要，排查问题时再打开。",
        json_schema_extra={"label": "记录原始响应摘要", "x-widget": "switch", "advanced": True},
    )
    enable_test_commands: bool = Field(
        default=True,
        description="开启后可使用 /deepseek_anthropic_ping 和 /deepseek_anthropic_search_test。",
        json_schema_extra={"label": "启用测试命令", "x-widget": "switch"},
    )


class DeepSeekAnthropicProviderConfig(PluginConfigBase):
    """DeepSeek Anthropic Provider 插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="python"))
    return {}


def _get_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _extract_text_from_part(part: Mapping[str, Any]) -> str:
    part_type = str(part.get("type") or "").strip().lower()
    if part_type == "text":
        text = part.get("text")
        if isinstance(text, str):
            return text
        content = part.get("content")
        return content if isinstance(content, str) else ""

    if part_type in {"image", "document", "file", "emoji", "voice"}:
        for key in ("description", "caption", "alt_text", "data"):
            description = part.get(key)
            if isinstance(description, str) and description.strip():
                return f"[{part_type} 内容描述] {description.strip()}"
        raise ValueError("DeepSeek Anthropic 兼容接口不支持直接发送图片或文档，请先提供文本描述。")

    text = part.get("text") or part.get("content")
    if isinstance(text, str):
        return text
    raise ValueError(f"不支持的消息片段类型: {part_type or '<empty>'}")


def _message_text(message: Mapping[str, Any]) -> str:
    parts = message.get("parts")
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes, bytearray)):
        content = message.get("content")
        return content if isinstance(content, str) else ""
    return "".join(_extract_text_from_part(part) for part in parts if isinstance(part, Mapping)).strip()


def _normalize_tool_call(raw_tool_call: Mapping[str, Any]) -> dict[str, Any] | None:
    function_info = raw_tool_call.get("function")
    if isinstance(function_info, Mapping):
        name = str(function_info.get("name") or "").strip()
        arguments = function_info.get("arguments")
    else:
        name = str(raw_tool_call.get("name") or raw_tool_call.get("func_name") or "").strip()
        arguments = raw_tool_call.get("arguments") or raw_tool_call.get("args")

    call_id = str(raw_tool_call.get("id") or raw_tool_call.get("call_id") or "").strip()
    if not name or not call_id:
        return None
    return {
        "type": "tool_use",
        "id": call_id,
        "name": name,
        "input": dict(arguments) if isinstance(arguments, Mapping) else {},
    }


def _convert_message(message: Mapping[str, Any]) -> dict[str, Any] | None:
    role = str(message.get("role") or "").strip().lower()
    if role == "system":
        return None
    if role == "tool":
        tool_result = {
            "type": "tool_result",
            "tool_use_id": str(message.get("tool_call_id") or "").strip(),
            "content": _message_text(message),
        }
        if not tool_result["tool_use_id"]:
            tool_result.pop("tool_use_id")
        return {"role": "user", "content": [tool_result]}

    text = _message_text(message)
    if role == "assistant":
        content_blocks: list[dict[str, Any]] = []
        if text:
            content_blocks.append({"type": "text", "text": text})
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, Sequence) and not isinstance(raw_tool_calls, (str, bytes, bytearray)):
            for raw_tool_call in raw_tool_calls:
                if isinstance(raw_tool_call, Mapping):
                    tool_call = _normalize_tool_call(raw_tool_call)
                    if tool_call is not None:
                        content_blocks.append(tool_call)
        return {"role": "assistant", "content": content_blocks or text}

    return {"role": "user", "content": text}


def _convert_tool_option(raw_tool: Mapping[str, Any]) -> dict[str, Any] | None:
    function_info = raw_tool.get("function")
    if not isinstance(function_info, Mapping):
        return None
    name = str(function_info.get("name") or "").strip()
    if not name:
        return None
    parameters = function_info.get("parameters")
    return {
        "name": name,
        "description": str(function_info.get("description") or "").strip(),
        "input_schema": dict(parameters) if isinstance(parameters, Mapping) else {"type": "object", "properties": {}},
    }


def _build_system_prompt(config: DeepSeekAnthropicProviderConfig, messages: Sequence[Mapping[str, Any]]) -> str:
    system_parts = [_message_text(message) for message in messages if str(message.get("role") or "").lower() == "system"]
    if config.search.enabled:
        system_parts.append(f"【联网搜索策略】{SEARCH_POLICY_TEXT[config.search.search_policy]}")
    return "\n\n".join(part for part in system_parts if part.strip())


def _resolve_model(config: DeepSeekAnthropicProviderConfig, request: Mapping[str, Any]) -> str:
    if config.model.model_choice in MODEL_ID_BY_CHOICE:
        return MODEL_ID_BY_CHOICE[config.model.model_choice]

    model_info = _as_dict(request.get("model_info"))
    configured_model = str(model_info.get("model_identifier") or "").strip()
    return configured_model or MODEL_ID_BY_CHOICE[MODEL_PRO]


def _resolve_effort(config: DeepSeekAnthropicProviderConfig) -> str:
    return EFFORT_BY_CHOICE.get(config.thinking.thinking_effort, "high")


def build_anthropic_request(config: DeepSeekAnthropicProviderConfig, request: Mapping[str, Any]) -> dict[str, Any]:
    """把 MaiBot LLM 请求快照转换为 DeepSeek Anthropic 请求。"""

    raw_messages = request.get("message_list")
    messages = [message for message in raw_messages if isinstance(message, Mapping)] if isinstance(raw_messages, list) else []

    provider_request: dict[str, Any] = {
        "model": _resolve_model(config, request),
        "max_tokens": int(request.get("max_tokens") or 4096),
        "messages": [
            converted
            for message in messages
            if (converted := _convert_message(message)) is not None
        ],
    }

    system_prompt = _build_system_prompt(config, messages)
    if system_prompt:
        provider_request["system"] = system_prompt

    raw_tools = request.get("tool_options")
    tools: list[dict[str, Any]] = []
    if isinstance(raw_tools, Sequence) and not isinstance(raw_tools, (str, bytes, bytearray)):
        for raw_tool in raw_tools:
            if isinstance(raw_tool, Mapping):
                tool = _convert_tool_option(raw_tool)
                if tool is not None:
                    tools.append(tool)
    if config.search.enabled:
        tools.append(
            {
                "type": config.search.web_search_tool,
                "name": "web_search",
                "max_uses": int(config.search.max_uses),
            }
        )
    if tools:
        provider_request["tools"] = tools

    if config.thinking.thinking_mode == THINKING_ENABLED:
        provider_request["thinking"] = {"type": "enabled"}
        provider_request["output_config"] = {"effort": _resolve_effort(config)}
    else:
        provider_request["thinking"] = {"type": "disabled"}
        temperature = request.get("temperature")
        if temperature is not None:
            provider_request["temperature"] = temperature

    extra_params = request.get("extra_params")
    if isinstance(extra_params, Mapping):
        for key, value in extra_params.items():
            if key in {"model", "messages", "system", "tools", "thinking", "output_config"}:
                continue
            if config.thinking.thinking_mode == THINKING_ENABLED and key in {
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
            }:
                continue
            provider_request[key] = value

    return provider_request


def resolve_api_key(config: DeepSeekAnthropicProviderConfig, request: Mapping[str, Any]) -> str:
    configured_key = str(config.auth.api_key or "").strip()
    if configured_key:
        return configured_key

    env_name = str(config.auth.api_key_env or "").strip()
    if env_name:
        env_key = str(os.getenv(env_name) or "").strip()
        if env_key:
            return env_key

    api_provider = _as_dict(request.get("api_provider"))
    return str(api_provider.get("api_key") or "").strip()


def resolve_base_url(config: DeepSeekAnthropicProviderConfig, request: Mapping[str, Any]) -> str:
    configured_url = str(config.auth.base_url or "").strip()
    if configured_url:
        return configured_url.rstrip("/")

    api_provider = _as_dict(request.get("api_provider"))
    return str(api_provider.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")


def _block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, Mapping):
        return {str(key): value for key, value in block.items()}
    result: dict[str, Any] = {}
    for name in ("type", "id", "name", "input", "text", "thinking", "tool_use_id", "content", "citations"):
        value = getattr(block, name, None)
        if value is not None:
            result[name] = value
    return result


def _extract_citations(block: Mapping[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    raw_citations = block.get("citations")
    if isinstance(raw_citations, Sequence) and not isinstance(raw_citations, (str, bytes, bytearray)):
        for raw_citation in raw_citations:
            citation = _as_dict(raw_citation)
            url = str(citation.get("url") or "").strip()
            title = str(citation.get("title") or citation.get("cited_text") or "").strip()
            if url:
                citations.append({"title": title, "url": url})

    raw_content = block.get("content")
    if isinstance(raw_content, Sequence) and not isinstance(raw_content, (str, bytes, bytearray)):
        for raw_item in raw_content:
            item = _as_dict(raw_item)
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if url:
                citations.append({"title": title, "url": url})
    return citations


def _usage_to_dict(usage: Any) -> dict[str, int]:
    prompt_tokens = int(_get_value(usage, "input_tokens", 0) or 0)
    completion_tokens = int(_get_value(usage, "output_tokens", 0) or 0)
    cache_hit = int(_get_value(usage, "cache_read_input_tokens", 0) or 0)
    cache_miss = int(_get_value(usage, "cache_creation_input_tokens", 0) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_cache_hit_tokens": cache_hit,
        "prompt_cache_miss_tokens": cache_miss,
    }


def parse_anthropic_response(response: Any) -> dict[str, Any]:
    """把 Anthropic SDK 响应转换为 MaiBot PluginLLMClient 可恢复的字典。"""

    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    server_tools: list[dict[str, Any]] = []
    citations: list[dict[str, str]] = []

    raw_content = _get_value(response, "content", [])
    if isinstance(raw_content, Sequence) and not isinstance(raw_content, (str, bytes, bytearray)):
        for raw_block in raw_content:
            block = _block_to_dict(raw_block)
            block_type = str(block.get("type") or "").strip()
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
                citations.extend(_extract_citations(block))
                continue
            if block_type in {"thinking", "redacted_thinking"}:
                thinking = block.get("thinking") or block.get("text")
                if isinstance(thinking, str):
                    thinking_parts.append(thinking)
                continue
            if block_type == "tool_use":
                name = str(block.get("name") or "").strip()
                call_id = str(block.get("id") or "").strip()
                if name and call_id:
                    input_payload = _as_dict(block.get("input"))
                    tool_calls.append(
                        {
                            "id": call_id,
                            "function": {
                                "name": name,
                                "arguments": input_payload,
                            },
                        }
                    )
                continue
            if block_type in {"server_tool_use", "web_search_tool_result"}:
                server_tools.append(block)
                citations.extend(_extract_citations(block))

    return {
        "content": "\n".join(part for part in text_parts if part).strip(),
        "reasoning_content": "\n".join(part for part in thinking_parts if part).strip(),
        "tool_calls": tool_calls,
        "usage": _usage_to_dict(_get_value(response, "usage")),
        "raw_data": {
            "id": _get_value(response, "id", ""),
            "model": _get_value(response, "model", ""),
            "stop_reason": _get_value(response, "stop_reason", ""),
            "server_tools": server_tools,
            "citations": citations,
        },
    }


class DeepSeekAnthropicProviderPlugin(MaiBotPlugin):
    """通过 Anthropic SDK 调用 DeepSeek 的 LLM Provider。"""

    config_model = DeepSeekAnthropicProviderConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("DeepSeek Anthropic Provider 已加载，client_type=%s", CLIENT_TYPE)

    async def on_unload(self) -> None:
        self.ctx.logger.info("DeepSeek Anthropic Provider 已卸载")

    @LLMProvider(
        CLIENT_TYPE,
        name="DeepSeek Anthropic Provider",
        description="通过 Anthropic SDK 调用 DeepSeek V4，并支持 DeepSeek 的 Anthropic 联网搜索工具。",
        version=PLUGIN_VERSION,
    )
    async def invoke_deepseek_anthropic(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        if not self.config.plugin.enabled:
            raise RuntimeError("DeepSeek Anthropic Provider 已在插件配置中关闭")
        if operation != "response":
            raise NotImplementedError("当前插件只实现文本响应，不支持 embedding 或音频转写")

        api_key = resolve_api_key(self.config, request)
        if not api_key:
            raise RuntimeError("缺少 DeepSeek API 密钥，请配置插件密钥或 DEEPSEEK_API_KEY 环境变量")

        provider_request = build_anthropic_request(self.config, request)
        base_url = resolve_base_url(self.config, request)

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError("缺少 anthropic 依赖，请先安装插件依赖") from exc

        client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        try:
            response = await client.messages.create(**provider_request)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()

        parsed = parse_anthropic_response(response)
        if self.config.debug.log_search_sources and parsed["raw_data"].get("citations"):
            self.ctx.logger.info("DeepSeek Anthropic 搜索来源: %s", parsed["raw_data"]["citations"])
        if self.config.debug.log_raw_summary:
            self.ctx.logger.info("DeepSeek Anthropic 响应摘要: %s", parsed["raw_data"])
        return parsed

    @Command(
        "deepseek_anthropic_ping",
        description="测试 DeepSeek Anthropic Provider 是否能正常调用模型",
        pattern=r"^/deepseek_anthropic_ping$",
    )
    async def handle_ping(self, stream_id: str = "", **kwargs: Any):
        del kwargs
        if not self.config.debug.enable_test_commands:
            return False, "测试命令已在插件配置中关闭", True
        try:
            result = await self._run_probe("请只回复 pong。", enable_search=False)
        except Exception as exc:
            await self.ctx.send.text(f"DeepSeek Anthropic 连接失败：{exc}", stream_id)
            return False, str(exc), True
        await self.ctx.send.text(f"DeepSeek Anthropic 连接正常：{result.get('content') or '已收到响应'}", stream_id)
        return True, "DeepSeek Anthropic 连接测试完成", True

    @Command(
        "deepseek_anthropic_search_test",
        description="测试 DeepSeek Anthropic 网页搜索工具是否可用",
        pattern=r"^/deepseek_anthropic_search_test\s+(.+)$",
    )
    async def handle_search_test(self, stream_id: str = "", **kwargs: Any):
        if not self.config.debug.enable_test_commands:
            return False, "测试命令已在插件配置中关闭", True
        text = str(kwargs.get("text") or "").strip()
        query = text.removeprefix("/deepseek_anthropic_search_test").strip() or "DeepSeek 最新消息"
        try:
            result = await self._run_probe(f"请联网搜索并用一句话回答：{query}", enable_search=True)
        except Exception as exc:
            await self.ctx.send.text(f"DeepSeek Anthropic 搜索测试失败：{exc}", stream_id)
            return False, str(exc), True
        server_tools = result.get("raw_data", {}).get("server_tools", [])
        await self.ctx.send.text(
            f"DeepSeek Anthropic 搜索测试完成，server tool 记录 {len(server_tools)} 条。\n{result.get('content', '')}",
            stream_id,
        )
        return True, "DeepSeek Anthropic 搜索测试完成", True

    async def _run_probe(self, prompt: str, *, enable_search: bool) -> dict[str, Any]:
        original_search_enabled = self.config.search.enabled
        self.config.search.enabled = enable_search
        try:
            return await self.invoke_deepseek_anthropic("response", self._build_probe_request(prompt))
        finally:
            self.config.search.enabled = original_search_enabled

    def _build_probe_request(self, prompt: str) -> dict[str, Any]:
        return {
            "api_provider": {"api_key": resolve_api_key(self.config, {}), "base_url": self.config.auth.base_url},
            "max_tokens": 512,
            "model_info": {"model_identifier": MODEL_ID_BY_CHOICE[MODEL_PRO], "name": "probe", "extra_params": {}},
            "message_list": [
                {"role": "system", "parts": [{"type": "text", "text": "你是 MaiBot 的连通性测试助手。"}]},
                {"role": "user", "parts": [{"type": "text", "text": prompt}]},
            ],
        }


def create_plugin() -> DeepSeekAnthropicProviderPlugin:
    """创建插件实例。"""

    return DeepSeekAnthropicProviderPlugin()
