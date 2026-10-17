"""Exercise direct Search / Fetch requests through the real HTTPX client."""

import asyncio
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from test_provider_behavior import make_plugin


def write_model_config(path, key="test-placeholder"):
    path.write_text(
        '[[api_providers]]\nname="DeepSeek"\nbase_url="https://api.deepseek.com/v1"\napi_key="' + key + '"\n',
        encoding="utf-8",
    )


def search_result(**updates):
    result = {
        "title": "Official page", "url": "https://example.com/article?id=1", "snippet": "short",
        "summary": "relevant summary", "content": "", "rerank_score": 2.4, "authority": 3,
        "date": "2026-10-17T00:00:00+00:00", "site_name": "Example",
    }
    result.update(updates)
    return result


@pytest.fixture
async def runtime(tmp_path):
    path = tmp_path / "model_config.toml"
    write_model_config(path)
    module, plugin = make_plugin({"provider": {"model_config_path": str(path)}, "runtime": {"requests_per_second": 5}})
    state = SimpleNamespace(
        requests=[], search={"results": [search_result()]}, fetch={"title": "Page", "content": "# Page\n\nBody"},
        status=200, callback=None, raw=None, config_path=path,
    )

    async def transport(request):
        state.requests.append(request)
        if state.callback is not None:
            result = await state.callback(request)
            if result is not None:
                return result
        if state.raw is not None:
            return httpx.Response(state.status, content=state.raw, headers={"x-request-id": "req_test"})
        data = state.search if request.url.path.endswith("/search") else state.fetch
        return httpx.Response(state.status, json=data, headers={"x-request-id": "req_test"})

    original = httpx.AsyncClient

    def factory(**kwargs):
        return original(transport=httpx.MockTransport(transport), **kwargs)

    with patch.object(module.httpx, "AsyncClient", side_effect=factory) as client_factory:
        state.client_factory = client_factory
        try:
            yield module, plugin, state
        finally:
            await plugin.on_unload()


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def test_search_uses_new_endpoint_and_all_documented_fields(runtime):
    _, plugin, state = runtime
    query = 'DeepSeek site:github.com lang:zh,en after:2026-01-01'
    result = await plugin.handle_search_and_summarize(
        query=query, count=8, need_content=True, ori_question="Which release?", localization="203.0.113.1",
    )
    assert result["success"]
    request = state.requests[0]
    assert str(request.url) == "https://api.deepseek.com/v1/tools/search"
    assert request.method == "POST"
    assert request.headers["authorization"] == "Bearer test-placeholder"
    assert json.loads(request.content) == {
        "query": query, "count": 8, "need_content": True, "ori_question": "Which release?", "localization": "203.0.113.1",
    }
    data = json.loads(result["content"])
    assert data["results"][0]["rerank_score"] == 2.4
    assert data["results"][0]["summary"] == "relevant summary"
    assert data["results"][0]["authority"] == 3
    plugin.ctx.send.text.assert_not_awaited()


async def test_search_defaults_request_50_without_adding_extra_api_fields(runtime):
    _, plugin, state = runtime
    state.search = {"results": [search_result(url=f"https://example.com/{i}") for i in range(50)]}
    result = await plugin.handle_search_and_summarize(query="DeepSeek")
    assert result["success"]
    assert json.loads(state.requests[0].content) == {"query": "DeepSeek", "count": 50, "need_content": False}
    data = json.loads(result["content"])
    assert len(data["results"]) == 50
    assert data["result_info"]["received_count"] == data["result_info"]["returned_count"] == 50
    assert all("summary" in item and "snippet" not in item and "site_icon" not in item for item in data["results"])
    assert len(state.requests) == 1


