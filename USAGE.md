# DeepSeek Anthropic Provider 使用教程

本文介绍如何在 MaiBot 中使用 `deepseek-anthropic-provider` 插件。

## 这个插件做什么

这个插件把 DeepSeek Anthropic API 包装为三个 MaiBot Tool。Bot 自己的模型在对话中按需调用这些工具获得 DeepSeek 的能力。

**插件本身不替代 Bot 的大脑**——Bot 仍然用自己的模型跑对话，Tool 只是一个"能力外挂"，类似于你把 DeepSeek API 接入 Claude Code 用的那种体验。

### 三个 Tool

| Tool | 做什么 | 典型使用场景 |
|------|--------|-------------|
| `search_and_summarize` | DeepSeek 联网搜索网页并总结 | Bot 说"帮我查一下xxx"时自动触发 |
| `fetch_page` | DeepSeek 读取指定网页内容 | Bot 需要查看某篇文章或文档时触发 |
| `deepseek_proxy` | 把 prompt 直接交给 DeepSeek 自由处理 | 复杂推理、长文分析等场景 |

**关键设计**：每个 Tool 背后插件不写爬虫、不调 requests、不 parse HTML。它只是管道——把 Bot 的参数发给 DeepSeek Anthropic API，DeepSeek 自己搞定搜索/读取/总结，插件把结果还给 Bot。

## 安装位置

插件应放在 MaiBot 仓库的：

```text
plugins/deepseek-anthropic-provider/
```

这个目录应作为独立插件仓库维护。不要修改 MaiBot 根目录 `.gitignore`。

## 安装依赖

优先使用 `uv`：

```powershell
cd plugins/deepseek-anthropic-provider
uv sync
```

插件依赖：
- `anthropic>=0.104.0,<1.0.0`
- `maibot-plugin-sdk>=2.0.0,<3.0.0`

## 配置 DeepSeek API Key

插件读取密钥的优先级是：

1. 插件 WebUI 的"DeepSeek API 密钥"
2. 环境变量，默认名为 `DEEPSEEK_API_KEY`

推荐使用环境变量：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

如果要长期生效，请用系统环境变量或你的启动脚本配置。

## WebUI 配置解释

### 基础设置

- 启用插件：关闭后所有 Tool 和命令均不可用。

### 密钥设置

- DeepSeek API 密钥：可留空，留空时读取环境变量。
- 环境变量名：默认 `DEEPSEEK_API_KEY`。

接口地址固定为 `https://api.deepseek.com/anthropic`，不在 WebUI 中提供修改项。

### 模型设置

- 模型：选择调用 DeepSeek 时使用的模型（V4 Pro / V4 Flash）。
- 最大输出长度：单次调用允许 DeepSeek 输出的最大长度，默认 `4096`。

默认使用 V4 Flash，适合日常使用并控制成本。

深度思考或长总结没有最终回答，并提示输出达到最大长度时，可以适当调高“最大输出长度”。数值越大，潜在输出费用越高。

### 思考设置

- 思考模式：选择开启思考或关闭思考。
- 思考深度：开启思考时可选择标准思考 `high` 或深度思考 `max`。

开启思考时，插件会向 DeepSeek Anthropic API 传递 `thinking.type = enabled` 和对应的 `output_config.effort`；关闭思考时只传递 `thinking.type = disabled`。

### 联网搜索

- 允许联网搜索：关闭后 `search_and_summarize` 和 `fetch_page` 不可用，`deepseek_proxy` 也不会获得搜索工具。
- 搜索工具版本：默认 `web_search_20260209`，也可切到 `web_search_20250305` 做兼容测试。
- 每轮最多搜索次数：插件传给 DeepSeek 的 server tool `max_uses`，默认 5。
- 搜索积极程度：控制通用代理在什么情况下使用搜索，可选择更积极、按需搜索、仅显式请求。

搜索积极程度只影响插件内部 DeepSeek 使用 server web search 的倾向，不能决定 MaiBot 主模型是否调用本插件。搜索和网页读取工具被调用时会直接联网，不受积极程度限制。

插件不会自动回退搜索工具版本。不同 DeepSeek 账号支持情况可能不同，首次安装或切换版本后请运行搜索测试命令。

所有携带 Web Search server tool 的请求都会自动注入 MaiBot 服务器当前的具体时间、时区名称和 UTC 偏移。DeepSeek 会以此处理“今天”“最新”“近期”“今年”等相对时间，并核对搜索结果发布日期。该行为始终开启，不影响无搜索工具的纯推理请求和连接测试。

### 调试与日志

- 记录搜索来源：记录 citations 到日志。
- 记录原始响应摘要：排查问题时再开启。
- 启用测试命令：控制下面两个命令是否可用。

## 推荐组合

- 默认均衡：V4 Flash + 开启思考 + 标准思考 + 按需搜索
- 复杂分析：V4 Pro + 开启思考 + 深度思考 + 更积极
- 最低成本：V4 Flash + 关闭思考 + 仅显式请求

## 测试命令

连接测试：

```text
/deepseek_anthropic_ping
```

搜索测试：

```text
/deepseek_anthropic_search_test DeepSeek V4 最新说明
```

真实 API 集成测试默认跳过，不会产生费用。开发者确实需要运行时，必须同时设置：

```powershell
$env:RUN_DEEPSEEK_INTEGRATION="1"
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
uv run pytest -m integration
```

## 常见问题

### 缺少 DeepSeek API 密钥

检查插件 WebUI 密钥或 `DEEPSEEK_API_KEY` 环境变量。

### 缺少 anthropic 依赖

在插件目录运行 `uv sync`。

### Bot 不调用工具

这取决于 Bot 使用的模型本身是否支持 function calling / tool use。如果支持，Bot 会自行判断何时调用哪个 Tool。插件只是把 Tool 注册给 MaiBot 运行时。

### 图片或文档请求失败

DeepSeek Anthropic 兼容接口不支持直接传图片或文档。插件只传文本 prompt。

### 搜索没有发生

用 `/deepseek_anthropic_search_test 关键词` 验证连通性和搜索工具版本。

同时确认 WebUI 中的“允许联网搜索”已经开启。通用代理是否主动搜索还会受到“搜索积极程度”的影响。

### 搜索工具提示达到使用上限或暂时不可用

`max_uses_exceeded` 表示本轮达到“每轮最多搜索次数”；可以调高该配置后重试。`unavailable` 表示搜索服务或当前账号暂时不可用，请稍后重试，并用搜索测试命令核对当前工具版本。

### 输出达到最大长度

在 WebUI 的“模型设置”中调高“最大输出长度”。建议逐步增加，并留意费用。

### API 调用失败但聊天里没有完整异常

这是预期行为。插件只向聊天用户返回认证失败、余额不足、参数错误、限流、服务繁忙、连接失败或超时等通俗提示；完整异常只写入插件日志。

### 网页读取能力边界

`fetch_page` 只接受有效的 HTTP/HTTPS URL，并通过 DeepSeek Web Search server tool 读取。它不是通用爬虫，无法保证读取需要登录、反爬限制严格、非公开或当前账号搜索能力不支持的页面。
