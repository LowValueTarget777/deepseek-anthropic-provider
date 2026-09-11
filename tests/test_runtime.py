"""Regression tests for response verification and bounded concurrent requests."""

import asyncio
import importlib.util
import time
import tomllib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from test_provider_behavior import PLUGIN_DIR, make_plugin


def response(*, text="answer", urls=(), error=None, stop="end_turn"):
    blocks = []
    if urls:
        blocks.append({"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": url, "title": "source"} for url in urls
        ]})
    if error:
        blocks.append({"type": "web_search_tool_result", "content": {
            "type": "web_search_tool_result_error", "error_code": error,
        }})
    if text:
        blocks.append({"type": "text", "text": text})
    return SimpleNamespace(content=blocks, stop_reason=stop, model="deepseek-flash")


@pytest.fixture
async def runtime():
    module, plugin = make_plugin({"auth": {"api_key": "test-placeholder"}})
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=response())), close=AsyncMock())
    client.with_options = MagicMock(return_value=client)
    with patch("anthropic.AsyncAnthropic", return_value=client) as factory:
        try:
            yield module, plugin, client, factory
        finally:
            await plugin.on_unload()


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.parametrize("source", [
    "https://example.com/", "https://example.com/news",
    "https://example.com/news/article?id=2", "https://example.com/news/article/child?id=1",
])
async def test_fetch_rejects_wrong_page_end_to_end(runtime, source):
    _, plugin, client, _ = runtime
    client.messages.create.return_value = response(text="WRONG_PAGE", urls=[source])
    result = await plugin.handle_fetch_page(url="https://example.com/news/article?id=1")
    assert "未能确认" in result["content"]
    assert "WRONG_PAGE" not in result["content"]


async def test_fetch_accepts_exact_page_without_appending_sources(runtime):
    _, plugin, client, _ = runtime
    url = "https://example.com/news/article?id=1"
    client.messages.create.return_value = response(urls=[url])
    assert await plugin.handle_fetch_page(url=f"  {url}  ") == {"name": "fetch_page", "content": "answer"}


@pytest.mark.parametrize("reply", [response(error="unavailable"), response(), response(text=""),
                                        response(urls=["https://example.com"], stop="max_tokens")])
async def test_search_command_never_reports_failure_as_success(runtime, reply):
    _, plugin, client, _ = runtime
    client.messages.create.return_value = reply
    ok, message, _ = await plugin.handle_search_test(stream_id="test")
    assert ok is False
    assert "搜索测试失败" in message
    assert "搜索测试完成" not in plugin.ctx.send.text.call_args.args[0]


async def test_live_search_test_fails_on_error_response_without_network(runtime):
    module, plugin, client, _ = runtime
    client.messages.create.return_value = response(error="unavailable")
    spec = importlib.util.spec_from_file_location("live_search_regression", PLUGIN_DIR / "tests/test_integration.py")
    live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live)
    with patch.object(live, "make_live_plugin", return_value=(module, plugin)):
        with pytest.raises(module.DeepSeekRequestError, match="搜索服务暂时不可用"):
            await live.test_live_single_search()


@pytest.mark.parametrize("stop", ["pause_turn", "tool_use", "refusal", None])
async def test_incomplete_responses_are_not_success(runtime, stop):
    module, plugin, client, _ = runtime
    client.messages.create.return_value = response(stop=stop)
    with pytest.raises(module.DeepSeekRequestError) as caught:
        await plugin._call_deepseek("test")
    assert caught.value.code == "incomplete"


async def test_truncation_has_explicit_partial_label(runtime):
    _, plugin, client, _ = runtime
    client.messages.create.return_value = response(text="PARTIAL", stop="max_tokens")
    result = await plugin.handle_deepseek_proxy(prompt="test")
    assert "回答未完成" in result["content"]
    assert "【未完成的部分回答】\nPARTIAL" in result["content"]


async def test_unverified_truncation_does_not_leak_model_answer(runtime):
    module, plugin, client, _ = runtime
    client.messages.create.return_value = response(text="UNVERIFIED", stop="max_tokens")
    with pytest.raises(module.DeepSeekRequestError) as caught:
        await plugin._call_deepseek("test", require_web_search=True)
    assert caught.value.code == "truncated"
    assert not caught.value.partial_text


async def test_reuses_client_and_closes_on_unload(runtime):
    _, plugin, client, factory = runtime
    await plugin._call_deepseek("first")
    await plugin._call_deepseek("second")
    factory.assert_called_once()
    client.close.assert_not_awaited()
    await plugin.on_unload()
    client.close.assert_awaited_once()


