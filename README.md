# DeepSeek Anthropic Provider

把 DeepSeek 的 Anthropic 兼容接口接入 MaiBot，让 Bot 可以调用 DeepSeek 提供的联网搜索、网页读取和深度推理能力。

> **⚠️ 重要提示**
>
> **建议到「麦麦设置 → 后处理 → 高级设置」中把 `enable_overflow_return_all` 打开。**
>
> 本插件通过搜索或网页读取返回的内容可能较长。如果该开关未启用，MaiBot 的后处理管线会把超长内容截断并可能直接返回「不知道」，导致检索结果无法正常交给 AI 进行总结，用户侧看起来就是“搜到了但麦麦说不知道”。



## 插件信息

| 项目 | 内容 |
| --- | --- |
| 插件 ID | `LowValueTarget.deepseek-anthropic-provider` |
| 当前版本 | `0.2.5` |
| 插件类型 | Tool 插件 |
| 支持能力 | `tool`、`send.text` |
| 主要依赖 | `anthropic>=0.104.0,<1.0.0`、`maibot-plugin-sdk>=2.5.2,<3.0.0` |
| 默认接口 | `https://api.deepseek.com/anthropic` |

## 主要功能

| 工具 | 用途 |
| --- | --- |
| `search_and_summarize` | 联网搜索并总结结果，适合查询新闻、资料、版本变更、公开网页信息。 |
| `fetch_page` | 通过搜索检索指定公开网页并提取重点，不保证获取全文。 |
| `deepseek_proxy` | 将复杂问题交给 DeepSeek 处理，适合长推理、资料整理和补充分析。 |

## 适合场景

- 让 Bot 查询最新公开信息，而不是只依赖本地知识。
- 让 Bot 阅读用户发来的网页链接并总结重点。
- 在不改 MaiBot 主程序的前提下，为 Bot 增加 DeepSeek 推理能力。
- 需要保留 MaiBot 原有人格、记忆、上下文，只增强外部工具能力。

## 安装

### 通过插件市场安装

插件发布到 MaiBot 插件市场后，可以直接在插件市场中搜索并安装 `DeepSeek Anthropic Provider`。

### 手动安装

将插件放到 MaiBot 的 `plugins` 目录：

```text
plugins/deepseek-anthropic-provider/
```

进入插件目录安装依赖，推荐使用 `uv`：

```powershell
cd plugins/deepseek-anthropic-provider
uv sync
```

然后重启 MaiBot，或按当前运行方式重新加载插件。

仓库只提交 `config.example.toml` 作为示例，不提交本地运行用的 `config.toml`。MaiBot 首次加载或保存配置时会按配置模型生成本地配置；如果需要手动参考，请复制示例内容后填入自己的密钥或环境变量。

## 配置

插件支持通过 WebUI 配置，配置页顶部按分组显示为标签页。配置项都使用简体中文说明，常用设置包括：

| 分组 | 配置项 | 说明 |
| --- | --- | --- |
| 基础设置 | 启用插件 | 控制插件是否生效。 |
| 基础设置 | 最大并发请求数 | 默认 `4`，超出后排队；队列有容量上限。 |
| 基础设置 | 合并重复请求 | 默认开启，只合并同一会话中参数相同的在途请求，不缓存完成的答案。 |
| 密钥设置 | DeepSeek API 密钥 | 可以直接填写，也可以留空后使用环境变量。 |
| 密钥设置 | 环境变量名 | 默认读取 `DEEPSEEK_API_KEY`。 |
| 模型设置 | 模型选择 | 默认 `deepseek-flash`，保留 V4 Pro 旧入口。 |
| 模型设置 | 最大输出长度 | 默认 `4096`；深度思考或长总结被截断时可以调高。 |
| 模型设置 | 请求总时限 | 默认 `120` 秒，包含排队与 API 等待，关闭 SDK 自动重试。 |
| 思考设置 | 思考模式 | 控制是否开启 DeepSeek 思考能力。 |
| 思考设置 | 思考深度 | 可选择轻量 `low`、标准 `high` 或深度 `max`，也是搜索档位的思考上限。 |
| 联网搜索 | 允许联网搜索 | 关闭后搜索和网页读取工具不可用，通用代理也不会获得搜索工具。 |
| 联网搜索 | 搜索工具版本 | 选择请求的工具版本，兼容性需通过真实搜索测试确认。 |
| 联网搜索 | 每轮最多搜索次数 | 控制 DeepSeek 每轮最多调用几次网页搜索。 |
| 联网搜索 | 默认搜索档位 | 快速最多 2 次、标准最多 3 次、深入使用配置上限；均不能突破管理员预算。 |
| 联网搜索 | 搜索积极程度 | 控制通用 DeepSeek 代理在什么情况下使用搜索。 |
| 调试与日志 | 调试开关 | 用于记录搜索来源、响应摘要和测试信息。 |

密钥读取优先级：

1. 插件 WebUI 中填写的 DeepSeek API 密钥。
2. 环境变量 `DEEPSEEK_API_KEY`。

不要把真实 API 密钥提交到 Git 仓库或公开截图中。
推荐把 `api_key` 留空，并通过 `DEEPSEEK_API_KEY` 环境变量提供密钥。

搜索积极程度只影响插件内部 DeepSeek 使用 server web search 的倾向，不会控制 MaiBot 主模型是否调用本插件。

每次请求携带网页搜索工具时，插件会自动告诉 DeepSeek 服务器当前的具体时间、时区名称和 UTC 偏移。模型会以此判断“今天”“最新”“近期”“今年”等相对时间，并核对搜索结果发布日期；纯推理请求和连接测试不会注入时间。