async def test_search_settings_and_explicit_tool_overrides(runtime):
    _, plugin, state = runtime
    plugin.config.search.allowed_sites = ["example.com"]
    plugin.config.search.languages = ["zh"]
    plugin.config.search.localization = "203.0.113.2"
    plugin.config.search.need_content = True
    plugin.config.search.send_original_question = False
    result = await plugin.handle_search_and_summarize(query="DeepSeek", ori_question="PRIVATE_QUESTION")
    assert result["success"]
    assert json.loads(state.requests[0].content) == {
        "query": "DeepSeek site:example.com lang:zh", "count": 50, "need_content": True,
        "localization": "203.0.113.2",
    }
    result = await plugin.handle_search_and_summarize(
        query="DeepSeek site:other.com lang:en", count=2, need_content=False, localization="",
    )
    assert result["success"]
    assert json.loads(state.requests[1].content) == {
        "query": "DeepSeek site:other.com lang:en", "count": 2, "need_content": False,
    }


@pytest.mark.parametrize("settings", [
    {"localization": "China"}, {"allowed_sites": ["a.com OR site:b.com"]},
    {"published_after": "2025-02-29"}, {"exact_phrases": ['bad"quote']},
])
async def test_invalid_configured_search_conditions_never_call_api(runtime, settings):
    _, plugin, state = runtime
    for key, value in settings.items():
        setattr(plugin.config.search, key, value)
    result = await plugin.handle_search_and_summarize(query="DeepSeek")
    assert not result["success"] and result["error_code"] == "invalid_input"
    assert not state.requests


async def test_filters_work_even_when_score_fields_are_hidden(runtime):
    _, plugin, state = runtime
    plugin.config.search.min_rerank_score = 1.5
    plugin.config.search.min_authority = 3
    plugin.config.search.include_authority = False
    plugin.config.search.include_rerank_score = False
    state.search = {"results": [
        search_result(url="https://example.com/good", rerank_score=1.5, authority=3),
        search_result(url="https://example.com/low", rerank_score=1.4, authority=4),
        search_result(url="https://example.com/unknown", rerank_score=None, authority=-1),
        search_result(url="https://example.com/weak", rerank_score=2.5, authority=2),
    ]}
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert [item["url"] for item in data["results"]] == ["https://example.com/good"]
    assert "authority" not in data["results"][0] and "rerank_score" not in data["results"][0]
    assert data["result_info"]["filtered_count"] == 3
    assert len(state.requests) == 1


async def test_quality_filters_off_preserve_unknown_scores_and_on_explain_empty_results(runtime):
    _, plugin, state = runtime
    state.search = {"results": [search_result(rerank_score=None, authority=-1)]}
    first = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert len(first["results"]) == 1
    plugin.config.search.min_rerank_score = 1.5
    result = await plugin.handle_search_and_summarize(query="DeepSeek")
    assert result["success"]
    data = json.loads(result["content"])
    assert not data["results"] and "质量筛选" in data["message"]
    assert data["result_info"]["received_count"] == data["result_info"]["filtered_count"] == 1


@pytest.mark.parametrize("sort_by,expected", [
    ("relevance", ["undated", "old", "new", "unknown"]),
    ("date", ["new", "old", "undated", "unknown"]),
    ("authority", ["new", "old", "undated", "unknown"]),
])
async def test_search_sorting_uses_real_dates_and_places_unknown_metrics_last(runtime, sort_by, expected):
    module, plugin, state = runtime
    plugin.config.search.sort_by = module.SEARCH_SORT_OPTIONS[sort_by]
    state.search = {"results": [
        search_result(url="https://example.com/old", date="2026-10-17T10:00:00+08:00", authority=3, rerank_score=2.5),
        search_result(url="https://example.com/new", date="2026-10-17T03:00:00Z", authority=4, rerank_score=2.0),
        search_result(url="https://example.com/undated", date=None, authority=-1, rerank_score=3.0),
        search_result(url="https://example.com/unknown", date="not-a-date", authority=None, rerank_score=None),
    ]}
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert [item["url"].rsplit("/", 1)[-1] for item in data["results"]] == expected
    assert data["result_info"]["sort_by"] == sort_by