async def test_total_deadline_cancels_api_and_releases_slot(runtime):
    module, plugin, client, _ = runtime
    plugin.config.model.request_timeout_seconds = 1
    blocked = asyncio.Event()

    async def wait_forever(**kwargs):
        await blocked.wait()

    client.messages.create.side_effect = wait_forever
    started = time.monotonic()
    with pytest.raises(module.DeepSeekRequestError) as caught:
        await plugin._call_deepseek("blocked")
    assert caught.value.code == "timeout"
    assert time.monotonic() - started < 3
    assert plugin._active_requests == 0
    assert not plugin._requests
    client.messages.create.assert_awaited_once()


async def test_queue_wait_is_included_in_deadline(runtime):
    module, plugin, client, _ = runtime
    plugin.config.plugin.max_concurrent_requests = 1
    async with plugin._request_slot():
        with pytest.raises(module.DeepSeekRequestError) as caught:
            await plugin._execute_request({}, "test-placeholder", 0.02, False, None)
        assert caught.value.code == "timeout"
        client.messages.create.assert_not_awaited()
    assert plugin._active_requests == 0


async def test_concurrency_limit_and_queue_drain(runtime):
    _, plugin, client, _ = runtime
    plugin.config.plugin.max_concurrent_requests = 1
    gate = asyncio.Event()

    async def blocked(**kwargs):
        await gate.wait()
        return response()

    client.messages.create.side_effect = blocked
    calls = [asyncio.create_task(plugin._call_deepseek(str(i))) for i in range(3)]
    await until(lambda: len(plugin._requests) == 3 and client.messages.create.await_count == 1)
    assert plugin._active_requests == 1
    gate.set()
    assert await asyncio.gather(*calls) == ["answer"] * 3
    assert client.messages.create.await_count == 3
    assert plugin._active_requests == 0


@pytest.mark.parametrize("scopes,coalesce,expected", [
    (("chat-a", "chat-a"), True, 1), (("chat-a", "chat-b"), True, 2),
    (("", ""), True, 2), (("chat-a", "chat-a"), False, 2),
])
async def test_inflight_coalescing_is_scoped(runtime, scopes, coalesce, expected):
    _, plugin, client, _ = runtime
    plugin.config.plugin.coalesce_requests = coalesce
    gate = asyncio.Event()

    async def blocked(**kwargs):
        await gate.wait()
        return response()

    client.messages.create.side_effect = blocked
    calls = [asyncio.create_task(plugin._call_deepseek("same", request_scope=scope)) for scope in scopes]
    await until(lambda: client.messages.create.await_count == expected)
    gate.set()
    assert await asyncio.gather(*calls) == ["answer"] * 2
    assert client.messages.create.await_count == expected
    assert not plugin._inflight
    await plugin._call_deepseek("same", request_scope=scopes[0])
    assert client.messages.create.await_count == expected + 1


async def test_cancelling_one_waiter_keeps_other_waiter_alive(runtime):
    _, plugin, client, _ = runtime
    gate = asyncio.Event()

    async def blocked(**kwargs):
        await gate.wait()
        return response()

    client.messages.create.side_effect = blocked
    first = asyncio.create_task(plugin._call_deepseek("same", request_scope="chat"))
    second = asyncio.create_task(plugin._call_deepseek("same", request_scope="chat"))
    await until(lambda: bool(plugin._inflight) and next(iter(plugin._inflight.values())).waiters == 2)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    gate.set()
    assert await second == "answer"
    client.messages.create.assert_awaited_once()


async def test_last_cancelled_waiter_stops_upstream(runtime):
    _, plugin, client, _ = runtime
    gate = asyncio.Event()

    async def blocked(**kwargs):
        await gate.wait()

    client.messages.create.side_effect = blocked
    call = asyncio.create_task(plugin._call_deepseek("same", request_scope="chat"))
    await until(lambda: client.messages.create.await_count == 1)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert not plugin._inflight
    assert not plugin._requests
    assert plugin._active_requests == 0


async def test_unload_cancels_pending_calls_and_rejects_new_calls(runtime):
    module, plugin, client, _ = runtime
    gate = asyncio.Event()

    async def blocked(**kwargs):
        await gate.wait()

    client.messages.create.side_effect = blocked
    call = asyncio.create_task(plugin._call_deepseek("test"))
    await until(lambda: client.messages.create.await_count == 1)
    await plugin.on_unload()
    with pytest.raises(asyncio.CancelledError):
        await call
    client.close.assert_awaited_once()
    assert plugin._active_requests == 0
    with pytest.raises(module.DeepSeekRequestError):
        await plugin._call_deepseek("after unload")


