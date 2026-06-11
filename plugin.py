"""DeepSeek Anthropic Provider 插件。

这个插件把 DeepSeek Anthropic API 的能力包装成 MaiBot Tool，
让 Bot 可以按需调用 DeepSeek 的联网搜索、网页读取和通用推理能力。
插件本身不做爬虫、不 parse HTML——只做管道。
"""

from datetime import datetime
from typing import Any, Literal, Mapping
from urllib.parse import urlparse
import copy
import os

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType


PLUGIN_VERSION = "0.2.3"
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"

MODEL_PRO = "deepseek-v4-pro"
MODEL_FLASH = "deepseek-v4-flash"
MODEL_ID_BY_CHOICE = {
    MODEL_PRO: MODEL_PRO,
    MODEL_FLASH: MODEL_FLASH,
}
MODEL_CHOICE_LABELS = {
    MODEL_PRO: "DeepSeek V4 Pro（更聪明，成本更高）",
    MODEL_FLASH: "DeepSeek V4 Flash（更快，更省钱）",
}

THINKING_ENABLED = "enabled"
THINKING_DISABLED = "disabled"
THINKING_CHOICE_LABELS = {
    THINKING_ENABLED: "开启思考",
    THINKING_DISABLED: "关闭思考",
}

EFFORT_HIGH = "high"
EFFORT_MAX = "max"
EFFORT_CHOICE_LABELS = {
    EFFORT_HIGH: "标准思考",
    EFFORT_MAX: "深度思考",
}

WEB_SEARCH_TOOL_20260209 = "web_search_20260209"
WEB_SEARCH_TOOL_20250305 = "web_search_20250305"
WEB_SEARCH_TOOL_LABELS = {
    WEB_SEARCH_TOOL_20260209: "新版网页搜索（web_search_20260209）",
    WEB_SEARCH_TOOL_20250305: "旧版网页搜索（web_search_20250305）",
}

SEARCH_POLICY_ACTIVE = "active"
SEARCH_POLICY_BALANCED = "balanced"
SEARCH_POLICY_EXPLICIT = "explicit"
SEARCH_POLICY_CHOICE_LABELS = {
    SEARCH_POLICY_ACTIVE: "更积极",
    SEARCH_POLICY_BALANCED: "按需搜索",
    SEARCH_POLICY_EXPLICIT: "仅显式请求",
}
SEARCH_POLICY_TEXT = {
    SEARCH_POLICY_ACTIVE: "只要任务可能依赖近期或外部事实，就优先使用联网搜索。",
    SEARCH_POLICY_BALANCED: "仅在信息可能变化、需要核实或任务明确要求时使用联网搜索。",
    SEARCH_POLICY_EXPLICIT: "只有任务明确要求联网、搜索、查询最新信息或读取网页时才使用联网搜索。",
}

CHOICE_LABELS_BY_FIELD = {
    ("model", "model_choice"): MODEL_CHOICE_LABELS,
    ("thinking", "thinking_mode"): THINKING_CHOICE_LABELS,
    ("thinking", "thinking_effort"): EFFORT_CHOICE_LABELS,
    ("search", "web_search_tool"): WEB_SEARCH_TOOL_LABELS,
    ("search", "search_policy"): SEARCH_POLICY_CHOICE_LABELS,
}
LEGACY_CHOICE_VALUE_MAPS = {
    ("model", "model_choice"): {
        **{label: value for value, label in MODEL_CHOICE_LABELS.items()},
        "跟随 MaiBot 模型配置（高级）": MODEL_PRO,
        "follow_model_config": MODEL_PRO,
    },
    ("thinking", "thinking_mode"): {label: value for value, label in THINKING_CHOICE_LABELS.items()},
    ("thinking", "thinking_effort"): {
        **{label: value for value, label in EFFORT_CHOICE_LABELS.items()},
        "标准思考 high": EFFORT_HIGH,
        "深度思考 max": EFFORT_MAX,
    },
    ("search", "search_policy"): {label: value for value, label in SEARCH_POLICY_CHOICE_LABELS.items()},
}