async def test_search_deduplication_keeps_best_duplicate_and_distinct_query_parameters(runtime):
    _, plugin, state = runtime
    state.search = {"results": [
        search_result(url="https://example.com/a?id=1#section", rerank_score=1.0),
        search_result(url="https://EXAMPLE.com:443/a?id=1#section", rerank_score=3.0),
        search_result(url="https://example.com/a?id=2", rerank_score=2.0),
    ]}
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert [item["rerank_score"] for item in data["results"]] == [3.0, 2.0]
    assert data["result_info"]["duplicates_removed"] == 1
    plugin.config.search.deduplicate = False
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert len(data["results"]) == 3 and data["result_info"]["duplicates_removed"] == 0


async def test_distinct_fragment_routes_and_sections_are_not_deduplicated(runtime):
    _, plugin, state = runtime
    urls = [
        "https://example.com/#/article/1", "https://example.com/#/article/2",
        "https://example.com/#!/article/1", "https://example.com/#!/article/2",
        "https://example.com/guide#first", "https://example.com/guide#second",
    ]
    state.search = {"results": [search_result(url=url) for url in urls]}
    result = await plugin.handle_search_and_summarize(query="DeepSeek")
    assert result["success"]
    data = json.loads(result["content"])
    assert [item["url"] for item in data["results"]] == urls
    assert data["result_info"]["duplicates_removed"] == 0
    fetched = await plugin.handle_fetch_page(url=urls[0])
    assert fetched["success"]
    assert json.loads(state.requests[-1].content)["url"] == urls[0]
    assert json.loads(fetched["content"])["url"] == urls[0]


@pytest.mark.parametrize("mode,summary,snippet,expected", [
    ("summary", "long", "short", {"summary": "long"}),
    ("summary", "", "short", {"snippet": "short"}),
    ("snippet", "long", "short", {"snippet": "short"}),
    ("snippet", "long", "", {"summary": "long"}),
    ("both", "long", "short", {"summary": "long", "snippet": "short"}),
])
async def test_summary_selection_preserves_available_fallback(runtime, mode, summary, snippet, expected):
    module, plugin, state = runtime
    plugin.config.search.summary_mode = module.SEARCH_SUMMARY_OPTIONS[mode]
    state.search = {"results": [search_result(summary=summary, snippet=snippet)]}
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert {key: value for key, value in data["results"][0].items() if key in {"summary", "snippet"}} == expected


async def test_optional_metadata_fields_and_site_icon_validation(runtime):
    _, plugin, state = runtime
    plugin.config.search.include_site_icon = True
    plugin.config.search.include_date = False
    plugin.config.search.include_site_name = False
    state.search = {"results": [search_result(site_icon="https://example.com/favicon.ico")]}
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    item = data["results"][0]
    assert item["site_icon"] == "https://example.com/favicon.ico"
    assert "date" not in item and "site_name" not in item
    assert item["title"] and item["url"]
    state.search["results"][0]["site_icon"] = "javascript:alert(1)"
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert data["results"][0]["site_icon"] is None


async def test_text_budget_preserves_all_50_links_and_explicit_truncation(runtime):
    _, plugin, state = runtime
    plugin.config.search.max_total_text_chars = 1000
    state.search = {"results": [
        search_result(url=f"https://example.com/{i}", summary="s" * 800, content="c" * 5000) for i in range(50)
    ]}
    result = await plugin.handle_search_and_summarize(query="DeepSeek", need_content=True)
    assert result["success"]
    data = json.loads(result["content"])
    assert len(data["results"]) == 50
    assert sum(len(item.get(field, "")) for item in data["results"] for field in ("title", "summary", "snippet", "content")) <= 1000
    assert all(item["url"] and item["summary_truncated"] and item["content_truncated"] for item in data["results"])
    assert data["result_info"]["text_truncated"] and "fetch_page" in data["notice"]
    assert len(state.requests) == 1


