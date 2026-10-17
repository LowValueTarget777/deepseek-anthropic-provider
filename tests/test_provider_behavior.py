"""Configuration, provider selection, and public Tool contracts."""

from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import ast
import copy
import importlib.util
import json
import tomllib

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("deepseek_web_tools", PLUGIN_DIR / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_plugin(overrides=None):
    module = load_plugin_module()
    # 离线测试不读取工作区真实的运行配置。
    with patch.object(module, "_capture_legacy_settings", return_value={}, create=True):
        plugin = module.create_plugin()
    config = plugin.get_default_config()
    for section, values in (overrides or {}).items():
        config.setdefault(section, {}).update(values)
    plugin.set_plugin_config(config)
    logger = SimpleNamespace(**{name: MagicMock() for name in ("debug", "info", "warning", "error")})
    plugin._set_context(SimpleNamespace(logger=logger, send=SimpleNamespace(text=AsyncMock())))
    return module, plugin


def provider(name="DeepSeek", key="test-placeholder", base_url="https://api.deepseek.com/v1"):
    return {"name": name, "api_key": key, "base_url": base_url}


def test_release_metadata_and_example_match():
    module, plugin = make_plugin()
    manifest = json.loads((PLUGIN_DIR / "_manifest.json").read_text(encoding="utf-8"))
    project = tomllib.loads((PLUGIN_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    example = tomllib.loads((PLUGIN_DIR / "config.example.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((PLUGIN_DIR / "uv.lock").read_text(encoding="utf-8"))
    assert manifest["version"] == project["version"] == module.PLUGIN_VERSION == "0.3.0"
    assert manifest["name"] == "Deepseek联网工具"
    assert manifest["id"] == "LowValueTarget.deepseek-anthropic-provider"
    assert next(p for p in lock["package"] if p["name"] == project["name"])["version"] == module.PLUGIN_VERSION
    assert example == plugin.get_default_config()
    assert "api_key" not in json.dumps(example)
    assert set(manifest["capabilities"]) == {"tool", "send.text"}
    assert {d["name"]: d["version_spec"] for d in manifest["dependencies"]} == {
        "httpx": ">=0.28.1,<1.0.0", "maibot-plugin-sdk": ">=2.5.2,<3.0.0",
    }
    assert "httpx>=0.28.1,<1.0.0" in project["dependencies"]
    assert not any(p["name"] == "anthropic" for p in lock["package"])


def test_only_public_sdk_and_no_local_crawler():
    code = (PLUGIN_DIR / "plugin.py").read_text(encoding="utf-8")
    tree = ast.parse(code)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(item.name for item in node.names)
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name == "src" or name.startswith("src.") for name in imports)
    assert not {"anthropic", "requests", "bs4"} & set(imports)
    _, plugin = make_plugin()
    assert {c["name"] for c in plugin.get_components() if c["type"] == "TOOL"} == {"search_and_summarize", "fetch_page"}


def test_schema_preserves_tabs_without_credential_input():
    module, _ = make_plugin()
    schema = module.DeepseekWebToolsPlugin.build_config_schema()
    assert schema["layout"]["type"] == "tabs"
    assert [tab["title"] for tab in schema["layout"]["tabs"]] == [
        "基础设置", "网页搜索", "网页抓取", "性能与超时", "调试与日志",
    ]
    assert [tab["sections"] for tab in schema["layout"]["tabs"]] == [[name] for name in ("plugin", "search", "fetch", "runtime", "debug")]
    assert "api_key" not in json.dumps(schema)
    assert "provider_name" not in json.dumps(schema)
    assert "model_config_path" not in json.dumps(schema)
    assert not {"auth", "model", "thinking", "provider"} & schema["sections"].keys()
    fields = schema["sections"]["search"]["fields"]
    assert fields["latest_news_enabled"]["default"] is False
    assert fields["latest_news_enabled"]["label"] == "搜索最新消息"
    assert fields["latest_news_days"]["default"] == 7
    assert fields["count"]["default"] == 50
    assert fields["allowed_sites"]["type"] == "array"
    assert fields["allowed_sites"]["item_type"] == "string"
    assert fields["sort_by"]["choices"] == ["综合相关性", "发布时间从新到旧", "权威性优先"]
    assert fields["summary_mode"]["choices"] == ["长摘要优先", "短摘要优先", "长短摘要都返回"]
    for section in schema["sections"].values():
        for field in section["fields"].values():
            if field["description"] and not field["hidden"]:
                assert field["hint"] == field["description"]
    assert fields["include_site_icon"]["default"] is False
    assert fields["max_total_text_chars"]["default"] == 60000


def test_legacy_migration_removes_keys_and_preserves_runtime_settings():
    _, plugin = make_plugin()
    old = {
        "plugin": {"enabled": False, "config_version": "0.2.5", "max_concurrent_requests": 2, "coalesce_requests": False},
        "auth": {"api_key": "PRIVATE_OLD_KEY", "api_key_env": "DEEPSEEK_API_KEY"},
        "model": {"model_choice": "deepseek-flash", "request_timeout_seconds": 90},
        "thinking": {"thinking_mode": "enabled"},
        "search": {"enabled": False, "web_search_tool": "web_search_20260209", "max_search_uses": 5, "default_depth": "deep"},
        "debug": {"log_raw_summary": True},
    }
    before = copy.deepcopy(old)
    new, changed = plugin.normalize_plugin_config(old)
    assert changed
    assert old == before
    assert new["runtime"]["max_concurrent_requests"] == 2
    assert new["runtime"]["coalesce_requests"] is False
    assert new["runtime"]["request_timeout_seconds"] == 90
    assert new["debug"]["log_request_summary"] is True
    assert new["plugin"]["enabled"] is False
    assert new["search"]["enabled"] is False
    assert new["search"]["count"] == 50
    assert "PRIVATE_OLD_KEY" not in json.dumps(new)
    assert not {"auth", "model", "thinking"} & new.keys()
    assert not {"web_search_tool", "max_search_uses", "default_depth"} & new["search"].keys()


def test_migration_is_idempotent_and_does_not_downgrade_future():
    _, plugin = make_plugin()
    default = plugin.get_default_config()
    normalized, changed = plugin.normalize_plugin_config(default)
    assert normalized == default and not changed
    future = {"plugin": {"config_version": "9.0.0"}, "future": {"keep": True}}
    assert plugin.normalize_plugin_config(future) == (future, False)


@pytest.mark.parametrize("url", ["https://api.deepseek.com", "https://api.deepseek.com/v1/", "https://api.deepseek.com/anthropic", "https://api.deepseek.com:443/anthropic/v1"])
def test_official_provider_addresses(url):
    module, _ = make_plugin()
    assert module._select_provider({"api_providers": [provider(base_url=url)]}) == ("DeepSeek", "test-placeholder")


@pytest.mark.parametrize("url", ["http://api.deepseek.com", "https://api.deepseek.com.evil.test/v1", "https://proxy.example/deepseek", "https://api.deepseek.com/v1?x=1", "https://user:pass@api.deepseek.com", "https://api.deepseek.com:8443/v1"])
def test_third_party_keys_are_not_sent_to_official_api(url):
    module, _ = make_plugin()
    with pytest.raises(module.DeepSeekRequestError) as error:
        module._select_provider({"api_providers": [provider(base_url=url)]})
    assert error.value.code == "provider_missing"


@pytest.mark.parametrize("data,code", [
    ({}, "provider_missing"), ({"api_providers": []}, "provider_missing"),
    ({"api_providers": [provider(key="")]}, "key_missing"),
    ({"api_providers": [provider(key="bad key")]}, "key_missing"),
    ({"api_providers": [provider("first"), provider("other")]}, "provider_ambiguous"),
])
def test_provider_failures_are_explicit(data, code):
    module, _ = make_plugin()
    with pytest.raises(module.DeepSeekRequestError) as error:
        module._select_provider(data)
    assert error.value.code == code


def test_provider_name_selection_and_missing_name():
    module, _ = make_plugin()
    data = {"api_providers": [provider("first", "first-key"), provider("second", "second-key")]}
    assert module._select_provider(data, "second") == ("second", "second-key")
    with pytest.raises(module.DeepSeekRequestError):
        module._select_provider(data, "missing")


def test_multiple_providers_can_be_selected_in_maibot_without_plugin_page():
    module, _ = make_plugin()
    data = {"api_providers": [provider("first", "first-key"), provider("deepseek", "chosen-key")]}
    assert module._select_provider(data) == ("deepseek", "chosen-key")
    assert module._select_provider(data, "first") == ("first", "first-key")


def test_hiding_provider_page_does_not_erase_existing_advanced_settings():
    _, plugin = make_plugin({"provider": {"provider_name": "legacy-name", "model_config_path": "custom/model_config.toml"}})
    config, _ = plugin.normalize_plugin_config(plugin.get_plugin_config_data())
    assert config["provider"] == {"provider_name": "legacy-name", "model_config_path": "custom/model_config.toml"}


@pytest.mark.parametrize("now,days,expected", [
    ("2026-10-16T17:00:00+00:00", 7, "2026-10-10"),
    ("2026-01-01T00:01:00+08:00", 1, "2025-12-31"),
    ("2024-03-01T12:00:00+08:00", 1, "2024-02-29"),
])
def test_latest_news_uses_beijing_date_across_boundaries(now, days, expected):
    module, plugin = make_plugin({"search": {"latest_news_enabled": True, "latest_news_days": days}})
    query, cutoff = module._build_search_query("DeepSeek", plugin.config.search, now=datetime.fromisoformat(now))
    assert cutoff == expected
    assert query == f"DeepSeek after:{expected}"


@pytest.mark.parametrize("query", [
    "DeepSeek after:2025", "DeepSeek before:2026-01-01", "DeepSeek after:2025-01-01 before:2026-01-01",
    '"release notes" site:example.com after:2026-01-01',
])
def test_latest_news_respects_explicit_date_filters(query):
    module, plugin = make_plugin({"search": {"latest_news_enabled": True}})
    assert module._build_search_query(query, plugin.config.search) == (query, None)


@pytest.mark.parametrize("query", ['DeepSeek "after:2020"', "DeepSeek 'before:2020'", '"history after:2020"'])
def test_date_operator_inside_quoted_phrase_is_not_a_filter(query):
    module, plugin = make_plugin({"search": {"latest_news_enabled": True}})
    effective, cutoff = module._build_search_query(query, plugin.config.search, now=datetime(2026, 10, 17, tzinfo=timezone.utc))
    assert cutoff == "2026-10-10"
    assert effective == query + " after:2026-10-10"


def test_latest_news_does_not_truncate_or_silently_drop_oversized_filter():
    module, plugin = make_plugin({"search": {"latest_news_enabled": True}})
    with pytest.raises(module.DeepSeekRequestError, match="超过 128 字"):
        module._build_search_query("x" * 128, plugin.config.search)
    effective, _ = module._build_search_query("x" * 111, plugin.config.search)
    assert len(effective) == 128


def test_latest_news_disabled_keeps_query_unchanged():
    module, plugin = make_plugin()
    assert module._build_search_query("x" * 128, plugin.config.search) == ("x" * 128, None)


def test_configured_query_operators_combine_with_official_syntax():
    module, plugin = make_plugin({"search": {
        "allowed_sites": ["a.com", "B.com", "a.com"], "blocked_sites": ["bad.com"],
        "excluded_terms": ["广告", "release notes"], "exact_phrases": ["V4 模型"],
        "languages": ["zh", "en", "zh"], "published_after": "2025", "published_before": "2026-06-01",
    }})
    query, cutoff = module._build_search_query("DeepSeek", plugin.config.search)
    assert query == 'DeepSeek site:a.com OR site:b.com -site:bad.com -广告 -"release notes" "V4 模型" lang:zh,en after:2025 before:2026-06-01'
    assert cutoff is None
    assert len(query) <= 128


def test_explicit_query_overrides_defaults_but_keeps_exclusions():
    module, plugin = make_plugin({"search": {
        "allowed_sites": ["default.com"], "blocked_sites": ["bad.com"], "languages": ["zh"],
        "published_after": "2026", "published_before": "2027", "latest_news_enabled": True,
    }})
    query = "DeepSeek site:explicit.com lang:en before:2020"
    assert module._build_search_query(query, plugin.config.search) == (query + " -site:bad.com", None)


def test_fixed_dates_override_latest_news_and_blank_list_items_are_ignored():
    module, plugin = make_plugin({"search": {
        "latest_news_enabled": True, "published_after": "2024-02-29", "allowed_sites": [" "],
        "languages": [" "], "exact_phrases": [" "], "excluded_terms": [" "],
    }})
    assert module._build_search_query("DeepSeek", plugin.config.search) == ("DeepSeek after:2024-02-29", None)


@pytest.mark.parametrize("quoted", ['-"old after:2020 release"', '"old site:a.com lang:en before:2020 release"'])
def test_operators_inside_phrases_do_not_override_defaults(quoted):
    module, plugin = make_plugin({"search": {"allowed_sites": ["b.com"], "languages": ["zh"], "published_after": "2026"}})
    query, _ = module._build_search_query("DeepSeek " + quoted, plugin.config.search)
    assert query.endswith("site:b.com lang:zh after:2026")


@pytest.mark.parametrize("options", [
    {"allowed_sites": ["https://example.com"]}, {"allowed_sites": ["a.com OR site:b.com"]},
    {"blocked_sites": ["a.com:443"]}, {"blocked_sites": ["a.com/path"]}, {"allowed_sites": ["-bad.com"]},
    {"languages": ["zh,en"]}, {"languages": ["en after:2020"]},
    {"exact_phrases": ['unclosed"']}, {"excluded_terms": ["hello\nworld"]},
    {"published_after": "2025-02-29"}, {"published_after": "0000"}, {"published_before": "2026-13-01"},
    {"published_after": "2027", "published_before": "2026"},
    {"published_after": "2026", "published_before": "2026-01-01"},
])
def test_invalid_default_filters_are_actionable(options):
    module, plugin = make_plugin({"search": options})
    with pytest.raises(module.DeepSeekRequestError) as exc:
        module._build_search_query("DeepSeek", plugin.config.search)
    assert exc.value.code == "invalid_input"


def test_default_filters_do_not_silently_truncate_long_queries():
    module, plugin = make_plugin({"search": {"allowed_sites": ["example.com"]}})
    with pytest.raises(module.DeepSeekRequestError, match="超过 128 字"):
        module._build_search_query("x" * 128, plugin.config.search)


def test_apostrophe_in_a_word_remains_valid_with_configured_filters():
    module, plugin = make_plugin({"search": {"languages": ["en"]}})
    assert module._build_search_query("Microsoft's news", plugin.config.search) == ("Microsoft's news lang:en", None)


def test_migration_preserves_explicit_search_count():
    _, plugin = make_plugin()
    normalized, _ = plugin.normalize_plugin_config({"search": {"count": 5}})
    assert normalized["search"]["count"] == 5


@pytest.mark.parametrize("left,right,equal", [
    ("https://EXAMPLE.com:443/a?q=1#one", "https://example.com/a?q=1#one", True),
    ("https://example.com/a#one", "https://example.com/a#two", False),
    ("https://example.com/#/article/1", "https://example.com/#/article/2", False),
    ("https://example.com/#!/article/1", "https://example.com/#!/article/2", False),
    ("https://example.com", "https://example.com/", True),
    ("https://example.com/a?q=1", "https://example.com/a?q=2", False),
    ("https://example.com/a", "https://example.com/A", False),
    ("http://example.com/a", "https://example.com/a", False),
    ("https://[2001:db8::1]:443/a", "https://[2001:db8::1]/a", True),
])
def test_deduplication_key_preserves_meaningful_url_differences(left, right, equal):
    module, _ = make_plugin()
    assert (module._search_url_key(left) == module._search_url_key(right)) is equal


def test_model_config_is_read_only_and_accepts_bom(tmp_path):
    module, _ = make_plugin()
    path = tmp_path / "model_config.toml"
    original = b'\xef\xbb\xbf[[api_providers]]\nname="DeepSeek"\nbase_url="https://api.deepseek.com"\napi_key="test-placeholder"\n'
    path.write_bytes(original)
    assert module._read_provider(path, "") == ("DeepSeek", "test-placeholder")
    assert path.read_bytes() == original


def test_invalid_config_does_not_reveal_file_contents(tmp_path):
    module, _ = make_plugin()
    path = tmp_path / "model_config.toml"
    path.write_text("PRIVATE_BROKEN_CONFIG", encoding="utf-8")
    with pytest.raises(module.DeepSeekRequestError) as error:
        module._read_provider(path, "")
    assert "PRIVATE" not in str(error.value)


def test_discovery_supports_host_cwd_and_standard_install(tmp_path, monkeypatch):
    module, _ = make_plugin()
    host = tmp_path / "host"
    (host / "config").mkdir(parents=True)
    target = host / "config/model_config.toml"
    target.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(host / "plugins/deepseek/plugin.py"))
    monkeypatch.chdir(tmp_path)
    assert module._find_model_config("") == target.resolve()
    monkeypatch.chdir(host)
    assert module._find_model_config("") == target.resolve()


def test_discovery_requires_choice_if_two_hosts_match(tmp_path, monkeypatch):
    module, _ = make_plugin()
    for name in ("first", "second"):
        (tmp_path / name / "config").mkdir(parents=True)
        (tmp_path / name / "config/model_config.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(tmp_path / "first/plugins/deepseek/plugin.py"))
    monkeypatch.chdir(tmp_path / "second")
    with pytest.raises(module.DeepSeekRequestError) as error:
        module._find_model_config("")
    assert error.value.code == "config_ambiguous"
    target = tmp_path / "second/config/model_config.toml"
    assert module._find_model_config(str(target)) == target.resolve()


@pytest.mark.parametrize("url", ["", None, "example.com", "ftp://example.com", "https://u:p@example.com", "https://example.com bad", "https://[invalid", "https://example.com/\\bad", "https://example.com/\x00x", "https://example.com/" + "x" * 8192])
def test_invalid_fetch_urls(url):
    module, _ = make_plugin()
    assert not module._is_valid_web_url(url)