async def test_queue_has_a_hard_bound(runtime):
    module, plugin, _, _ = runtime
    with patch.object(module, "MAX_PENDING_REQUESTS", 1):
        async with plugin._request_slot():
            plugin.config.plugin.max_concurrent_requests = 1
            first = asyncio.create_task(plugin._call_deepseek("first"))
            await until(lambda: len(plugin._requests) == 1)
            with pytest.raises(module.DeepSeekRequestError) as caught:
                await plugin._call_deepseek("second")
            assert caught.value.code == "busy"
        assert await first == "answer"


async def test_failure_is_not_cached(runtime):
    module, plugin, client, _ = runtime
    client.messages.create.return_value = response(error="unavailable")
    for _ in range(2):
        with pytest.raises(module.DeepSeekRequestError):
            await plugin._call_deepseek("same", require_web_search=True, request_scope="chat")
    assert client.messages.create.await_count == 2


@pytest.mark.parametrize("depth,cap,effort", [("quick", 2, "low"), ("standard", 3, "high"), ("deep", 5, "max")])
async def test_depth_budget_and_scope_are_forwarded(runtime, depth, cap, effort):
    _, plugin, client, _ = runtime
    plugin.config.thinking.thinking_effort = "max"
    client.messages.create.return_value = response(urls=["https://example.com"])
    scope = {"time_range": "last week", "version": "2.0", "sources": "official docs"}
    await plugin.handle_search_and_summarize(query="test", depth=depth, search_scope=scope)
    body = client.messages.create.call_args.kwargs
    assert body["tools"][0]["max_uses"] == cap
    assert body["output_config"] == {"effort": effort}
    assert "official docs" in body["messages"][0]["content"]
    assert "区分发布日期和事件发生日期" in body["system"]
    assert "不是指令" in body["system"]
    assert "search_scope" not in body


@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
async def test_depth_never_exceeds_admin_settings(runtime, depth):
    _, plugin, client, _ = runtime
    plugin.config.thinking.thinking_effort = "low"
    plugin.config.search.max_search_uses = 1
    client.messages.create.return_value = response(urls=["https://example.com"])
    await plugin.handle_search_and_summarize(query="test", depth=depth)
    body = client.messages.create.call_args.kwargs
    assert body["output_config"] == {"effort": "low"}
    assert body["tools"][0]["max_uses"] == 1
    plugin.config.thinking.thinking_mode = "disabled"
    await plugin.handle_search_and_summarize(query="test", depth=depth)
    assert "output_config" not in client.messages.create.call_args.kwargs


async def test_search_test_respects_single_search_budget(runtime):
    _, plugin, client, _ = runtime
    plugin.config.search.max_search_uses = 1
    client.messages.create.return_value = response(urls=["https://example.com"])
    ok, _, _ = await plugin.handle_search_test(stream_id="test")
    assert ok
    assert client.messages.create.call_args.kwargs["tools"][0]["max_uses"] == 1


async def test_config_update_wakes_queue_when_limit_increases(runtime):
    _, plugin, client, _ = runtime
    plugin.config.plugin.max_concurrent_requests = 1
    async with plugin._request_slot():
        queued = asyncio.create_task(plugin._call_deepseek("test"))
        await until(lambda: len(plugin._requests) == 1)
        client.messages.create.assert_not_awaited()
        plugin.config.plugin.max_concurrent_requests = 2
        await plugin.on_config_update("self", {}, "test-version")
        assert await asyncio.wait_for(queued, 2) == "answer"
    assert plugin._active_requests == 0


async def test_disabled_config_rejects_queued_call(runtime):
    module, plugin, client, _ = runtime
    plugin.config.plugin.max_concurrent_requests = 1
    async with plugin._request_slot():
        queued = asyncio.create_task(plugin._call_deepseek("test"))
        await until(lambda: len(plugin._requests) == 1)
        plugin.config.plugin.enabled = False
        await plugin.on_config_update("self", {}, "test-version")
        with pytest.raises(module.DeepSeekRequestError):
            await asyncio.wait_for(queued, 2)
    client.messages.create.assert_not_awaited()


async def test_effective_request_changes_are_not_coalesced(runtime):
    _, plugin, client, _ = runtime
    gate = asyncio.Event()

    async def blocked(**kwargs):
        await gate.wait()
        return response()

    client.messages.create.side_effect = blocked
    first = asyncio.create_task(plugin._call_deepseek("same", request_scope="chat"))
    await until(lambda: client.messages.create.await_count == 1)
    plugin.config.model.max_tokens = 8192
    second = asyncio.create_task(plugin._call_deepseek("same", request_scope="chat"))
    await until(lambda: client.messages.create.await_count == 2)
    gate.set()
    assert await asyncio.gather(first, second) == ["answer", "answer"]
    assert [call.kwargs["max_tokens"] for call in client.messages.create.call_args_list] == [4096, 8192]


