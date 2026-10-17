"""Runner 边界回归；只读解析宿主纯函数，不启动或导入主程序。"""

from typing import Any, Dict, Mapping
from unittest.mock import patch
import ast
import copy
import importlib.util
import json
import tomllib

import pytest

from test_provider_behavior import PLUGIN_DIR, load_plugin_module, make_plugin


@pytest.fixture
def runner_rebuild():
    source = PLUGIN_DIR.parents[1] / "src/plugin_runtime/runner/runner_main.py"
    if not source.is_file():
        pytest.skip("独立插件环境未附带 MaiBot 源码；其余离线测试仍可运行")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {
        "_deep_copy_plugin_config_value", "_deep_copy_plugin_config_mapping",
        "_is_plugin_config_value_type_compatible", "_overlay_plugin_config_fields", "rebuild_plugin_config_data",
    }
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names, "宿主重建契约已变更，需要重新核对迁移链路"
    namespace = {"Any": Any, "Dict": Dict, "Mapping": Mapping}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["rebuild_plugin_config_data"]


def create_from_local_config(tmp_path, text):
    module = load_plugin_module()
    config_path = tmp_path / "config.toml"
    config_path.write_text(text, encoding="utf-8")
    with patch.object(module, "__file__", str(tmp_path / "plugin.py")):
        plugin = module.create_plugin()
    assert config_path.read_text(encoding="utf-8") == text
    return module, plugin


LEGACY_CONFIG = '''[plugin]
config_version = "0.2.5"
enabled = false
max_concurrent_requests = 2
coalesce_requests = false
[model]
request_timeout_seconds = 90
[debug]
log_raw_summary = true
[auth]
api_key = "PRIVATE_TEST_PLACEHOLDER"
'''


def test_runner_upgrade_preserves_renamed_settings_before_old_fields_are_removed(tmp_path, runner_rebuild):
    module, plugin = create_from_local_config(tmp_path, LEGACY_CONFIG)
    old = tomllib.loads(LEGACY_CONFIG)
    before = copy.deepcopy(old)
    prepared = runner_rebuild(plugin.get_default_config(), old)
    assert "model" not in prepared and "auth" not in prepared
    assert "max_concurrent_requests" not in prepared["plugin"]
    normalized, _ = plugin.normalize_plugin_config(prepared)
    assert normalized["plugin"]["config_version"] == module.PLUGIN_VERSION
    assert old == before
    plugin.set_plugin_config(normalized)
    assert plugin.config.runtime.max_concurrent_requests == 2
    assert plugin.config.runtime.coalesce_requests is False
    assert plugin.config.runtime.request_timeout_seconds == 90
    assert plugin.config.debug.log_request_summary is True
    assert plugin.config.plugin.enabled is False
    assert plugin.get_default_config() == module.DeepseekWebToolsPlugin.build_default_config()
    assert "PRIVATE" not in json.dumps(plugin.__dict__, default=str)
    assert not {"auth", "model", "thinking"} & normalized.keys()


def test_explicit_new_settings_override_legacy_startup_defaults(tmp_path, runner_rebuild):
    _, plugin = create_from_local_config(tmp_path, LEGACY_CONFIG)
    old = tomllib.loads(LEGACY_CONFIG)
    old["runtime"] = {"request_timeout_seconds": 120, "max_concurrent_requests": 4, "coalesce_requests": True}
    old["debug"]["log_request_summary"] = False
    prepared = runner_rebuild(plugin.get_default_config(), old)
    plugin.set_plugin_config(prepared)
    assert plugin.config.runtime.request_timeout_seconds == 120
    assert plugin.config.runtime.max_concurrent_requests == 4
    assert plugin.config.runtime.coalesce_requests is True
    assert plugin.config.debug.log_request_summary is False


def test_legacy_snapshot_is_cleared_after_injection_and_cannot_override_later_changes(tmp_path):
    module, plugin = create_from_local_config(tmp_path, LEGACY_CONFIG)
    plugin.set_plugin_config(plugin.get_default_config())
    assert plugin.config.runtime.max_concurrent_requests == 2
    canonical = module.DeepseekWebToolsPlugin.build_default_config()
    plugin.set_plugin_config(canonical)
    assert plugin.config.runtime.max_concurrent_requests == 4
    assert plugin.config.runtime.coalesce_requests is True
    assert plugin.config.debug.log_request_summary is False


@pytest.mark.parametrize("version", ["0.3.0", "9.0.0"])
def test_current_and_future_local_configs_do_not_supply_legacy_defaults(tmp_path, version):
    module, plugin = create_from_local_config(tmp_path, LEGACY_CONFIG.replace('"0.2.5"', f'"{version}"'))
    assert plugin.get_default_config() == module.DeepseekWebToolsPlugin.build_default_config()


