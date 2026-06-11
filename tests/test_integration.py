"""显式启用后调用真实 DeepSeek API 的集成测试。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import importlib.util
import os
import pytest


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "plugin.py"
RUN_INTEGRATION = os.getenv("RUN_DEEPSEEK_INTEGRATION") == "1" and bool(os.getenv("DEEPSEEK_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_INTEGRATION,
        reason="仅同时设置 RUN_DEEPSEEK_INTEGRATION=1 和 DEEPSEEK_API_KEY 时调用真实 API",
    ),
]


def make_live_plugin():
    """创建使用环境变量密钥的真实调用插件。"""

    spec = importlib.util.spec_from_file_location("deepseek_anthropic_provider_integration", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    plugin = module.create_plugin()
    config = plugin.get_default_config()
    config["auth"]["api_key"] = ""
    config["auth"]["api_key_env"] = "DEEPSEEK_API_KEY"
    config["model"]["max_tokens"] = 1024
    config["thinking"]["thinking_mode"] = "disabled"
    config["search"]["max_search_uses"] = 1
    plugin.set_plugin_config(config)
    plugin._set_context(
        SimpleNamespace(
            logger=SimpleNamespace(
                debug=MagicMock(),
                info=MagicMock(),
                warning=MagicMock(),
                error=MagicMock(),
            )
        )
    )
    return module, plugin


async def test_live_ping() -> None:
    """验证当前密钥、模型和 Anthropic 接口可用。"""

    _module, plugin = make_live_plugin()
    result = await plugin._call_deepseek("请只回复 pong。", system="你是连通性测试助手。")

    assert result.strip()


async def test_live_single_search() -> None:
    """验证当前账号支持配置中的 Web Search server tool。"""

    module, plugin = make_live_plugin()
    result = await plugin._call_deepseek(
        "请联网搜索 DeepSeek 官方网站，并用一句话回答。",
        system="你是搜索连通性测试助手。",
        tools=module._build_web_search_tools(plugin.config, max_uses=1),
    )

    assert result.strip()
