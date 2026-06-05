# DeepSeek Anthropic Provider 使用教程

本文介绍如何在 MaiBot 中使用 `deepseek-anthropic-provider` 插件。

## 这个插件做什么

这个插件把 MaiBot 的模型请求转成 DeepSeek Anthropic 兼容接口请求。MaiBot 原本负责的人格、记忆、聊天上下文、工具列表仍由 MaiBot 主流程构造，插件不会重新拼人格 prompt。

适合的用途：

- 让 replyer 使用 DeepSeek V4 的 Anthropic 接口。
- 让模型在回答时自动使用 DeepSeek 支持的网页搜索工具。
- 使用 DeepSeek V4 的思考模式和思考深度设置。

## 安装位置

插件应放在 MaiBot 仓库的：

```text
plugins/deepseek-anthropic-provider/
```

这个目录应作为独立插件仓库维护。不要修改 MaiBot 根目录 `.gitignore`，插件自己的忽略规则写在插件目录的 `.gitignore`。

## 安装依赖

优先使用 `uv`：

```powershell
cd D:\code\maibot-plugin\MaiBot\plugins\deepseek-anthropic-provider
uv sync
```

插件依赖也已经写入 `_manifest.json`，MaiBot 插件运行时可据此安装：

- `anthropic>=0.104.0,<1.0.0`
- `maibot-plugin-sdk>=2.0.0`

## 配置 DeepSeek API Key

插件读取密钥的优先级是：

1. 插件 WebUI 的“DeepSeek API 密钥”
2. 环境变量，默认名为 `DEEPSEEK_API_KEY`
3. MaiBot 模型供应商配置里的 `api_key`

推荐使用环境变量：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
```

如果要长期生效，请用系统环境变量或你的启动脚本配置。

## MaiBot 模型供应商示例

不要直接修改真实 `model_config.toml` 时误提交密钥。下面只是示例：

```toml
[[api_providers]]
name = "DeepSeek Anthropic"
base_url = "https://api.deepseek.com/anthropic"
api_key = "your-api-key-or-empty-when-using-env"
client_type = "deepseek.anthropic"
auth_type = "bearer"
timeout = 120
max_retry = 2
retry_interval = 5
```

模型示例：

```toml
[[models]]
model_identifier = "deepseek-v4-pro"
name = "deepseek-v4-pro-anthropic"
api_provider = "DeepSeek Anthropic"
price_in = 12.0
price_out = 24.0
visual = false

[[models]]
model_identifier = "deepseek-v4-flash"
name = "deepseek-v4-flash-anthropic"
api_provider = "DeepSeek Anthropic"
price_in = 1.0
price_out = 2.0
visual = false
```

replyer 示例：

```toml
[model_task_config.replyer]
model_list = ["deepseek-v4-pro-anthropic"]
max_tokens = 4096
temperature = 1.0
hard_timeout = 240.0
```

开启思考模式时，插件不会主动传 `temperature`、`top_p`、`presence_penalty`、`frequency_penalty`，因为 DeepSeek 思考模式文档说明这些采样参数不生效。

## WebUI 配置解释

### 基础设置

- 启用插件：关闭后 Provider 不处理模型请求。
- 配置版本：用于插件配置兼容，通常不用改。

### 密钥设置

- DeepSeek API 密钥：可留空，留空时读取环境变量。
- 环境变量名：默认 `DEEPSEEK_API_KEY`。
- 接口地址：默认 `https://api.deepseek.com/anthropic`。
- 密钥读取说明：给 WebUI 展示的说明文字，不参与运行逻辑。

### 模型设置

- DeepSeek V4 Pro（更聪明，成本更高）：默认选项，适合作为 replyer。
- DeepSeek V4 Flash（更快，更省钱）：适合 planner 或轻量任务。
- 跟随 MaiBot 模型配置（高级）：使用 MaiBot 当前模型的 `model_identifier`。

不提供 `deepseek-chat` 和 `deepseek-reasoner` 下拉选项，因为 DeepSeek 文档说明它们会在北京时间 2026-07-24 23:59 弃用。

### 思考设置

- 开启思考：模型会输出思考过程，回答更稳，但更慢。
- 关闭思考：回复更快、更省输出，适合轻量任务。
- 标准思考 high：默认深度。
- 深度思考 max：更深入，适合复杂问题。

### 联网搜索

- 允许模型联网搜索：开启后模型可以调用 DeepSeek Anthropic server web search。
- 搜索工具版本：默认 `web_search_20260209`，也可切到 `web_search_20250305` 做兼容测试。
- 每轮最多搜索次数：默认 5。
- 搜索积极程度：默认“更积极”，适合让 Bot 主动查最新信息。

搜索来源默认只写入日志和 `raw_data`，不会主动追加到聊天回复末尾。

### 调试与日志

- 记录搜索来源：记录 citations 和 server tool 使用情况。
- 记录原始响应摘要：排查问题时再开启。
- 启用测试命令：控制下面两个命令是否可用。

## 推荐组合

- 日常聊天更聪明：V4 Pro + 开启思考 + high + 搜索更积极。
- 成本更低：V4 Flash + 关闭思考 + 搜索按需。
- 复杂推理：V4 Pro + 开启思考 + max + 搜索更积极。

## 测试命令

连接测试：

```text
/deepseek_anthropic_ping
```

搜索测试：

```text
/deepseek_anthropic_search_test DeepSeek V4 最新说明
```

搜索测试会把 server tool 使用情况写入日志；聊天中只展示简短测试结果。

## 常见问题

### 缺少 DeepSeek API 密钥

检查插件 WebUI 密钥、`DEEPSEEK_API_KEY` 环境变量，或 MaiBot 模型供应商的 `api_key`。

### 缺少 anthropic 依赖

在插件目录运行：

```powershell
uv sync
```

### 模型没有保持人格

这个插件不会重写人格。如果人格丢失，优先检查 MaiBot 的 replyer/planner 模型配置是否真的走到了 `client_type = "deepseek.anthropic"`，以及上游请求快照里的 system prompt 是否完整。

### 图片或文档请求失败

DeepSeek Anthropic 兼容接口不支持直接传图片或文档内容块。请先让 MaiBot 或其他插件生成文本描述，再交给这个 Provider。

### 搜索没有发生

确认“允许模型联网搜索”已开启，并用 `/deepseek_anthropic_search_test 关键词` 验证。模型是否搜索仍由模型根据问题决定，默认“更积极”会更容易触发搜索。
