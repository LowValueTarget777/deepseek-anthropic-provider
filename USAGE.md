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
- `maibot-plugin-sdk>=2.5.2,<3.0.0`（本版结构化 Tool 参数按此版本验证）

## 配置 DeepSeek API Key

插件读取密钥的优先级是：

1. 插件 WebUI 的"DeepSeek API 密钥"
2. 环境变量，默认名为 `DEEPSEEK_API_KEY`

推荐使用环境变量：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

如果要长期生效，请用系统环境变量或你的启动脚本配置。

仓库只提交 `config.example.toml` 作为参考，不提交本地运行用的 `config.toml`。本地 `config.toml` 可能包含真实密钥，应保留在本机并保持被 `.gitignore` 忽略。

## WebUI 配置解释

配置页顶部按分组显示为标签页，方便在基础设置、密钥设置、模型设置、思考设置、联网搜索和调试日志之间切换。

### 基础设置

- 启用插件：关闭后所有 Tool 和命令均不可用。
- 最大并发请求数：默认 4，其他请求排队，执行与排队请求总数最多 64。
- 合并重复请求：同一会话、同一工具、相同参数和有效配置的在途请求共用一次 API 调用；缺少会话标识时不合并。完成或失败后立即清除，不缓存答案。

### 密钥设置

- DeepSeek API 密钥：可留空，留空时读取环境变量。
- 环境变量名：默认 `DEEPSEEK_API_KEY`。

接口地址固定为 `https://api.deepseek.com/anthropic`，不在 WebUI 中提供修改项。

### 模型设置

- 模型：默认 `deepseek-flash`，保留 `deepseek-v4-pro` 旧入口。
- 最大输出长度：单次调用允许 DeepSeek 输出的最大长度，默认 `4096`。
- 请求总时限：默认 120 秒，包含排队、网络和响应等待。SDK 自动重试关闭，避免重复付费和等待时间失控。