async def test_inflight_search_uses_a_consistent_settings_snapshot(runtime):
    _, plugin, state = runtime

    async def hot_reload(request):
        plugin.config.search.include_authority = False
        plugin.config.search.min_authority = 4

    state.callback = hot_reload
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert len(data["results"]) == 1 and data["results"][0]["authority"] == 3
    data = json.loads((await plugin.handle_search_and_summarize(query="DeepSeek"))["content"])
    assert not data["results"] and data["result_info"]["filtered_count"] == 1


async def test_fetch_uses_dedicated_endpoint_and_returns_markdown(runtime):
    _, plugin, state = runtime
    url = "https://example.com/article?id=1"
    result = await plugin.handle_fetch_page(url=url)
    assert result["success"]
    request = state.requests[0]
    assert str(request.url) == "https://api.deepseek.com/v1/tools/fetch"
    assert json.loads(request.content) == {"url": url}
    data = json.loads(result["content"])
    assert data["content"] == "# Page\n\nBody"
    assert data["url"] == url
    assert not data["truncated"]
    assert data["next_start_char"] is None


async def test_model_key_rotation_is_read_on_next_request_without_new_pool(runtime):
    _, plugin, state = runtime
    original = state.config_path.read_bytes()
    await plugin.handle_search_and_summarize(query="first")
    assert state.config_path.read_bytes() == original
    write_model_config(state.config_path, "rotated-placeholder")
    await plugin.handle_search_and_summarize(query="second")
    assert [r.headers["authorization"] for r in state.requests] == ["Bearer test-placeholder", "Bearer rotated-placeholder"]
    state.client_factory.assert_called_once()
    assert not plugin._client.is_closed


async def test_legacy_environment_key_is_not_used(runtime, monkeypatch):
    _, plugin, state = runtime
    monkeypatch.setenv("DEEPSEEK_API_KEY", "PRIVATE_LEGACY_ENV")
    state.config_path.unlink()
    result = await plugin.handle_search_and_summarize(query="test")
    assert not result["success"]
    assert not state.requests
    assert "PRIVATE_LEGACY_ENV" not in result["content"]


@pytest.mark.parametrize("options", [
    {"query": ""}, {"query": "x" * 129}, {"query": None}, {"query": "   "},
    {"query": "x", "count": 0}, {"query": "x", "count": 51}, {"query": "x", "count": True},
    {"query": "x", "need_content": "true"}, {"query": "x", "ori_question": ""},
    {"query": "x", "ori_question": "x" * 129}, {"query": "x", "localization": "China"},
    {"query": "x", "localization": False},
])
async def test_invalid_search_options_never_call_api(runtime, options):
    _, plugin, state = runtime
    result = await plugin.handle_search_and_summarize(**options)
    assert not result["success"]
    assert result["error_code"] == "invalid_input"
    assert not state.requests


async def test_query_unicode_limit_and_null_original_question(runtime):
    _, plugin, state = runtime
    result = await plugin.handle_search_and_summarize(query="麦" * 128, ori_question=None, explanation="legacy")
    assert result["success"]
    assert "ori_question" not in json.loads(state.requests[0].content)
    assert "explanation" not in json.loads(state.requests[0].content)


async def test_latest_news_filter_is_sent_to_api_with_returned_date_context(runtime):
    module, plugin, state = runtime
    plugin.config.search.latest_news_enabled = True
    plugin.config.search.latest_news_days = 3
    with patch.object(module, "datetime") as clock:
        clock.now.return_value = datetime(2026, 10, 16, 17, tzinfo=timezone.utc)
        result = await plugin.handle_search_and_summarize(query="DeepSeek 新闻")
    payload = json.loads(state.requests[0].content)
    assert payload == {"query": "DeepSeek 新闻 after:2026-10-14", "count": 50, "need_content": False}
    assert json.loads(result["content"])["time_filter"] == {
        "after": "2026-10-14", "recent_days": 3, "timezone": "UTC+08:00",
    }