SEARCH_ERROR_MESSAGES = {
    "max_uses_exceeded": "已达到每轮最多搜索次数。",
    "unavailable": "搜索服务暂时不可用。",
    "too_many_requests": "搜索请求过于频繁。",
    "query_too_long": "搜索关键词过长。",
    "request_too_large": "搜索请求内容过大。",
    "invalid_tool_input": "搜索工具参数无效。",
}


class DeepSeekRequestError(RuntimeError):
    """可以安全展示给聊天用户的 DeepSeek 请求错误。"""

    @classmethod
    def from_exception(cls, exc: Exception) -> "DeepSeekRequestError":
        exception_name = type(exc).__name__
        if exception_name == "APITimeoutError":
            return cls("连接 DeepSeek 超时，请稍后再试。")
        if exception_name == "APIConnectionError":
            return cls("无法连接 DeepSeek，请检查网络后重试。")

        status_messages = {
            400: "DeepSeek 请求格式错误，请检查插件配置。",
            401: "DeepSeek API 密钥无效或没有权限。",
            402: "DeepSeek 账户余额不足。",
            422: "DeepSeek 请求参数无效，请检查模型和工具配置。",
            429: "DeepSeek 请求过于频繁，请稍后再试。",
            500: "DeepSeek 服务暂时异常，请稍后再试。",
            503: "DeepSeek 服务繁忙，请稍后再试。",
        }
        status_code = getattr(exc, "status_code", None)
        if status_code in status_messages:
            return cls(status_messages[status_code])
        return cls("DeepSeek 调用失败，请查看插件日志。")


# ========== 配置 ==========

class PluginSectionConfig(PluginConfigBase):
    """插件开关。"""

    __ui_label__ = "基础设置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="关闭后，插件所有 Tool 和命令均不可用。",
        json_schema_extra={
            "label": "启用插件",
            "hint": "关闭后，联网搜索、网页读取、通用代理和测试命令都不可用。",
            "x-widget": "switch",
        },
    )
    config_version: str = Field(
        default=PLUGIN_VERSION,
        description="配置文件版本，通常不需要手动修改。",
        json_schema_extra={
            "label": "配置版本",
            "hint": "由插件自动维护。",
            "x-widget": "input",
            "hidden": True,
        },
    )


class AuthConfig(PluginConfigBase):
    """DeepSeek 密钥和地址。"""

    __ui_label__ = "密钥设置"
    __ui_icon__ = "key-round"
    __ui_order__ = 1

    api_key: str = Field(
        default="",
        description="可选。填写后优先使用这里的密钥；留空时读取环境变量。",
        json_schema_extra={
            "label": "DeepSeek API 密钥",
            "hint": "优先使用这里填写的密钥；留空时读取下方环境变量。",
            "x-widget": "password",
        },
    )
    api_key_env: str = Field(
        default="DEEPSEEK_API_KEY",
        description="插件配置里没有密钥时，会从这个环境变量读取。",
        json_schema_extra={
            "label": "环境变量名",
            "hint": "推荐保留默认的 DEEPSEEK_API_KEY，避免把密钥直接写进配置文件。",
            "x-widget": "input",
        },
    )


class ModelConfig(PluginConfigBase):
    """模型设置。"""

    __ui_label__ = "模型设置"
    __ui_icon__ = "brain-circuit"
    __ui_order__ = 2

    model_choice: Literal[MODEL_PRO, MODEL_FLASH] = Field(
        default=MODEL_FLASH,
        description="选择调用 DeepSeek Anthropic 接口时使用的模型。",
        json_schema_extra={
            "label": "模型",
            "hint": "Flash 更快更省，Pro 更适合复杂推理和高质量总结。",
            "x-widget": "select",
        },
    )
    max_tokens: int = Field(
        default=4096,
        ge=1024,
        le=32768,
        description="单次调用允许 DeepSeek 输出的最大长度。",
        json_schema_extra={
            "label": "最大输出长度",
            "hint": "深度思考或长总结被截断时可以调高；数值越大，潜在费用越高。",
            "x-widget": "input",
        },
    )


