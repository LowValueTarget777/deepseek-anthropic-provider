# Web Search Verification Design

## Goal

修复 DeepSeek Anthropic Provider 对 server web search 成功状态的误判，确保网页读取和搜索测试不会在未取得有效搜索结果时报告成功，并补齐请求超时和文档一致性。

## Scope

- 只修改当前插件目录内的实现、测试和文档。
- 继续使用 DeepSeek Anthropic server web search，不新增爬虫、`requests`、HTML 解析或 `web_fetch`。
- 不修改 MaiBot 主程序配置，不新增 `@LLMProvider` 或 `@Action`。
- 搜索来源继续只写日志，不追加到聊天回复。

## Search Result Semantics

响应解析需要区分四种状态：

1. 未调用：没有 `server_tool_use(name="web_search")`，也没有 `web_search_tool_result`。
2. 调用失败：`web_search_tool_result.content` 是 `web_search_tool_result_error`。
3. 成功但无结果：`web_search_tool_result.content` 是空列表。
4. 成功且有结果：`content` 至少包含一个带有效 HTTP/HTTPS URL 的搜索结果。

`require_web_search=True` 只接受“成功且有结果”。失败时优先返回对应的中文搜索错误；未调用或空结果时返回明确提示，不返回模型自行生成的文本。

## Target URL Verification

`fetch_page` 除了要求成功搜索，还必须确认至少一个搜索来源与目标 URL 相关：

- URL scheme 必须是 HTTP 或 HTTPS。
- 主机名大小写不敏感，并忽略默认端口。
- 来源主机必须与目标主机相同。
- 路径完全相同、一个路径是另一个路径的父路径，或目标/来源为站点根路径时视为相关，以容忍尾斜杠和常见规范化跳转。
- 查询参数和 fragment 不参与匹配，避免追踪参数导致误判。

如果搜索成功但只有无关来源，返回“未能确认读取目标网页”的中文提示。

## Request Timeout

Anthropic 客户端使用固定 120 秒总超时。该值不新增 WebUI 配置，避免扩大配置面；超时继续由现有 `APITimeoutError` 映射为中文提示。

## Commands And Integration Tests

- `/deepseek_anthropic_search_test` 必须传 `require_web_search=True`，没有有效结果时测试失败。
- 真实搜索集成测试同样传 `require_web_search=True`，从而验证账号、模型和工具版本确实完成搜索。
- 不自动运行真实集成测试，除非显式设置 `RUN_DEEPSEEK_INTEGRATION=1` 和 `DEEPSEEK_API_KEY`。

## Documentation

- 删除 README 中不存在的 `fetch_full_text` 配置项。
- 将“抓取”改为符合实际架构的“网页读取/搜索”。
- 保留 `enable_overflow_return_all` 的长内容提示，但不声称插件拥有未实现的全文抓取开关。

## Tests

新增或调整回归测试覆盖：

- 搜索错误块不能满足强制搜索要求。
- 空结果不能满足强制搜索要求。
- `fetch_page` 接受相关 URL 来源，拒绝无关来源。
- 搜索测试命令和真实集成测试启用强制搜索。
- `AsyncAnthropic` 获得 120 秒超时参数。
- 原有配置、思考参数、来源日志、错误映射和 Tool 返回格式保持不变。