旧 Flash 配置会自动迁移到 `deepseek-flash`。官方公告：北京时间 2026-09-14 12:00 后，Pro 入口也将路由到 V4.1 Flash。[模型说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

深度思考或长总结没有最终回答，并提示输出达到最大长度时，可以适当调高“最大输出长度”。数值越大，潜在输出费用越高。

### 思考设置

- 思考模式：选择开启思考或关闭思考。
- 思考深度：轻量 `low`、标准 `high`、深度 `max`。搜索档位不会超过此上限。

开启思考时，插件会向 DeepSeek Anthropic API 传递 `thinking.type = enabled` 和对应的 `output_config.effort`；关闭思考时只传递 `thinking.type = disabled`。

### 联网搜索

- 允许联网搜索：关闭后 `search_and_summarize` 和 `fetch_page` 不可用，`deepseek_proxy` 也不会获得搜索工具。
- 搜索工具版本：默认 `web_search_20260209`，也可切到 `web_search_20250305` 做兼容测试。
- 每轮最多搜索次数：插件传给 DeepSeek 的 server tool `max_uses`，默认 5。
- 默认搜索档位：快速 `quick` 最多 2 次、标准 `standard` 最多 3 次、深入 `deep` 使用配置的次数上限。默认标准；所有档位仍受全局上限约束。
- 搜索积极程度：控制通用代理在什么情况下使用搜索，可选择更积极、按需搜索、仅显式请求。

搜索积极程度只影响插件内部 DeepSeek 使用 server web search 的倾向，不能决定 MaiBot 主模型是否调用本插件。搜索和网页读取工具被调用时会直接联网，不受积极程度限制。

插件不会自动回退搜索工具版本。不同 DeepSeek 账号支持情况可能不同，首次安装或切换版本后请运行搜索测试命令。

所有携带 Web Search server tool 的请求都会在出队时生成服务器当前时间、时区名称和 UTC 偏移，追加到用户输入末尾。固定规则保持稳定前缀，DeepSeek 以时间信息处理相对日期。此行为不影响无搜索工具的纯推理请求和连接测试。

快速档位的思考上限为 `low`、标准为 `high`、深入为 `max`，再与管理员配置取较低值；关闭思考时任何档位都不会重新开启它。档位不改变最大输出长度，也不保证实际搜索次数或质量。

Bot 可传入以下可选参数，现有只传 `query` 的调用保持兼容：

```json
{
  "query": "某个库的迁移步骤",
  "depth": "standard",
  "search_scope": {
    "time_range": "最近一个月",
    "region": "中国",
    "language": "中文或英文",
    "version": "2.0",
    "sources": "官方文档与发布说明"
  }
}
```

每项范围值最多 500 字，只作为检索偏好传入提示词，不传入未确认兼容的 API 过滤参数。`fetch_page` 也支持 `depth`，但始终只能基于目标 URL 回答。

### 调试与日志

- 记录搜索来源：记录 citations 到日志。
- 记录原始响应摘要：记录模型、结束原因、token 数、请求标识、来源数量和包含排队的总耗时，不记录完整正文。
- 启用测试命令：控制下面两个命令是否可用。

## 推荐组合

- 默认均衡：Flash + 标准思考 + 标准搜索档位 + 按需搜索
- 复杂查证：Flash + 深度思考 + 深入搜索档位；按需要设置次数上限
- 成本优先：Flash + 轻量或关闭思考 + 快速搜索档位

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

本插件只接收文本和公开网页 URL，不发送图片或文档二进制；这是插件能力边界，不代表 DeepSeek 所有接口的能力。

### 搜索没有发生

用 `/deepseek_anthropic_search_test 关键词` 验证连通性和搜索工具版本。

同时确认 WebUI 中的“允许联网搜索”已经开启。通用代理是否主动搜索还会受到“搜索积极程度”的影响。

如果 `search_and_summarize` 或 `fetch_page` 提示没有有效网页搜索结果，说明本次响应没有完成搜索、搜索失败或没有命中任何网页。请重试，或检查当前 DeepSeek 账号、模型和搜索工具版本是否支持 server web search。

### 搜索工具提示达到使用上限或暂时不可用

`max_uses_exceeded` 表示本轮达到“每轮最多搜索次数”；可以调高该配置后重试。`unavailable` 表示搜索服务或当前账号暂时不可用，请稍后重试，并用搜索测试命令核对当前工具版本。

### 输出达到最大长度

在 WebUI 的“模型设置”中调高“最大输出长度”。建议逐步增加，并留意费用。

### API 调用失败但聊天里没有完整异常

这是预期行为。插件只向聊天用户返回通俗中文错误，日志记录异常类型和状态码，不输出原始异常响应。输出截断也算失败；仅在来源核验通过时附上明确标注的部分回答。测试命令与集成测试不会将这些错误判为成功。

### 网页读取能力边界

`fetch_page` 只接受有效的 HTTP/HTTPS URL，并通过 DeepSeek Web Search server tool 读取。它不是通用爬虫，无法保证读取需要登录、反爬限制严格、非公开或当前账号搜索能力不支持的页面。

`fetch_page` 要求有效搜索结果中的来源与目标 URL 一致，仅允许主机大小写、默认端口、空路径的规范化差异。路径、查询字符串、片段均保留；不会将站点首页、其他文章参数或父子页面视作目标，也不会推测跳转关系。严格核验可能拒绝重定向或锚点不同的链接；可提供最终公开 URL 后再试。

URL 命中并不等于获得全文。仅有搜索片段时，提示词要求明确说明限制。搜索失败、空结果或来源不符时不会返回模型补写文本。

## 性能与评测

客户端复用连接池，密钥或超时变更使用独立 SDK 请求配置，不改变已在执行的请求。卸载会取消未完成调用并关闭连接；一个合并请求的等待者取消，不影响其他等待者，全部取消后停止上游等待。取消本地请求不保证 DeepSeek 停止服务端计算或不计费。

本版不缓存完成的答案，也不新增爬虫、外部搜索引擎或 `web_fetch`。不同搜索版本仍需真实兼容性验收，优化效果需按[固定评测方法](./docs/search-evaluation.md)验证，不能用单元测试通过率替代真实搜索质量。
