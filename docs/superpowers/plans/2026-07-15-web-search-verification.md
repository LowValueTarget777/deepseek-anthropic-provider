# Web Search Verification Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make required DeepSeek web searches succeed only when the response contains usable results, verify `fetch_page` results against its target URL, add a bounded request timeout, and remove misleading documentation.

**Architecture:** Keep the single request pipeline in `plugin.py`, but replace the boolean activity flag with explicit response evidence gathered from result blocks. `_call_deepseek` will accept an optional target URL and enforce search errors, usable results, and source relevance before returning model text.

**Tech Stack:** Python 3.11+, Anthropic SDK, MaiBot Plugin SDK, pytest, pytest-asyncio.

## Global Constraints

- Modify only `D:/code/maibot-plugin/MaiBot/plugins/deepseek-anthropic-provider/`.
- Do not add crawlers, `requests`, HTML parsing, `web_fetch`, `@LLMProvider`, or `@Action`.
- Keep search sources in logs rather than appending them to chat responses.
- Use a fixed Anthropic timeout of 120 seconds without adding WebUI configuration.
- Do not run real API tests unless `RUN_DEEPSEEK_INTEGRATION=1` and `DEEPSEEK_API_KEY` are explicitly set.

---

### Task 1: Required Search Result Semantics

**Files:**
- Modify: `tests/test_provider_behavior.py`
- Modify: `plugin.py`

**Interfaces:**
- Consumes: Anthropic response blocks normalized by `_block_to_dict()` and `_as_block_list()`.
- Produces: `_extract_search_result_urls(block: dict[str, Any]) -> list[str]` and strict `require_web_search` handling in `_call_deepseek()`.

- [ ] **Step 1: Write failing tests for error and empty result blocks**

Add tests where `require_web_search=True` receives a `web_search_tool_result_error` plus model text, and where it receives an empty result list plus model text. Assert the first returns the mapped search error and the second returns `REQUIRED_WEB_SEARCH_NOT_USED_MESSAGE`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
uv run pytest -q tests/test_provider_behavior.py -k "required_search and (error or empty)"
```

Expected: both tests fail because any `web_search_tool_result` currently satisfies the requirement.

- [ ] **Step 3: Implement usable-result extraction and validation order**

Add `_extract_search_result_urls()` that returns only valid HTTP/HTTPS URLs from non-error result content. In `_call_deepseek`, collect these URLs, then enforce this order before returning text:

```python
if require_web_search and search_errors:
    return f"联网搜索失败：{_search_error_message(search_errors[0])}"
if require_web_search and not search_result_urls:
    return REQUIRED_WEB_SEARCH_NOT_USED_MESSAGE
```

Do not treat `server_tool_use` alone as successful search completion.

- [ ] **Step 4: Run focused and full behavior tests**

```powershell
uv run pytest -q tests/test_provider_behavior.py
```

Expected: all provider behavior tests pass.

---

### Task 2: Target URL Verification

**Files:**
- Modify: `tests/test_provider_behavior.py`
- Modify: `plugin.py`

**Interfaces:**
- Consumes: `_call_deepseek(..., required_source_url: str | None = None)` and collected result URLs.
- Produces: `_is_related_web_url(source_url: str, target_url: str) -> bool` and `REQUIRED_SOURCE_URL_NOT_FOUND_MESSAGE`.

- [ ] **Step 1: Write failing URL relation and request-pipeline tests**

Cover same host/path, trailing slash, query/fragment differences, child paths, unrelated hosts, and deceptive host suffixes. Add a `_call_deepseek` test proving unrelated search results are rejected when `required_source_url` is set.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
uv run pytest -q tests/test_provider_behavior.py -k "related_web_url or required_source"
```

Expected: failure because the helper and argument do not exist.

- [ ] **Step 3: Implement normalized URL matching**

Normalize hostnames to lowercase, ignore default ports, trim trailing slashes, and ignore query/fragment. Require equal host and paths that are equal, root, or parent/child on a slash boundary. Add `required_source_url` to `_call_deepseek` and reject responses with no related result URL.

- [ ] **Step 4: Pass the target from `fetch_page`**

Update `handle_fetch_page`:

```python
result = await self._call_deepseek(
    user_prompt=user_prompt,
    system=system,
    tools=_build_web_search_tools(self.config),
    require_web_search=True,
    required_source_url=url,
)
```

- [ ] **Step 5: Run provider tests**

```powershell
uv run pytest -q tests/test_provider_behavior.py
```

Expected: all provider behavior tests pass.

---

### Task 3: Timeout And Search Diagnostics

**Files:**
- Modify: `tests/test_provider_behavior.py`
- Modify: `tests/test_integration.py`
- Modify: `plugin.py`

**Interfaces:**
- Consumes: `AsyncAnthropic` constructor and `_call_deepseek(require_web_search=True)`.
- Produces: `DEEPSEEK_REQUEST_TIMEOUT_SECONDS = 120` and reliable search diagnostics.

- [ ] **Step 1: Write failing timeout and command tests**

Assert `AsyncAnthropic` is constructed with `timeout=120`. Update the search command test to require `require_web_search=True`.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
uv run pytest -q tests/test_provider_behavior.py -k "timeout or search_test_command"
```

Expected: timeout assertion and required-search assertion fail.

- [ ] **Step 3: Add timeout and strict diagnostic behavior**

Construct the client as:

```python
client = AsyncAnthropic(
    api_key=api_key,
    base_url=base_url,
    timeout=DEEPSEEK_REQUEST_TIMEOUT_SECONDS,
)
```

Pass `require_web_search=True` in `handle_search_test` and `test_live_single_search`.

- [ ] **Step 4: Run unit tests**

```powershell
uv run pytest -q
```

Expected: unit tests pass; live integration tests remain skipped unless explicitly enabled.

---

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: actual plugin behavior and configuration names.
- Produces: accurate user documentation without nonexistent settings.

- [ ] **Step 1: Correct the long-response notice**

Remove `fetch_full_text` and replace “搜索/抓取” with “搜索或网页读取”. Preserve the `enable_overflow_return_all` recommendation without claiming a plugin-side full-text option.

- [ ] **Step 2: Run complete verification**

```powershell
uv run pytest -q
uv run python -m py_compile plugin.py
uvx ruff check plugin.py tests
uvx pip-audit
git diff --check
git diff --cached --check
```

Expected: 0 test failures, compilation success, no Ruff findings, no known dependency vulnerabilities, and no whitespace errors.

- [ ] **Step 3: Review the final diff**

Confirm no files outside the plugin directory changed, no real secrets are tracked, `config.toml` remains ignored/deleted from Git tracking, and staged plus unstaged README changes form one accurate document.