def test_old_config_with_explicit_new_fields_preserves_new_field_precedence(tmp_path):
    _, plugin = create_from_local_config(tmp_path, LEGACY_CONFIG + '''
[runtime]
request_timeout_seconds = 75
max_concurrent_requests = 3
coalesce_requests = true
''')
    defaults = plugin.get_default_config()
    # 新字段交给 Runner 从原始配置回填，不能用旧别名替代其默认值。
    assert defaults["runtime"]["request_timeout_seconds"] == 120
    assert defaults["runtime"]["max_concurrent_requests"] == 4
    assert defaults["runtime"]["coalesce_requests"] is True


def test_missing_local_config_keeps_normal_defaults(tmp_path):
    module = load_plugin_module()
    with patch.object(module, "__file__", str(tmp_path / "plugin.py")):
        plugin = module.create_plugin()
    assert plugin.get_default_config() == module.DeepseekWebToolsPlugin.build_default_config()


@pytest.mark.parametrize("text", [
    "PRIVATE_INVALID_TOML", LEGACY_CONFIG.replace("max_concurrent_requests = 2", "max_concurrent_requests = 999"),
])
def test_migration_capture_errors_are_safe_and_do_not_silently_reset_settings(tmp_path, text):
    module = load_plugin_module()
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(module.DeepSeekRequestError) as error:
        module._capture_legacy_settings(path)
    assert error.value.code == "config_invalid"
    assert "PRIVATE" not in str(error.value)
    assert path.read_text(encoding="utf-8") == text


def test_migration_capture_is_bounded_and_accepts_bom(tmp_path):
    module = load_plugin_module()
    path = tmp_path / "config.toml"
    path.write_text(LEGACY_CONFIG, encoding="utf-8-sig")
    captured = module._capture_legacy_settings(path)
    assert captured == {
        "runtime": {"request_timeout_seconds": 90.0, "max_concurrent_requests": 2, "coalesce_requests": False},
        "debug": {"log_request_summary": True},
    }
    with patch.object(module, "MAX_CONFIG_BYTES", 16):
        with pytest.raises(module.DeepSeekRequestError, match="过大"):
            module._capture_legacy_settings(path)


@pytest.mark.parametrize("sort_by,summary_mode", [
    ("relevance", "summary"), ("date", "snippet"), ("authority", "both"),
    ("综合相关性", "长摘要优先"), ("发布时间从新到旧", "短摘要优先"), ("权威性优先", "长短摘要都返回"),
])
def test_chinese_choices_and_legacy_english_values_round_trip(sort_by, summary_mode):
    module, plugin = make_plugin({"search": {"sort_by": sort_by, "summary_mode": summary_mode}})
    normalized = plugin.get_plugin_config_data()
    assert normalized["search"]["sort_by"] in module.SEARCH_SORT_OPTIONS.values()
    assert normalized["search"]["summary_mode"] in module.SEARCH_SUMMARY_OPTIONS.values()
    assert plugin.normalize_plugin_config(normalized) == (normalized, False)
    fields = plugin.get_webui_config_schema()["sections"]["search"]["fields"]
    assert normalized["search"]["sort_by"] in fields["sort_by"]["choices"]
    assert normalized["search"]["summary_mode"] in fields["summary_mode"]["choices"]


def test_every_component_rpc_timeout_exceeds_supported_request_timeout():
    module, plugin = make_plugin()
    maximum = plugin.get_webui_config_schema()["sections"]["runtime"]["fields"]["request_timeout_seconds"]["max"]
    for component in plugin.get_components():
        assert component["metadata"]["timeout_ms"] == module.COMPONENT_RPC_TIMEOUT_MS
        assert component["metadata"]["timeout_ms"] >= (maximum + 30) * 1000


def test_actual_host_resolves_declared_timeout_instead_of_default_60_seconds():
    source = PLUGIN_DIR.parents[1] / "src/plugin_runtime/host/component_timeout.py"
    if not source.is_file():
        pytest.skip("独立插件环境未附带 MaiBot 超时解析器")
    spec = importlib.util.spec_from_file_location("host_component_timeout_contract", source)
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    module, plugin = make_plugin()
    for component in plugin.get_components():
        declared = component["metadata"].get("timeout_ms", 0)
        assert host.resolve_component_rpc_timeout_ms(declared) == module.COMPONENT_RPC_TIMEOUT_MS
        assert host.resolve_component_rpc_timeout_ms(declared) > 600000