时间在出队时生成，放在用户输入末尾以保留固定提示词前缀。客户端在插件实例中复用，密钥变更时新请求使用新密钥，卸载时取消未完成调用并关闭连接。没有会话标识的调用不进行重复请求合并。

`search_and_summarize` 新增可选参数 `depth` 和 `search_scope`（时间、地区、语言、版本、来源偏好），`fetch_page` 支持可选 `depth`。范围参数仅作为提示词偏好，不是搜索服务保证执行的硬过滤。检索提示词要求优先原始来源、区分新闻与事件日期、证据不足时再补搜，不盲目用满次数。

## 使用方式

正常聊天即可，不需要用户手动输入固定命令。只要 MaiBot 当前主模型支持工具调用，Bot 会在需要时自动调用插件。

可以这样向 Bot 提问：

```text
帮我查一下 DeepSeek 最近的模型更新，并总结重点。
```

```text
打开这个网页看看主要讲了什么：https://example.com
```

```text
这个问题交给 DeepSeek 深入分析一下：……
```

## 测试命令

插件提供调试命令，用于检查配置是否可用：

```text
/deepseek_anthropic_ping
```

检查 API 密钥、固定接口地址和当前模型是否可用。

```text
/deepseek_anthropic_search_test 关键词
```

检查当前联网搜索工具版本是否可用，并在日志中记录工具调用情况。

默认使用 `web_search_20260209`。不同 DeepSeek 账号支持情况可能不同，插件不会自动切换搜索工具版本，请在正式使用前运行一次搜索测试命令。

## 推荐设置

| 使用目标 | 推荐模型 | 思考模式 | 搜索积极程度 |
| --- | --- | --- | --- |
| 日常聊天增强 | DeepSeek Flash | 开启思考 | 按需搜索 |
| 查询最新资料 | DeepSeek Flash | 开启思考 | 更积极 |
| 复杂分析任务 | DeepSeek Flash | 开启思考 | 更积极 |
| 成本优先 | DeepSeek Flash | 关闭思考 | 仅显式请求 |

默认配置为 DeepSeek Flash、开启思考、标准思考、标准搜索档位、按需搜索。

旧配置的 `deepseek-v4-flash` 会迁移到 `deepseek-flash`。官方公告：北京时间 **2026-09-14 12:00** 后，`deepseek-v4-pro` 请求也将路由到 V4.1 Flash；模型名不保证对应独立的 Pro 能力。[官方模型说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

## 常见问题

### Bot 没有调用插件

请确认 MaiBot 当前主模型支持工具调用，并且插件已经启用。这个插件不会强制接管所有消息，只有主模型判断需要工具时才会调用。

### 提示没有 API 密钥

请在插件 WebUI 中填写 DeepSeek API 密钥，或设置环境变量 `DEEPSEEK_API_KEY`。

### 联网搜索不可用

请先运行 `/deepseek_anthropic_search_test 关键词`。如果仍然失败，可能是当前 DeepSeek 账号、模型或工具版本暂不支持对应的 Web Search server tool。

### 提示输出达到最大长度

在 WebUI 的“模型设置”中调高“最大输出长度”。数值越大，单次请求可能产生的输出费用也越高。

### 错误信息为什么没有原始 API 响应

插件会向聊天用户显示通俗中文错误，日志仅记录异常类型和状态码，不记录原始异常响应。搜索来源日志仍可能包含用户提供的 URL，请不要公开分享未经检查的日志。

### 网页读取支持哪些地址

`fetch_page` 只接受有效的 `http://` 或 `https://` 网页地址。它依赖 DeepSeek Web Search server tool，不是通用爬虫，无法保证读取需要登录、反爬限制严格或账号搜索能力不支持的网页。

如果 DeepSeek 没有返回有效搜索结果，插件会拒绝返回可能来自模型常识的网页摘要。来源校验仅规范化主机大小写、默认端口和空路径；保留路径、查询字符串及片段，不把首页、父子页面或不同文章参数视作目标页，也不推测重定向。

因此重定向、末尾斜杠或锚点不同也可能无法匹配。即使来源 URL 匹配，也只能确认有该页面的搜索结果，不能证明获得了全文。截断结果会明确标注未完成；没有可靠来源的部分文本不会返回。

### 搜索来源会发到聊天里吗

默认不会。搜索来源主要写入日志，避免在聊天回复末尾追加过长的引用内容。

### 会影响 MaiBot 的人格和记忆吗

不会。插件只负责工具调用和 DeepSeek 接口请求，MaiBot 的人格、记忆、聊天上下文仍由 MaiBot 主流程管理。

## 隐私与安全

调用插件时，相关问题、链接和上下文会被发送到 DeepSeek API。请不要让 Bot 处理不应发送给第三方服务的敏感信息。

插件不会内置或提交任何真实 API 密钥。发布前请再次确认 `config.toml`、`config.example.toml`、截图和日志中没有泄露密钥。

## 更多文档

- [完整使用教程](./USAGE.md)
- [版本变更记录](./CHANGELOG.md)
- [搜索评测方法](./docs/search-evaluation.md)
- [MaiBot Vibe Coding 指南](https://docs.mai-mai.org/plugin/vibe-coding)
- [DeepSeek Anthropic API 文档](https://api-docs.deepseek.com/zh-cn/guides/anthropic_api)
- [MaiBot 插件市场提交说明](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)