async def test_historical_query_is_not_overridden_by_latest_news(runtime):
    _, plugin, state = runtime
    plugin.config.search.latest_news_enabled = True
    query = "DeepSeek after:2025-01-01 before:2026-01-01"
    result = await plugin.handle_search_and_summarize(query=query)
    assert json.loads(state.requests[0].content)["query"] == query
    assert "time_filter" not in json.loads(result["content"])


@pytest.mark.parametrize("query", ["x" * 128, 'DeepSeek "unfinished'])
async def test_invalid_latest_news_query_does_not_call_api(runtime, query):
    _, plugin, state = runtime
    plugin.config.search.latest_news_enabled = True
    result = await plugin.handle_search_and_summarize(query=query)
    assert not result["success"] and result["error_code"] == "invalid_input"
    assert not state.requests


async def test_latest_news_does_not_change_fetch(runtime):
    _, plugin, state = runtime
    plugin.config.search.latest_news_enabled = True
    result = await plugin.handle_fetch_page(url="https://example.com/article?id=1")
    assert result["success"]
    assert json.loads(state.requests[0].content) == {"url": "https://example.com/article?id=1"}


@pytest.mark.parametrize("start", [-1, True, "10"])
async def test_invalid_fetch_start_never_calls_api(runtime, start):
    _, plugin, state = runtime
    result = await plugin.handle_fetch_page(url="https://example.com", start_char=start)
    assert not result["success"] and not state.requests


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 408, 413, 429, 500, 502, 503, 504, 302])
async def test_http_errors_are_safe_and_not_retried(runtime, status):
    _, plugin, state = runtime
    state.status = status
    state.raw = b'{"error":{"message":"PRIVATE_UPSTREAM_RESPONSE"}}'
    result = await plugin.handle_fetch_page(url="https://example.com")
    assert not result["success"]
    assert result["error_code"] == f"http_{status}"
    assert "PRIVATE" not in result["content"]
    assert len(state.requests) == 1
    assert "PRIVATE" not in repr(plugin.ctx.logger.error.call_args_list)


async def test_redirect_never_receives_credentials(runtime):
    _, plugin, state = runtime

    async def redirect(request):
        return httpx.Response(302, headers={"location": "https://untrusted.example/capture"})

    state.callback = redirect
    result = await plugin.handle_fetch_page(url="https://example.com")
    assert not result["success"]
    assert len(state.requests) == 1
    assert state.requests[0].url.host == "api.deepseek.com"


@pytest.mark.parametrize("data", [{"error": {"message": "PRIVATE"}}, {"results": [None]}, {"results": [{"url": "ftp://example.com"}]}, {"results": [search_result(summary=1)]}])
async def test_invalid_search_response_is_not_success(runtime, data):
    _, plugin, state = runtime
    state.search = data
    result = await plugin.handle_search_and_summarize(query="x")
    assert not result["success"]
    assert result["error_code"] == "invalid_response"


async def test_search_empty_results_is_explicit_and_not_fabricated(runtime):
    _, plugin, state = runtime
    state.search = {"results": []}
    result = await plugin.handle_search_and_summarize(query="x")
    assert result["success"]
    data = json.loads(result["content"])
    assert not data["results"]
    assert "未找到" in data["message"]


@pytest.mark.parametrize("payload", [{"title": "Only title"}, {"content": ""}, {"content": " "}, {"content": 123}])
async def test_fetch_missing_body_is_failure(runtime, payload):
    _, plugin, state = runtime
    state.fetch = payload
    result = await plugin.handle_fetch_page(url="https://example.com")
    assert not result["success"] and result["error_code"] == "empty_response"