class ThinkingConfig(PluginConfigBase):
    """思考设置。"""

    __ui_label__ = "思考设置"
    __ui_icon__ = "brain"
    __ui_order__ = 3

    thinking_mode: Literal[THINKING_ENABLED, THINKING_DISABLED] = Field(
        default=THINKING_ENABLED,
        description="开启后模型会先思考再回答；关闭后回复更快、更省输出。",
        json_schema_extra={
            "label": "思考模式",
            "hint": "开启后更适合复杂任务；关闭后响应更快，且不发送思考深度参数。",
            "x-widget": "select",
        },
    )
    thinking_effort: Literal[EFFORT_HIGH, EFFORT_MAX] = Field(
        default=EFFORT_HIGH,
        description="仅在开启思考时生效。深度思考更深入，也更慢、更贵。",
        json_schema_extra={
            "label": "思考深度",
            "hint": "仅在开启思考时生效；深度思考更慢，通常也会消耗更多输出。",
            "x-widget": "select",
        },
    )


class SearchConfig(PluginConfigBase):
    """联网搜索设置。"""

    __ui_label__ = "联网搜索"
    __ui_icon__ = "search"
    __ui_order__ = 4

    enabled: bool = Field(
        default=True,
        description="控制插件内部的 DeepSeek 是否可以使用网页搜索，不影响 MaiBot 主模型是否调用插件。",
        json_schema_extra={
            "label": "允许联网搜索",
            "hint": "只控制插件内部的 DeepSeek 搜索能力，不控制 MaiBot 主模型是否调用本插件。",
            "x-widget": "switch",
        },
    )
    web_search_tool: Literal[WEB_SEARCH_TOOL_20260209, WEB_SEARCH_TOOL_20250305] = Field(
        default=WEB_SEARCH_TOOL_20260209,
        description="DeepSeek 支持的 Anthropic 网页搜索工具版本。",
        json_schema_extra={
            "label": "搜索工具版本",
            "hint": "默认使用新版工具；不同账号支持情况可能不同，请用搜索测试命令验证。",
            "x-widget": "select",
        },
    )
    max_search_uses: int = Field(
        default=5,
        ge=1,
        description="每轮搜索最多允许调用几次。越大越聪明，但更慢、更贵。",
        json_schema_extra={
            "label": "每轮最多搜索次数",
            "hint": "限制单次 DeepSeek 调用中的搜索次数，避免耗时和费用失控。",
            "x-widget": "input",
        },
    )
    search_policy: Literal[SEARCH_POLICY_ACTIVE, SEARCH_POLICY_BALANCED, SEARCH_POLICY_EXPLICIT] = Field(
        default=SEARCH_POLICY_BALANCED,
        description="控制通用 DeepSeek 代理在什么情况下使用联网搜索。",
        json_schema_extra={
            "label": "搜索积极程度",
            "hint": "只影响通用代理内部是否主动搜索；联网搜索和网页读取工具始终会搜索。",
            "x-widget": "select",
        },
    )


class DebugConfig(PluginConfigBase):
    """调试与日志。"""

    __ui_label__ = "调试与日志"
    __ui_icon__ = "bug"
    __ui_order__ = 5

    log_search_sources: bool = Field(
        default=True,
        description="搜索来源只写入日志，不主动发给聊天用户。",
        json_schema_extra={
            "label": "记录搜索来源",
            "hint": "将搜索结果 URL 写入日志，方便核实答案来源；不会追加到聊天回复。",
            "x-widget": "switch",
        },
    )
    log_raw_summary: bool = Field(
        default=False,
        description="开启后会记录简短原始响应摘要，排查问题时再打开。",
        json_schema_extra={
            "label": "记录原始响应摘要",
            "hint": "仅记录模型、停止原因和 token 数，不记录完整回答。",
            "x-widget": "switch",
            "advanced": True,
        },
    )
    enable_test_commands: bool = Field(
        default=True,
        description="开启后可使用 /deepseek_anthropic_ping 和 /deepseek_anthropic_search_test。",
        json_schema_extra={
            "label": "启用测试命令",
            "hint": "允许在聊天中测试模型连通性和当前搜索工具版本。",
            "x-widget": "switch",
        },
    )


