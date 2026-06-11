# DeepSeek Anthropic Provider

把 DeepSeek 的 Anthropic 兼容接口接入 MaiBot，让 Bot 可以按需调用联网搜索、网页读取和 DeepSeek 深度推理能力。

这个插件不是替换 MaiBot 的人格、记忆或聊天上下文，而是作为 MaiBot Tool 插件存在：主模型判断需要工具时，才会把问题交给本插件处理。

## 插件信息

| 项目 | 内容 |
| --- | --- |
| 插件 ID | `LowValueTarget.deepseek-anthropic-provider` |
| 当前版本 | `0.2.3` |
| 插件类型 | Tool 插件 |
| 支持能力 | `tool`、`send.text` |
| 主要依赖 | `anthropic>=0.104.0,<1.0.0`、`maibot-plugin-sdk>=2.0.0,<3.0.0` |
| 默认接口 | `https://api.deepseek.com/anthropic` |

## 主要功能

| 工具 | 用途 |
| --- | --- |
| `search_and_summarize` | 联网搜索并总结结果，适合查询新闻、资料、版本变更、公开网页信息。 |
| `fetch_page` | 读取指定网页并提取重点，适合让 Bot 总结链接内容。 |
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

## 配置

插件支持通过 WebUI 配置。配置项都使用简体中文说明，常用设置包括：

| 分组 | 配置项 | 说明 |
| --- | --- | --- |
| 基础设置 | 启用插件 | 控制插件是否生效。 |
| 密钥设置 | DeepSeek API 密钥 | 可以直接填写，也可以留空后使用环境变量。 |
| 密钥设置 | 环境变量名 | 默认读取 `DEEPSEEK_API_KEY`。 |
| 模型设置 | 模型选择 | 可选择 DeepSeek V4 Pro 或 DeepSeek V4 Flash。 |
| 模型设置 | 最大输出长度 | 默认 `4096`；深度思考或长总结被截断时可以调高。 |
| 思考设置 | 思考模式 | 控制是否开启 DeepSeek 思考能力。 |
| 思考设置 | 思考深度 | 可选择标准思考或深度思考。 |
| 联网搜索 | 允许联网搜索 | 关闭后搜索和网页读取工具不可用，通用代理也不会获得搜索工具。 |
| 联网搜索 | 搜索工具版本 | 可选择 DeepSeek 支持的 Web Search 工具版本。 |
| 联网搜索 | 每轮最多搜索次数 | 控制 DeepSeek 每轮最多调用几次网页搜索。 |
| 联网搜索 | 搜索积极程度 | 控制通用 DeepSeek 代理在什么情况下使用搜索。 |
| 调试与日志 | 调试开关 | 用于记录搜索来源、响应摘要和测试信息。 |

密钥读取优先级：

1. 插件 WebUI 中填写的 DeepSeek API 密钥。
2. 环境变量 `DEEPSEEK_API_KEY`。

不要把真实 API 密钥提交到 Git 仓库或公开截图中。

搜索积极程度只影响插件内部 DeepSeek 使用 server web search 的倾向，不会控制 MaiBot 主模型是否调用本插件。

每次请求携带网页搜索工具时，插件会自动告诉 DeepSeek 服务器当前的具体时间、时区名称和 UTC 偏移。模型会以此判断“今天”“最新”“近期”“今年”等相对时间，并核对搜索结果发布日期；纯推理请求和连接测试不会注入时间。

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
| 日常聊天增强 | DeepSeek V4 Flash | 开启思考 | 按需搜索 |
| 查询最新资料 | DeepSeek V4 Flash | 开启思考 | 更积极 |
| 复杂分析任务 | DeepSeek V4 Pro | 开启思考 | 更积极 |
| 成本优先 | DeepSeek V4 Flash | 关闭思考 | 仅显式请求 |

如果不确定怎么选，建议使用默认配置：DeepSeek V4 Flash、开启思考、标准思考、按需搜索。

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

插件会向聊天用户显示通俗中文错误，并把完整异常写入日志，避免把服务端响应、请求细节或敏感信息直接发到聊天中。

### 网页读取支持哪些地址

`fetch_page` 只接受有效的 `http://` 或 `https://` 网页地址。它依赖 DeepSeek Web Search server tool，不是通用爬虫，无法保证读取需要登录、反爬限制严格或账号搜索能力不支持的网页。

### 搜索来源会发到聊天里吗

默认不会。搜索来源主要写入日志，避免在聊天回复末尾追加过长的引用内容。

### 会影响 MaiBot 的人格和记忆吗

不会。插件只负责工具调用和 DeepSeek 接口请求，MaiBot 的人格、记忆、聊天上下文仍由 MaiBot 主流程管理。

## 隐私与安全

调用插件时，相关问题、链接和上下文会被发送到 DeepSeek API。请不要让 Bot 处理不应发送给第三方服务的敏感信息。

插件不会内置或提交任何真实 API 密钥。发布前请再次确认 `config.toml`、截图和日志中没有泄露密钥。

## 更多文档

- [完整使用教程](./USAGE.md)
- [版本变更记录](./CHANGELOG.md)
- [DeepSeek Anthropic API 文档](https://api-docs.deepseek.com/zh-cn/guides/anthropic_api)
- [MaiBot 插件市场提交说明](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)