async def test_long_fetch_is_explicitly_chunked_and_can_be_continued(runtime):
    _, plugin, state = runtime
    plugin.config.fetch.max_content_chars = 1000
    state.fetch = {"title": "Page", "content": "A" * 1000 + "B" * 500}
    first = json.loads((await plugin.handle_fetch_page(url="https://example.com"))["content"])
    assert first["content"] == "A" * 1000
    assert first["truncated"] and first["next_start_char"] == 1000 and first["notice"]
    second = json.loads((await plugin.handle_fetch_page(url="https://example.com", start_char=1000))["content"])
    assert second["content"] == "B" * 500 and not second["truncated"]
    assert json.loads(state.requests[1].content) == {"url": "https://example.com"}


async def test_search_body_limit_is_marked(runtime):
    _, plugin, state = runtime
    plugin.config.search.max_result_chars = 500
    state.search = {"results": [search_result(content="x" * 600)]}
    result = await plugin.handle_search_and_summarize(query="x", need_content=True)
    item = json.loads(result["content"])["results"][0]
    assert item["content"] == "x" * 500
    assert item["content_truncated"]


async def test_fetch_past_end_has_clear_notice(runtime):
    _, plugin, _ = runtime
    result = await plugin.handle_fetch_page(url="https://example.com", start_char=500)
    data = json.loads(result["content"])
    assert data["content"] == ""
    assert "正文末尾" in data["notice"]
    assert data["next_start_char"] is None


@pytest.mark.parametrize("raw", [b"not json PRIVATE", b"[]", b"\xff"])
async def test_invalid_json_never_leaks_response(runtime, raw):
    _, plugin, state = runtime
    state.raw = raw
    result = await plugin.handle_search_and_summarize(query="x")
    assert not result["success"]
    assert result["error_code"] == "invalid_response"
    assert "PRIVATE" not in result["content"]


async def test_response_size_is_bounded(runtime):
    module, plugin, state = runtime
    state.raw = b'{"results":[],"extra":"' + b"x" * 1000 + b'"}'
    with patch.object(module, "MAX_RESPONSE_BYTES", 100):
        result = await plugin.handle_search_and_summarize(query="x")
    assert result["error_code"] == "response_too_large"


async def test_debug_logs_do_not_contain_key_prompt_or_page(runtime):
    _, plugin, state = runtime
    plugin.config.debug.log_request_summary = True
    state.fetch = {"title": "PRIVATE_TITLE", "content": "PRIVATE_BODY"}
    await plugin.handle_fetch_page(url="https://example.com/PRIVATE_URL")
    logged = repr(plugin.ctx.logger.info.call_args_list)
    assert "req_test" in logged
    assert "PRIVATE" not in logged
    assert "test-placeholder" not in logged


@pytest.mark.parametrize("section", ["plugin", "search", "fetch"])
async def test_disabled_features_do_not_request(runtime, section):
    _, plugin, state = runtime
    getattr(plugin.config, section).enabled = False
    if section == "fetch":
        result = await plugin.handle_fetch_page(url="https://example.com")
    else:
        result = await plugin.handle_search_and_summarize(query="x")
    assert not result["success"] and not state.requests


async def test_status_does_not_perform_paid_request_or_expose_key(runtime):
    _, plugin, state = runtime
    ok, message, _ = await plugin.handle_status(stream_id="chat")
    assert ok and "尚未验证" in message
    assert "test-placeholder" not in message
    assert not state.requests


@pytest.mark.parametrize("mode", ["http_error", "empty", "invalid", "success"])
async def test_search_command_reports_actual_result(runtime, mode):
    _, plugin, state = runtime
    if mode == "http_error":
        state.status = 401
    if mode == "empty":
        state.search = {"results": []}
    if mode == "invalid":
        state.search = {}
    ok, message, _ = await plugin.handle_search_test(stream_id="chat", text="/deepseek_web_search_test query")
    assert ok == (mode == "success")
    assert ("测试成功" in message) == (mode == "success")
    assert json.loads(state.requests[0].content)["count"] == 1


