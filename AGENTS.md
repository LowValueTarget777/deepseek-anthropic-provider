# DeepSeek Anthropic Provider 插件开发限制

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

## DeepSeek Anthropic 约束

- 插件只做管道：把 Bot 通过 Tool 传来的参数转为 Anthropic 请求发 DeepSeek，把结果还回去。不在插件里写爬虫、不调 requests、不 parse HTML。
- DeepSeek Anthropic 兼容接口支持文本和 server web search；不要把图片或文档二进制直接发送。
- 搜索来源默认只写日志，不主动附到聊天回复末尾。
- 不传 `thinking.type` / `output_config`（让模型自己决定是否思考）。

参考文档：

- <https://docs.mai-mai.org/develop/plugin-dev/vibe-coding>
- <https://api-docs.deepseek.com/zh-cn/guides/anthropic_api>
- <https://api-docs.deepseek.com/zh-cn/guides/thinking_mode>
