# DeepSeek Anthropic Provider

DeepSeek Anthropic Provider 是一个 MaiBot LLM Provider 插件。它让 MaiBot 通过 Anthropic SDK 调用 DeepSeek V4，并支持 DeepSeek Anthropic 兼容接口里的思考模式和联网搜索工具。

## 功能

- 注册 `client_type = "deepseek.anthropic"`，可在 MaiBot 模型供应商里选择使用。
- 支持 DeepSeek V4 Pro / V4 Flash 下拉选择。
- 支持开启/关闭思考模式，以及 `high` / `max` 思考深度。
- 支持 `web_search_20260209` 和 `web_search_20250305` server web search。
- 不重写 MaiBot 人格、记忆和聊天上下文，只做协议转换。

## 快速开始

1. 安装插件依赖。
2. 设置 `DEEPSEEK_API_KEY`，或在插件 WebUI 的“密钥设置”里填写 API key。
3. 在 MaiBot 模型供应商里新增 `client_type = "deepseek.anthropic"` 的供应商。
4. 把 replyer 或 planner 模型切到该供应商下的 DeepSeek V4 模型。
5. 用 `/deepseek_anthropic_ping` 和 `/deepseek_anthropic_search_test 关键词` 做连通性测试。

完整教程见 [USAGE.md](USAGE.md)。
