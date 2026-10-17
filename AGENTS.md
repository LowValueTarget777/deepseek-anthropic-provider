# Deepseek联网工具插件开发限制

你正在维护 `plugins/deepseek-anthropic-provider/` 这个 MaiBot 第三方插件。

## 强制边界

- 所有插件实现、测试和文档改动默认只允许发生在当前插件目录内。
- 不要修改 `src/`、`dashboard/`、`config/`、仓库根目录 `.gitignore` 或其他 MaiBot 主程序文件。
- 不要修改实际的 `bot_config.toml` 或 `model_config.toml`；只在文档里提供示例。
- 如果需求必须依赖主程序改动，先停止并说明原因、影响面和替代方案。
- 插件入口固定为 `plugin.py`，工厂函数固定为 `create_plugin()`，元信息文件固定为 `_manifest.json`。

## 开发约束

- 使用 MaiBot Plugin SDK 的 `@Tool`、`@Command` 等公开接口。
- 不要在插件代码中导入 `src.*`，保持插件可独立发布。
- 不要新增 `@LLMProvider` 或 `@Action`。
- 依赖同时维护 `_manifest.json` 和 `pyproject.toml`，优先使用 `uv` 安装和测试。
- 所有 WebUI 配置文案、日志和用户可见文本优先使用通俗简体中文。
- 不要提交真实 API key、cookie、token、私有 URL 或本地路径。

## DeepSeek 联网接口约束

- 根据用户的 0.3.0 迁移要求，搜索和抓取分别调用官方 /v1/tools/search 与 /v1/tools/fetch，使用 httpx；不再调用 Anthropic server web search 或额外对话模型。
- 插件只转发检索参数与结构化结果，不写本地爬虫、不使用 requests、不解析 HTML；结果交给 MaiBot 主模型归纳。
- 密钥只读复用本机 model_config.toml 中的官方 DeepSeek 供应商；不在插件设置保存密钥，不回退旧插件 key 或环境变量 key，不修改模型配置文件。
- 当前 SDK 配置能力只公开 Bot 配置。供应商读取使用标准 TOML 解析器，支持普通安装自动发现和管理员指定只读路径，不导入 src.*。
- 只向固定官方域名发送供应商密钥，不把第三方转发服务的 key 发给官方接口。
- 搜索来源默认只写日志，不主动向聊天追加来源列表；Tool 返回中的 URL 用于主模型核验与继续抓取。
- 保留已发布插件 ID 和仓库地址，显示名称为 Deepseek联网工具。

参考文档：

- <https://docs.mai-mai.org/plugin/vibe-coding>
- <https://docs.mai-mai.org/plugin/api-reference>
- <https://api-docs.deepseek.com/zh-cn/guides/search/>