class DeepSeekAnthropicProviderConfig(PluginConfigBase):
    """DeepSeek Anthropic Provider 插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)


# ========== 辅助函数 ==========

def _add_choice_labels(schema: dict[str, Any]) -> dict[str, Any]:
    """在生成的 JSON Schema 中注入中文 choice_labels。"""

    sections = schema.get("sections")
    if not isinstance(sections, dict):
        return schema

    for (section_name, field_name), labels in CHOICE_LABELS_BY_FIELD.items():
        section_schema = sections.get(section_name)
        if not isinstance(section_schema, dict):
            continue
        fields = section_schema.get("fields")
        if not isinstance(fields, dict):
            continue
        field_schema = fields.get(field_name)
        if isinstance(field_schema, dict):
            field_schema["choice_labels"] = dict(labels)

    return schema


def _version_parts(version: str) -> tuple[int, ...] | None:
    """将纯数字点分版本转换为可比较元组。"""

    try:
        return tuple(int(part) for part in version.split("."))
    except (AttributeError, ValueError):
        return None


def _is_future_config_version(config_data: Mapping[str, Any] | None) -> bool:
    """判断配置是否来自高于当前插件的版本。"""

    if not isinstance(config_data, Mapping):
        return False
    plugin_section = config_data.get("plugin")
    if not isinstance(plugin_section, Mapping):
        return False
    config_version = _version_parts(plugin_section.get("config_version", ""))
    plugin_version = _version_parts(PLUGIN_VERSION)
    return config_version is not None and plugin_version is not None and config_version > plugin_version


def _normalize_legacy_config(config_data: Mapping[str, Any] | None) -> tuple[dict[str, Any], bool]:
    """迁移旧分组、旧字段名和旧中文选项值。"""

    normalized = copy.deepcopy(dict(config_data)) if isinstance(config_data, Mapping) else {}
    changed = False

    plugin_section = normalized.setdefault("plugin", {})
    if not isinstance(plugin_section, dict):
        plugin_section = {}
        normalized["plugin"] = plugin_section
        changed = True
    if plugin_section.get("config_version") != PLUGIN_VERSION and not _is_future_config_version(normalized):
        plugin_section["config_version"] = PLUGIN_VERSION
        changed = True

    legacy_model_tool = normalized.pop("model_tool", None)
    if isinstance(legacy_model_tool, dict):
        model_section = normalized.setdefault("model", {})
        search_section = normalized.setdefault("search", {})
        if isinstance(model_section, dict) and "model_choice" in legacy_model_tool:
            model_section["model_choice"] = legacy_model_tool["model_choice"]
        if isinstance(search_section, dict):
            if "web_search_tool" in legacy_model_tool:
                search_section["web_search_tool"] = legacy_model_tool["web_search_tool"]
            if "max_search_uses" in legacy_model_tool:
                search_section["max_search_uses"] = legacy_model_tool["max_search_uses"]
        changed = True

    search_section = normalized.get("search")
    if isinstance(search_section, dict) and "max_uses" in search_section:
        search_section["max_search_uses"] = search_section.pop("max_uses")
        changed = True

    for (section_name, field_name), value_map in LEGACY_CHOICE_VALUE_MAPS.items():
        section = normalized.get(section_name)
        if not isinstance(section, dict):
            continue
        current_value = section.get(field_name)
        if isinstance(current_value, str) and current_value in value_map:
            section[field_name] = value_map[current_value]
            changed = True

    return normalized, changed


def _resolve_api_key(config: DeepSeekAnthropicProviderConfig) -> str:
    """按优先级读取 API Key。"""

    configured_key = str(config.auth.api_key or "").strip()
    if configured_key:
        return configured_key

    env_name = str(config.auth.api_key_env or "").strip()
    if env_name:
        env_key = str(os.getenv(env_name) or "").strip()
        if env_key:
            return env_key

    return ""


def _resolve_base_url(config: DeepSeekAnthropicProviderConfig) -> str:
    del config
    return DEFAULT_BASE_URL


def _resolve_model(config: DeepSeekAnthropicProviderConfig) -> str:
    return MODEL_ID_BY_CHOICE.get(config.model.model_choice, MODEL_FLASH)


def _build_web_search_tools(config: DeepSeekAnthropicProviderConfig, max_uses: int | None = None) -> list[dict[str, Any]]:
    """构造 DeepSeek Anthropic server web search 工具参数。"""

    if not config.search.enabled:
        return []

    return [
        {
            "type": config.search.web_search_tool,
            "name": "web_search",
            "max_uses": int(max_uses if max_uses is not None else config.search.max_search_uses),
        }
    ]


def _has_web_search_tool(tools: list[dict[str, Any]] | None) -> bool:
    """判断请求是否携带 Anthropic Web Search server tool。"""

    if not tools:
        return False
    return any(
        str(tool.get("name", "") or "").strip() == "web_search"
        or str(tool.get("type", "") or "").strip().startswith("web_search_")
        for tool in tools
    )


def _build_search_time_context() -> str:
    """构造供联网搜索使用的服务器本地时间上下文。"""

    local_time = datetime.now().astimezone()
    timezone_name = local_time.tzname() or "本地时区"
    raw_offset = local_time.strftime("%z")
    utc_offset = f"{raw_offset[:3]}:{raw_offset[3:]}" if len(raw_offset) == 5 else raw_offset
    formatted_time = local_time.strftime("%Y年%m月%d日 %H:%M:%S")
    return (
        f"【当前时间】服务器本地时间是 {formatted_time}（{timezone_name}，UTC{utc_offset}）。"
        "处理“今天、最新、近期、今年”等相对时间、生成搜索词和筛选搜索结果时，必须以此时间为准；"
        "请核对搜索结果的发布日期，不要把模型训练数据中的日期当作当前日期。"
    )


def _build_proxy_system_prompt(config: DeepSeekAnthropicProviderConfig) -> str:
    """构造通用代理提示词，并说明插件内部的联网搜索策略。"""

    system = "你是通过 MaiBot Tool 调用的 DeepSeek 助手。任务：通用推理。"
    if config.search.enabled:
        policy = SEARCH_POLICY_TEXT[config.search.search_policy]
        system = f"{system}\n【联网搜索策略】{policy}"
    return system


def _block_to_dict(block: Any) -> dict[str, Any]:
    """将字典、Anthropic SDK 对象或测试对象转换为普通字典。"""

    if isinstance(block, Mapping):
        return dict(block)

    model_dump = getattr(block, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, Mapping):
            return dict(dumped)

    result: dict[str, Any] = {}
    for name in (
        "type",
        "text",
        "citations",
        "content",
        "url",
        "title",
        "cited_text",
        "error_code",
    ):
        value = getattr(block, name, None)
        if value is not None:
            result[name] = value
    return result


def _as_block_list(value: Any) -> list[Any]:
    """把内容字段统一为可遍历的内容块列表。"""

    if value is None or isinstance(value, (str, bytes)):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _deduplicate_citations(citations: list[dict[str, str]]) -> list[dict[str, str]]:
    """按 URL 去重并保留首次出现的标题。"""

    result: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for citation in citations:
        url = citation["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        result.append(citation)
    return result


def _extract_citations_from_block(block: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []

    for raw_citation in _as_block_list(block.get("citations")):
        citation = _block_to_dict(raw_citation)
        url = str(citation.get("url", "") or "").strip()
        title = str(citation.get("title", "") or citation.get("cited_text", "") or "").strip()
        if url:
            citations.append({"title": title, "url": url})

    for raw_item in _as_block_list(block.get("content")):
        item = _block_to_dict(raw_item)
        url = str(item.get("url", "") or "").strip()
        title = str(item.get("title", "") or "").strip()
        if url:
            citations.append({"title": title, "url": url})

    return _deduplicate_citations(citations)


def _extract_search_errors_from_block(block: dict[str, Any]) -> list[str]:
    """提取 Anthropic web_search_tool_result 中的错误码。"""

    errors: list[str] = []
    for raw_item in _as_block_list(block.get("content")):
        item = _block_to_dict(raw_item)
        error_code = str(item.get("error_code", "") or "").strip()
        if error_code and error_code not in errors:
            errors.append(error_code)
    return errors


def _search_error_message(error_code: str) -> str:
    return SEARCH_ERROR_MESSAGES.get(error_code, f"搜索工具返回错误（{error_code}）。")


def _is_valid_web_url(url: str) -> bool:
    """只接受带主机名的 HTTP/HTTPS URL。"""

    normalized_url = url.strip()
    if any(character.isspace() for character in normalized_url):
        return False
    try:
        parsed = urlparse(normalized_url)
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(hostname)


# ========== 插件主体 ==========

class DeepSeekAnthropicProviderPlugin(MaiBotPlugin):
    """将 DeepSeek Anthropic API 的能力包装为 MaiBot Tool。"""

    config_model = DeepSeekAnthropicProviderConfig

    @classmethod
    def build_config_schema(
        cls,
        *,
        plugin_id: str = "",
        plugin_name: str = "",
        plugin_version: str = "",
        plugin_description: str = "",
        plugin_author: str = "",
    ) -> dict[str, Any]:
        schema = super().build_config_schema(
            plugin_id=plugin_id,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            plugin_description=plugin_description,
            plugin_author=plugin_author,
        )
        return _add_choice_labels(schema)

    def normalize_plugin_config(self, config_data: Mapping[str, Any] | None) -> tuple[dict[str, Any], bool]:
        if _is_future_config_version(config_data):
            return copy.deepcopy(dict(config_data)), False

        normalized_input, legacy_changed = _normalize_legacy_config(config_data)
        normalized_config, changed = super().normalize_plugin_config(normalized_input)
        return normalized_config, changed or legacy_changed

    # ---- 生命周期 ----

    async def on_load(self) -> None:
        self.ctx.logger.info("DeepSeek Anthropic Provider 已加载（Tool 模式）")

    async def on_unload(self) -> None:
        self.ctx.logger.info("DeepSeek Anthropic Provider 已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置热重载时执行。"""
        del scope, config_data, version

    # ---- 共用后端 ----

    def _format_tool_error(self, prefix: str, exc: Exception) -> str:
        """将内部异常转换为不会泄露原始响应的用户提示。"""

        if isinstance(exc, DeepSeekRequestError):
            return f"{prefix}：{exc}"
        self.ctx.logger.error("%s：%s", prefix, exc, exc_info=True)
        return f"{prefix}，请查看插件日志。"

    async def _call_deepseek(
        self,
        user_prompt: str,
        *,
        system: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """通过 Anthropic SDK 调用 DeepSeek，返回提取后的文本内容。

        这是所有 Tool 和命令共用的后端管道。
        """

        if not self.config.plugin.enabled:
            raise DeepSeekRequestError("DeepSeek Anthropic Provider 已在插件配置中关闭")

        api_key = _resolve_api_key(self.config)
        if not api_key:
            raise DeepSeekRequestError("缺少 DeepSeek API 密钥，请配置插件密钥或 DEEPSEEK_API_KEY 环境变量")

        base_url = _resolve_base_url(self.config)
        model = _resolve_model(self.config)

        request_body: dict[str, Any] = {
            "model": model,
            "max_tokens": self.config.model.max_tokens,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        effective_system = system
        if _has_web_search_tool(tools):
            search_time_context = _build_search_time_context()
            effective_system = f"{system}\n\n{search_time_context}" if system else search_time_context
        if self.config.thinking.thinking_mode == THINKING_ENABLED:
            request_body["thinking"] = {"type": THINKING_ENABLED}
            request_body["output_config"] = {"effort": self.config.thinking.thinking_effort}
        else:
            request_body["thinking"] = {"type": THINKING_DISABLED}
        if effective_system:
            request_body["system"] = effective_system
        if tools:
            request_body["tools"] = tools

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise DeepSeekRequestError("缺少 anthropic 依赖，请先安装插件依赖") from exc

        client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        try:
            try:
                response = await client.messages.create(**request_body)
            except Exception as exc:
                self.ctx.logger.error("DeepSeek Anthropic 请求失败：%s", exc, exc_info=True)
                raise DeepSeekRequestError.from_exception(exc) from exc
        finally:
            await client.close()

        # 提取最终文本、搜索来源和 server tool 错误。
        text_parts: list[str] = []
        citations: list[dict[str, str]] = []
        search_errors: list[str] = []
        raw_content = getattr(response, "content", [])

        if isinstance(raw_content, (list, tuple)) and not isinstance(raw_content, (str, bytes)):
            for raw_block in raw_content:
                block = _block_to_dict(raw_block)
                block_type = str(block.get("type", "") or "").strip()
                if block_type == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text.strip())
                citations.extend(_extract_citations_from_block(block))
                for error_code in _extract_search_errors_from_block(block):
                    if error_code not in search_errors:
                        search_errors.append(error_code)

        citations = _deduplicate_citations(citations)
        if self.config.debug.log_search_sources and citations:
            self.ctx.logger.info("DeepSeek Anthropic 搜索来源: %s", citations)
        if search_errors:
            self.ctx.logger.warning(
                "DeepSeek Anthropic 搜索工具错误: %s",
                [{"code": code, "message": _search_error_message(code)} for code in search_errors],
            )
        if self.config.debug.log_raw_summary:
            self.ctx.logger.info(
                "DeepSeek Anthropic 响应摘要: model=%s stop=%s tokens_in=%s tokens_out=%s",
                getattr(response, "model", ""),
                getattr(response, "stop_reason", ""),
                getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0,
                getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0,
            )

        final_text = "\n\n".join(text_parts).strip()
        if final_text:
            return final_text
        if search_errors:
            return f"联网搜索失败：{_search_error_message(search_errors[0])}"
        if str(getattr(response, "stop_reason", "") or "") == "max_tokens":
            return "DeepSeek 输出达到最大长度，请在插件配置中调高“最大输出长度”。"
        return "（DeepSeek 未返回文本内容）"

    # ================================================================
    # Tool: search_and_summarize
    # ================================================================

    @Tool(
        "search_and_summarize",
        description="使用 DeepSeek 联网搜索网页并总结结果。适合查最新消息、查资料、核实事实等需要联网的场景。",
        parameters=[
            ToolParameterInfo(name="query", param_type=ToolParamType.STRING, description="搜索查询词", required=True),
            ToolParameterInfo(name="explanation", param_type=ToolParamType.STRING, description="为什么需要搜索", required=False),
        ],
    )
    async def handle_search_and_summarize(self, query: str = "", explanation: str = "", **kwargs: Any):
        """联网搜索并总结。"""
        del kwargs
        if not query.strip():
            return {"name": "search_and_summarize", "content": "请提供搜索查询词。"}
        if not self.config.search.enabled:
            return {"name": "search_and_summarize", "content": "联网搜索已在插件配置中关闭。"}

        tools = _build_web_search_tools(self.config)

        reason = f"（调用原因：{explanation}）" if explanation.strip() else ""
        system = "你是通过 MaiBot Tool 调用的 DeepSeek 助手。任务：联网搜索并总结答案。"
        user_prompt = f"{query}\n{reason}".strip()

        try:
            result = await self._call_deepseek(user_prompt=user_prompt, system=system, tools=tools)
        except Exception as exc:
            return {"name": "search_and_summarize", "content": self._format_tool_error("搜索失败", exc)}

        return {"name": "search_and_summarize", "content": result}

    # ================================================================
    # Tool: fetch_page
    # ================================================================

    @Tool(
        "fetch_page",
        description="读取指定网页 URL 的内容并返回。适合需要查看某个具体网页内容的场景。",
        parameters=[
            ToolParameterInfo(name="url", param_type=ToolParamType.STRING, description="要读取的网页 URL", required=True),
            ToolParameterInfo(name="explanation", param_type=ToolParamType.STRING, description="为什么需要读这个页面", required=False),
        ],
    )
    async def handle_fetch_page(self, url: str = "", explanation: str = "", **kwargs: Any):
        """读取网页内容。"""
        del kwargs
        if not url.strip():
            return {"name": "fetch_page", "content": "请提供要读取的网页 URL。"}
        if not _is_valid_web_url(url):
            return {"name": "fetch_page", "content": "请提供有效的 HTTP 或 HTTPS 网页地址。"}
        if not self.config.search.enabled:
            return {"name": "fetch_page", "content": "联网搜索已在插件配置中关闭，无法读取网页。"}

        reason = f"（读取原因：{explanation}）" if explanation.strip() else ""
        system = "你是通过 MaiBot Tool 调用的 DeepSeek 助手。任务：读取指定网页内容并呈现。"
        user_prompt = f"请读取以下网页的内容并返回：\n{url}\n{reason}".strip()

        try:
            result = await self._call_deepseek(
                user_prompt=user_prompt,
                system=system,
                tools=_build_web_search_tools(self.config),
            )
        except Exception as exc:
            return {"name": "fetch_page", "content": self._format_tool_error("读取页面失败", exc)}

        return {"name": "fetch_page", "content": result}

    # ================================================================
    # Tool: deepseek_proxy
    # ================================================================

    @Tool(
        "deepseek_proxy",
        description="将复杂 prompt 直接交给 DeepSeek 处理。适合需要深度推理、长文分析、或以上工具无法覆盖的场景。",
        parameters=[
            ToolParameterInfo(name="prompt", param_type=ToolParamType.STRING, description="交给 DeepSeek 的完整 prompt", required=True),
            ToolParameterInfo(name="explanation", param_type=ToolParamType.STRING, description="为什么需要交给 DeepSeek", required=False),
        ],
    )
    async def handle_deepseek_proxy(self, prompt: str = "", explanation: str = "", **kwargs: Any):
        """通用代理，把 prompt 直接交给 DeepSeek 处理。"""
        del kwargs
        if not prompt.strip():
            return {"name": "deepseek_proxy", "content": "请提供要处理的 prompt。"}

        reason = f"\n（调用原因：{explanation}）" if explanation.strip() else ""
        system = _build_proxy_system_prompt(self.config)
        user_prompt = f"{prompt}{reason}"
        tools = _build_web_search_tools(self.config) or None

        try:
            result = await self._call_deepseek(user_prompt=user_prompt, system=system, tools=tools)
        except Exception as exc:
            return {"name": "deepseek_proxy", "content": self._format_tool_error("DeepSeek 处理失败", exc)}

        return {"name": "deepseek_proxy", "content": result}

    # ================================================================
    # 测试命令
    # ================================================================

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
            result = await self._call_deepseek(
                user_prompt="请只回复 pong。",
                system="你是 MaiBot 连通性测试助手。",
            )
        except Exception as exc:
            error_message = self._format_tool_error("DeepSeek Anthropic 连接失败", exc)
            await self.ctx.send.text(error_message, stream_id)
            return False, error_message, True
        await self.ctx.send.text(f"DeepSeek Anthropic 连接正常：{result}", stream_id)
        return True, "DeepSeek Anthropic 连接测试完成", True

    @Command(
        "deepseek_anthropic_search_test",
        description="测试 DeepSeek Anthropic 网页搜索工具是否可用",
        pattern=r"^/deepseek_anthropic_search_test\s+(.+)$",
    )
    async def handle_search_test(self, stream_id: str = "", **kwargs: Any):
        if not self.config.debug.enable_test_commands:
            return False, "测试命令已在插件配置中关闭", True
        if not self.config.search.enabled:
            return False, "联网搜索已在插件配置中关闭", True
        text = str(kwargs.get("text") or "").strip()
        query = text.removeprefix("/deepseek_anthropic_search_test").strip() or "DeepSeek 最新消息"

        tools = _build_web_search_tools(self.config, max_uses=2)
        try:
            result = await self._call_deepseek(
                user_prompt=f"请联网搜索并用一句话回答：{query}",
                system="你是 MaiBot 搜索测试助手。",
                tools=tools,
            )
        except Exception as exc:
            error_message = self._format_tool_error("DeepSeek Anthropic 搜索测试失败", exc)
            await self.ctx.send.text(error_message, stream_id)
            return False, error_message, True
        await self.ctx.send.text(f"DeepSeek Anthropic 搜索测试完成。\n{result}", stream_id)
        return True, "DeepSeek Anthropic 搜索测试完成", True


def create_plugin() -> DeepSeekAnthropicProviderPlugin:
    """创建插件实例。"""
    return DeepSeekAnthropicProviderPlugin()
