"""DeepSeek Anthropic Provider 插件。

这个插件把 DeepSeek Anthropic API 的能力包装成 MaiBot Tool，
让 Bot 可以按需调用 DeepSeek 的联网搜索、网页读取和通用推理能力。
插件本身不做爬虫、不 parse HTML——只做管道。
"""

from typing import Any, Literal

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

import os


PLUGIN_VERSION = "0.2.0"
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

WEB_SEARCH_TOOL_20260209 = "web_search_20260209"
WEB_SEARCH_TOOL_20250305 = "web_search_20250305"
WEB_SEARCH_TOOL_LABELS = {
    WEB_SEARCH_TOOL_20260209: "新版网页搜索（web_search_20260209）",
    WEB_SEARCH_TOOL_20250305: "旧版网页搜索（web_search_20250305）",
}

CHOICE_LABELS_BY_FIELD = {
    ("model_tool", "model_choice"): MODEL_CHOICE_LABELS,
    ("model_tool", "web_search_tool"): WEB_SEARCH_TOOL_LABELS,
}


# ========== 配置 ==========

class PluginSectionConfig(PluginConfigBase):
    """插件开关。"""

    __ui_label__ = "基础设置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="关闭后，插件所有 Tool 和命令均不可用。",
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
        description="可选。填写后优先使用这里的密钥；留空时读取环境变量。",
        json_schema_extra={"label": "DeepSeek API 密钥", "x-widget": "password"},
    )
    api_key_env: str = Field(
        default="DEEPSEEK_API_KEY",
        description="插件配置里没有密钥时，会从这个环境变量读取。",
        json_schema_extra={"label": "环境变量名", "x-widget": "input"},
    )


class ModelToolConfig(PluginConfigBase):
    """模型与工具设置。"""

    __ui_label__ = "模型与工具"
    __ui_icon__ = "brain-circuit"
    __ui_order__ = 2

    model_choice: Literal[MODEL_PRO, MODEL_FLASH] = Field(
        default=MODEL_PRO,
        description="选择调用 DeepSeek Anthropic 接口时使用的模型。",
        json_schema_extra={"label": "模型", "x-widget": "select"},
    )
    web_search_tool: Literal[WEB_SEARCH_TOOL_20260209, WEB_SEARCH_TOOL_20250305] = Field(
        default=WEB_SEARCH_TOOL_20260209,
        description="DeepSeek 支持的 Anthropic 网页搜索工具版本。",
        json_schema_extra={"label": "搜索工具版本", "x-widget": "select"},
    )
    max_search_uses: int = Field(
        default=5,
        ge=1,
        description="每轮搜索最多允许调用几次。越大越聪明，但更慢、更贵。",
        json_schema_extra={"label": "每轮最多搜索次数", "x-widget": "input"},
    )


class DebugConfig(PluginConfigBase):
    """调试与日志。"""

    __ui_label__ = "调试与日志"
    __ui_icon__ = "bug"
    __ui_order__ = 3

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
    model_tool: ModelToolConfig = Field(default_factory=ModelToolConfig)
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
    return MODEL_ID_BY_CHOICE.get(config.model_tool.model_choice, MODEL_PRO)


def _build_web_search_tools(config: DeepSeekAnthropicProviderConfig, max_uses: int | None = None) -> list[dict[str, Any]]:
    """构造 DeepSeek Anthropic server web search 工具参数。"""

    return [
        {
            "type": config.model_tool.web_search_tool,
            "name": "web_search",
            "max_uses": int(max_uses if max_uses is not None else config.model_tool.max_search_uses),
        }
    ]


def _block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return dict(block)
    result: dict[str, Any] = {}
    for name in ("type", "text", "citations", "content"):
        value = getattr(block, name, None)
        if value is not None:
            result[name] = value
    return result