async def test_test_commands_can_be_disabled(runtime):
    _, plugin, state = runtime
    plugin.config.debug.enable_test_commands = False
    assert not (await plugin.handle_status())[0]
    assert not (await plugin.handle_search_test())[0]
    assert not state.requests


async def test_total_timeout_stops_request_and_releases_slot(runtime):
    _, plugin, state = runtime
    plugin.config.runtime.request_timeout_seconds = 1
    gate = asyncio.Event()

    async def blocked(request):
        await gate.wait()

    state.callback = blocked
    started = time.monotonic()
    result = await plugin.handle_search_and_summarize(query="x")
    assert result["error_code"] == "timeout"
    assert time.monotonic() - started < 3
    assert plugin._active_requests == 0
    assert not plugin._requests
    assert len(state.requests) == 1


async def test_queue_and_rate_wait_are_included_in_deadline(runtime):
    module, plugin, state = runtime
    plugin.config.runtime.max_concurrent_requests = 1
    async with plugin._request_slot():
        with pytest.raises(module.DeepSeekRequestError) as error:
            await plugin._execute_request("search", {"query": "x"}, "test-placeholder", 0.02)
        assert error.value.code == "timeout"
        assert not state.requests
    plugin.config.runtime.requests_per_second = 1
    plugin._rate_times["search"].append(time.monotonic())
    with pytest.raises(module.DeepSeekRequestError) as error:
        await plugin._execute_request("search", {"query": "x"}, "test-placeholder", 0.02)
    assert error.value.code == "timeout"
    assert not state.requests


async def test_endpoint_rate_limits_are_independent(runtime):
    _, plugin, _ = runtime
    plugin.config.runtime.requests_per_second = 1
    await plugin._pace("search")
    # A full Search window must not block the independent Fetch window.
    await asyncio.wait_for(plugin._pace("fetch"), 0.1)


@pytest.mark.parametrize("scopes,coalesce,expected", [
    (("a", "a"), True, 1), (("a", "b"), True, 2), (("", ""), True, 2), (("a", "a"), False, 2),
])
async def test_same_chat_inflight_coalescing_and_no_completed_cache(runtime, scopes, coalesce, expected):
    _, plugin, state = runtime
    plugin.config.runtime.coalesce_requests = coalesce
    gate = asyncio.Event()

    async def blocked(request):
        await gate.wait()

    state.callback = blocked
    calls = [asyncio.create_task(plugin._call_api("search", {"query": "same"}, request_scope=scope)) for scope in scopes]
    await until(lambda: len(state.requests) == expected)
    if expected == 1:
        await until(lambda: bool(plugin._inflight) and next(iter(plugin._inflight.values())).waiters == 2)
    gate.set()
    first, second = await asyncio.gather(*calls)
    first["results"].clear()
    assert second["results"]
    assert len(state.requests) == expected
    assert not plugin._inflight
    await plugin._call_api("search", {"query": "same"}, request_scope=scopes[0])
    assert len(state.requests) == expected + 1