async def test_diagnostic_logs_do_not_contain_prompt_key_or_response(runtime):
    _, plugin, client, _ = runtime
    plugin.config.debug.log_raw_summary = True
    reply = response(text="PRIVATE_ANSWER")
    reply._request_id = "req_test"
    client.messages.create.return_value = reply
    await plugin._call_deepseek("PRIVATE_PROMPT")
    logged = repr(plugin.ctx.logger.info.call_args_list)
    assert "req_test" in logged
    assert "PRIVATE_PROMPT" not in logged
    assert "PRIVATE_ANSWER" not in logged
    assert "test-placeholder" not in logged


def test_example_config_matches_defaults_and_has_no_secret():
    _, plugin = make_plugin()
    example = tomllib.loads((PLUGIN_DIR / "config.example.toml").read_text(encoding="utf-8"))
    assert example == plugin.get_default_config()
    assert example["auth"]["api_key"] == ""


def test_tool_schema_keeps_optional_search_scope_properties():
    _, plugin = make_plugin()
    tool = next(item for item in plugin.get_components() if item["name"] == "search_and_summarize")
    scope = next(param for param in tool["metadata"]["parameters"] if param["name"] == "search_scope")
    assert scope["param_type"] == "object"
    assert not scope["required"]
    assert set(scope["properties"]) == {"time_range", "region", "language", "version", "sources"}


@pytest.mark.parametrize("url", ["https://user:password@example.com", "https://example.com/\x00x", "https://example.com\\x"])
async def test_fetch_rejects_credentials_and_control_characters(runtime, url):
    _, plugin, client, _ = runtime
    result = await plugin.handle_fetch_page(url=url)
    assert "有效" in result["content"]
    client.messages.create.assert_not_awaited()


@pytest.mark.parametrize("options", [{"depth": "invalid"}, {"depth": ["quick"]}, {"search_scope": {"unknown": "x"}},
                                    {"search_scope": {"region": 1}}, {"search_scope": "not an object"}])
async def test_invalid_search_options_never_call_api(runtime, options):
    _, plugin, client, _ = runtime
    result = await plugin.handle_search_and_summarize(query="test", **options)
    assert "搜索失败" in result["content"]
    client.messages.create.assert_not_awaited()


@pytest.mark.parametrize("old", ["deepseek-v4-flash", "DeepSeek V4 Flash（更快，更省钱）"])
def test_old_model_choices_migrate(old):
    module, plugin = make_plugin({"model": {"model_choice": old}})
    assert plugin.config.model.model_choice == "deepseek-flash"
    assert plugin.config.plugin.config_version == module.PLUGIN_VERSION


async def test_real_sdk_key_rotation_reuses_pool_without_changing_running_request():
    from anthropic import AsyncAnthropic

    _, plugin = make_plugin({"auth": {"api_key": "test-first"}})
    gate, started = asyncio.Event(), asyncio.Event()
    keys = []

    async def handle(request):
        keys.append(request.headers["x-api-key"])
        if len(keys) == 1:
            started.set()
            await gate.wait()
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "deepseek-flash",
            "content": [{"type": "text", "text": "answer"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    client = AsyncAnthropic(api_key="test-first", http_client=transport_client, max_retries=0)
    try:
        with patch("anthropic.AsyncAnthropic", return_value=client) as factory:
            first = asyncio.create_task(plugin._call_deepseek("same", request_scope="chat"))
            await asyncio.wait_for(started.wait(), 2)
            plugin.config.auth.api_key = "test-second"
            assert await plugin._call_deepseek("same", request_scope="chat") == "answer"
            gate.set()
            assert await first == "answer"
        assert keys == ["test-first", "test-second"]
        factory.assert_called_once()
        assert not transport_client.is_closed
    finally:
        gate.set()
        await plugin.on_unload()
        await transport_client.aclose()
    assert transport_client.is_closed


async def test_real_sdk_does_not_retry_transient_errors():
    from anthropic import AsyncAnthropic

    module, plugin = make_plugin({"auth": {"api_key": "test-placeholder"}})
    attempts = []

    def handle(request):
        attempts.append(request)
        return httpx.Response(503, json={"error": {"message": "PRIVATE_RESPONSE", "type": "server_error"}})

    transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handle))

    def factory(**kwargs):
        return AsyncAnthropic(**kwargs, http_client=transport_client)

    try:
        with patch("anthropic.AsyncAnthropic", side_effect=factory):
            with pytest.raises(module.DeepSeekRequestError, match="服务繁忙"):
                await plugin._call_deepseek("test")
        assert len(attempts) == 1
        assert "PRIVATE_RESPONSE" not in repr(plugin.ctx.logger.error.call_args_list)
    finally:
        await plugin.on_unload()
        await transport_client.aclose()