def _extract_citations_from_block(block: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []

    raw_citations = block.get("citations")
    if isinstance(raw_citations, (list, tuple)) and not isinstance(raw_citations, (str, bytes)):
        for raw_citation in raw_citations:
            citation = _block_to_dict(raw_citation)
            url = str(citation.get("url", "") or "").strip()
            title = str(citation.get("title", "") or citation.get("cited_text", "") or "").strip()
            if url:
                citations.append({"title": title, "url": url})

    raw_content = block.get("content")
    if isinstance(raw_content, (list, tuple)) and not isinstance(raw_content, (str, bytes)):
        for raw_item in raw_content:
            item = _block_to_dict(raw_item)
            url = str(item.get("url", "") or "").strip()
            title = str(item.get("title", "") or "").strip()
            if url:
                citations.append({"title": title, "url": url})

    return citations


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

    # ---- 生命周期 ----

    async def on_load(self) -> None:
        self.ctx.logger.info("DeepSeek Anthropic Provider 已加载（Tool 模式）")

    async def on_unload(self) -> None:
        self.ctx.logger.info("DeepSeek Anthropic Provider 已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置热重载时执行。"""
        del scope, config_data, version

    # ---- 共用后端 ----

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
            raise RuntimeError("DeepSeek Anthropic Provider 已在插件配置中关闭")

        api_key = _resolve_api_key(self.config)
        if not api_key:
            raise RuntimeError("缺少 DeepSeek API 密钥，请配置插件密钥或 DEEPSEEK_API_KEY 环境变量")

        base_url = _resolve_base_url(self.config)
        model = _resolve_model(self.config)

        request_body: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if system:
            request_body["system"] = system
        if tools:
            request_body["tools"] = tools

        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise RuntimeError("缺少 anthropic 依赖，请先安装插件依赖") from exc

        client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        try:
            response = await client.messages.create(**request_body)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()

        # 提取文本和 citations
        text_parts: list[str] = []
        citations: list[dict[str, str]] = []
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

        if self.config.debug.log_search_sources and citations:
            self.ctx.logger.info("DeepSeek Anthropic 搜索来源: %s", citations)
        if self.config.debug.log_raw_summary:
            self.ctx.logger.info(
                "DeepSeek Anthropic 响应摘要: model=%s stop=%s tokens_in=%s tokens_out=%s",
                getattr(response, "model", ""),
                getattr(response, "stop_reason", ""),
                getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0,
                getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0,
            )

        return "\n\n".join(text_parts).strip() or "（DeepSeek 未返回文本内容）"

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

        tools = _build_web_search_tools(self.config)

        reason = f"（调用原因：{explanation}）" if explanation.strip() else ""
        system = "你是通过 MaiBot Tool 调用的 DeepSeek 助手。任务：联网搜索并总结答案。"
        user_prompt = f"{query}\n{reason}".strip()

        try:
            result = await self._call_deepseek(user_prompt=user_prompt, system=system, tools=tools)
        except Exception as exc:
            return {"name": "search_and_summarize", "content": f"搜索失败：{exc}"}

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
            return {"name": "fetch_page", "content": f"读取页面失败：{exc}"}

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
        system = "你是通过 MaiBot Tool 调用的 DeepSeek 助手。任务：通用推理。"
        user_prompt = f"{prompt}{reason}"

        try:
            result = await self._call_deepseek(user_prompt=user_prompt, system=system)
        except Exception as exc:
            return {"name": "deepseek_proxy", "content": f"DeepSeek 处理失败：{exc}"}

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
            await self.ctx.send.text(f"DeepSeek Anthropic 连接失败：{exc}", stream_id)
            return False, str(exc), True
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
            await self.ctx.send.text(f"DeepSeek Anthropic 搜索测试失败：{exc}", stream_id)
            return False, str(exc), True
        await self.ctx.send.text(f"DeepSeek Anthropic 搜索测试完成。\n{result}", stream_id)
        return True, "DeepSeek Anthropic 搜索测试完成", True


def create_plugin() -> DeepSeekAnthropicProviderPlugin:
    """创建插件实例。"""
    return DeepSeekAnthropicProviderPlugin()