async def test_cancel_one_waiter_does_not_cancel_other(runtime):
    _, plugin, state = runtime
    gate = asyncio.Event()

    async def blocked(request):
        await gate.wait()

    state.callback = blocked
    first = asyncio.create_task(plugin._call_api("search", {"query": "same"}, request_scope="chat"))
    second = asyncio.create_task(plugin._call_api("search", {"query": "same"}, request_scope="chat"))
    await until(lambda: bool(plugin._inflight) and next(iter(plugin._inflight.values())).waiters == 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    gate.set()
    assert (await second)["results"]
    assert len(state.requests) == 1


async def test_concurrent_fetch_slices_share_request_but_not_results(runtime):
    _, plugin, state = runtime
    gate = asyncio.Event()
    state.fetch = {"title": "Page", "content": "ABCDEF"}

    async def blocked(request):
        await gate.wait()

    state.callback = blocked
    first = asyncio.create_task(plugin.handle_fetch_page(url="https://example.com", start_char=0, stream_id="chat"))
    second = asyncio.create_task(plugin.handle_fetch_page(url="https://example.com", start_char=3, stream_id="chat"))
    await until(lambda: bool(plugin._inflight) and next(iter(plugin._inflight.values())).waiters == 2)
    gate.set()
    one, two = await asyncio.gather(first, second)
    assert len(state.requests) == 1
    assert json.loads(one["content"])["content"] == "ABCDEF"
    assert json.loads(two["content"])["content"] == "DEF"


async def test_rotated_key_does_not_join_old_inflight_request(runtime):
    _, plugin, state = runtime
    gate = asyncio.Event()

    async def blocked(request):
        if request.headers["authorization"] == "Bearer test-placeholder":
            await gate.wait()

    state.callback = blocked
    first = asyncio.create_task(plugin._call_api("search", {"query": "same"}, request_scope="chat"))
    await until(lambda: len(state.requests) == 1)
    write_model_config(state.config_path, "new-placeholder")
    second = await plugin._call_api("search", {"query": "same"}, request_scope="chat")
    assert second["results"]
    assert state.requests[1].headers["authorization"] == "Bearer new-placeholder"
    gate.set()
    assert (await first)["results"]
    state.client_factory.assert_called_once()


async def test_last_cancelled_waiter_cleans_upstream(runtime):
    _, plugin, state = runtime
    gate = asyncio.Event()

    async def blocked(request):
        await gate.wait()

    state.callback = blocked
    call = asyncio.create_task(plugin._call_api("search", {"query": "same"}, request_scope="chat"))
    await until(lambda: len(state.requests) == 1)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert not plugin._requests and not plugin._inflight and plugin._active_requests == 0


async def test_concurrency_limit_and_hot_config_wakeup(runtime):
    _, plugin, state = runtime
    plugin.config.runtime.max_concurrent_requests = 1
    async with plugin._request_slot():
        queued = asyncio.create_task(plugin._call_api("search", {"query": "same"}))
        await until(lambda: len(plugin._requests) == 1)
        assert not state.requests
        plugin.config.runtime.max_concurrent_requests = 2
        await plugin.on_config_update("self", {}, "version")
        assert (await asyncio.wait_for(queued, 2))["results"]
    assert plugin._active_requests == 0


async def test_queue_has_hard_bound(runtime):
    module, plugin, _ = runtime
    plugin.config.runtime.max_concurrent_requests = 1
    with patch.object(module, "MAX_PENDING_REQUESTS", 1):
        async with plugin._request_slot():
            first = asyncio.create_task(plugin._call_api("search", {"query": "one"}))
            await until(lambda: len(plugin._requests) == 1)
            with pytest.raises(module.DeepSeekRequestError) as error:
                await plugin._call_api("search", {"query": "two"})
            assert error.value.code == "busy"
        await first


async def test_unload_cancels_pending_and_closes_pool(runtime):
    module, plugin, state = runtime
    gate = asyncio.Event()

    async def blocked(request):
        await gate.wait()

    state.callback = blocked
    call = asyncio.create_task(plugin._call_api("search", {"query": "x"}))
    await until(lambda: len(state.requests) == 1)
    client = plugin._client
    await plugin.on_unload()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert client.is_closed
    assert not plugin._requests and not plugin._inflight
    with pytest.raises(module.DeepSeekRequestError):
        await plugin._call_api("search", {"query": "after unload"})


async def test_network_errors_are_safe(runtime):
    _, plugin, state = runtime

    async def failed(request):
        raise httpx.ConnectError("PRIVATE_NETWORK_ERROR", request=request)

    state.callback = failed
    result = await plugin.handle_fetch_page(url="https://example.com")
    assert result["error_code"] == "connection"
    assert "PRIVATE" not in result["content"]
