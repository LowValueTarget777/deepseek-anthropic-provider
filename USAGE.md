# Deepseek联网工具使用教程

> [!IMPORTANT]
> **只需在 MaiBot 的「模型设置 → 模型提供商（供应商）」中配置官方 DeepSeek，插件会自动复用其密钥，无需在插件里单独配置 API Key。**
>
> 只有一个官方 DeepSeek 提供商时，通常可直接使用默认设置；有多个时，在 MaiBot 模型设置中把要使用的一个命名为 DeepSeek。插件界面没有模型提供商页面，MaiBot 主模型可以继续使用其他提供商。

本版使用 DeepSeek 官方 Search 与 Fetch 接口，搜索结果与网页 Markdown 交给 MaiBot 主模型处理。保留原插件 ID、仓库和目录；显示名称更新为“Deepseek联网工具”。

## 准备供应商

1. 只在 MaiBot WebUI 的“模型设置 → 模型提供商（供应商）”中添加或检查官方 DeepSeek 提供商，并在那里配置密钥。
2. 确认 base_url 是 https://api.deepseek.com、https://api.deepseek.com/v1 或官方 Anthropic 兼容地址，api_key 已在该供应商中填写。
3. 重载插件，运行 /deepseek_web_status；无需在插件里填写密钥。
4. 存在多个官方 DeepSeek 供应商时，优先使用名称为 DeepSeek 的一个（不区分大小写）；无法唯一确定时，在 MaiBot 模型设置中调整名称。

供应商不一定需要被 MaiBot 主模型使用。第三方转发服务的密钥不能直接调用 DeepSeek 官方工具 API，插件只自动选择官方域名供应商。

## 配置文件读取

SDK 的配置能力读取的是 bot_config.toml，不能用 config.get("api_providers") 读取模型供应商。本版不臆造 RPC 方法，使用标准库 tomllib 只读解析本机 model_config.toml。

自动发现检查 Runner 工作目录下的 config/model_config.toml，以及标准 plugins/<plugin> 安装布局对应的模型配置。两个路径若指向同一文件会去重；若指向不同配置，则要求管理员在本地 config.toml 的 provider.model_config_path 指定真实路径。其他安装布局、容器或远程配置需保证该文件对插件进程可读。

provider.provider_name 与 provider.model_config_path 仅保留为兼容旧部署的本地高级选项，不显示在 WebUI，也不需要正常安装用户填写。旧版已指定的供应商与文件路径继续有效。

每次调用读取最新配置，密钥轮换后下一次请求即使用新值；不缓存到磁盘，不修改源文件，不把供应商配置返回给 Tool。读取失败时不回退旧插件密钥或环境变量。状态命令仅确认读取成功，不证明 API Key 有效。

## 搜索参数

~~~json
{
  "query": "DeepSeek site:deepseek.com lang:zh,en after:2026-10-01",
  "count": 50,
  "need_content": false,
  "ori_question": "DeepSeek 最近发布了什么？"
}
~~~

- query：1～128 个 Unicode 字符，不能全空白。
- count：1～50，插件默认 50，表示请求的结果条数，不是重复调用次数；已有配置的自定义值保留。
- need_content：是否带网页正文，默认 false；摘要类型可配置，默认长摘要优先。
- ori_question：可省略或 null，提供时为 1～128 字的原始问题；“传递原始问题”关闭后不转发，不自动编造。
- localization：省略时使用插件“默认本地化 IP”；显式空字符串取消默认值。填写 IP 地址，不是国家名称。

支持 site:、-site:、排除词、精确短语、lang:、after:、before:，具体组合以[官方语法](https://api-docs.deepseek.com/zh-cn/guides/search/)为准。条件可直接写进 query，也可在“网页搜索”中设置默认值；0.2.x 的 search_scope 与 depth 已退出配置。

### 配置默认搜索条件

以下为插件配置示例片段，不修改 MaiBot 的模型配置：

~~~toml
[search]
count = 50
allowed_sites = ["github.com", "deepseek.com"]
blocked_sites = ["example.com"]
excluded_terms = ["广告", "release notes"]
exact_phrases = []
languages = ["zh", "en"]
published_after = ""
published_before = ""
localization = ""
send_original_question = true
~~~

各列表每项填一个值，不在站点中填写协议、路径或 site:。短语不要自行加引号，不含反斜杠或换行。多个限定站点转换为 site:a OR site:b；排除词中带空格时自动生成 -"短语"，精确短语自动生成 "短语"。所有条件默认留空。

优先级：Tool 明确的 count、need_content、localization 覆盖配置；query 中明确的 site:、lang: 覆盖对应默认值，明确日期覆盖全部默认日期。全局排除条件和精确短语始终叠加。固定日期配置优先于“搜索最新消息”。最终 query 仍限 128 字，条件过多会明确报错，需减少默认条件或缩短关键词。

### 结果筛选与文本预算

Tool 的 content 是 JSON 文本，包含 results 数组，标题与 URL 始终返回。“摘要类型”可选长摘要优先（默认）、短摘要优先、长短都返回；优先字段为空时保留另一种摘要，避免丢失已有资料。发布时间、排序分数、权威性、站点名称可分别关闭，站点图标可单独开启，默认关闭。

配置文件的 sort_by 可填“综合相关性”“发布时间从新到旧”“权威性优先”，summary_mode 可填“长摘要优先”“短摘要优先”“长短摘要都返回”。旧英文值 relevance/date/authority 与 summary/snippet/both 会自动转换，仍可兼容；WebUI 直接使用中文选项，不依赖宿主尚未支持的 choice_labels。

最低排序分数默认 0、最低权威性默认 -1，表示不做质量过滤；开启后低于阈值或指标未知的结果都会被筛掉。可尝试分数 1.5、权威性 3，但限制较严可能漏掉资料，且分数不能证明事实正确。过滤依据原始指标，不受是否返回该字段影响。

结果排序可选综合相关性（默认）、发布时间从新到旧、权威性优先，未知指标排后；时间按带时区的日期比较。仅重排本次已召回的候选，不等于全网最新排序，也不会额外发请求。默认合并规范化后相同的 URL，忽略默认端口与域名大小写，但保留路径、查询参数、片段和协议差异。/#/article/1 与 /#/article/2 是不同结果，章节锚点也不会互相合并。

默认 max_result_chars=4000、max_total_text_chars=60000。所有入选结果平分文本预算，依次保留标题、摘要、正文，避免某一页正文占满全部空间；URL 与元数据不计入此预算。超出时返回对应 *_truncated 标记及 notice，可用 fetch_page 按链接读取正文。不为补足条数自动搜索，也不自动抓取每条结果。

result_info 记录 received_count、returned_count、filtered_count、duplicates_removed、sort_by、text_truncated。请求 50 条不保证入选 50 条：无匹配是正常空数组；全部被质量过滤时会明确提示降低要求，不会伪造内容或悄悄放宽限制。已有明确保存的 count 不会被升级覆盖，需使用 50 时可在 WebUI 调整。

result_info.sort_by 保持 relevance/date/authority 英文标识，不受界面和配置值中文化影响。

## 搜索最新消息

在“网页搜索”中开启“搜索最新消息”（search.latest_news_enabled），设置“最近多少天”（search.latest_news_days，默认 7，范围 1～365）。默认不开启，以免影响历史资料检索。

开启后使用北京时间计算日期，并在 query 末尾追加官方 after:YYYY-MM-DD 条件。例如北京时间 2026-10-17、范围 7 天时：

~~~text
DeepSeek 最新消息 after:2026-10-10
~~~

如果 query 已有明确的 after: 或 before: 日期条件，或配置了固定发布日期范围，插件不会另加近期限制。引号内作为精确/排除短语的日期文字不算筛选条件。追加日期后仍需满足 128 字上限，超长会明确提示缩短关键词。

自动添加过滤时，Tool 返回 time_filter，包含 after、recent_days 和 timezone，方便主模型了解实际筛选范围。这是按页面发布日期过滤，并不证明事件本身发生在该日期内，也不保证即时收录或按日期排序；主模型仍应核对来源时间。此开关不改变 Fetch 的指定网页抓取。

## 网页抓取

~~~json
{"url": "https://example.com/article?id=1"}
~~~

插件直接把 URL 发给官方 Fetch API，不经过 server web search。成功时 Tool 的 JSON 内容包括 url、title、Markdown content、total_chars、start_char、truncated、next_start_char 与 notice。

当 truncated=true 时，可把下一次调用的 start_char 设置为 next_start_char。每次续读都会重新请求该 URL，可能再次计费；页面发生更新时不同片段也可能变化。正文上限可在网页抓取标签页设置。超出正文末尾时返回空片段，不伪造内容。

Fetch 不能保证访问登录页、被封禁网站或无法提取文本的页面。官方 403/404 会明确失败，不自动绕过访问限制或交给模型补写。插件不在本地下载页面或解析 HTML。

## 更新与迁移

升级到 0.3.0 后：

- 显示名称改为 Deepseek联网工具，插件 ID、仓库地址、安装目录保持不变。
- 工具仍叫 search_and_summarize 与 fetch_page；结果由 MaiBot 主模型处理。
- 移除 deepseek_proxy、Anthropic 依赖、模型选择、思考配置、server search 版本及插件密钥字段。
- 保留并迁移插件开关、并发、超时、请求合并和日志开关。
- 顶部只显示五个标签页：基础设置、网页搜索、网页抓取、性能与超时、调试与日志；模型提供商页移除，旧本地高级设置保留兼容。
- 网页搜索增加最新消息开关与天数范围，自动日期过滤遵循查询中显式指定的时间条件。
- 默认请求 50 条，新增默认搜索语法条件、本地化 IP、原始问题转发、返回字段、质量筛选、排序、去重与文本预算；已有明确条数不强制覆盖。
- config.toml 继续由 Runner 生成和迁移，仓库只保留无密钥的 config.example.toml。

不需要修改实际 bot_config.toml 或 model_config.toml；旧插件里单独填写的密钥不会自动写入 MaiBot 主程序。需要在模型设置中已有官方 DeepSeek 供应商。

Runner 会先按新骨架重建旧配置。插件工厂因此在此之前只读提取本插件本地旧配置的四个非密钥迁移项（并发、请求合并、超时、请求日志），供首次重建使用；新字段显式值优先。首次配置注入后清除迁移状态，之后调整设置不会被旧值覆盖。捕获过程不写文件，不保留历史鉴权信息。

## 连接、费用与日志

默认每接口每秒 4 次请求，并发 4，等待与执行请求最多 64。Search 与 Fetch 分别限速；账号还有跨进程、跨客户端、Fetch 目标域名等限制。遇到 429 时稍后重试，不通过添加多个 key 规避账号限制。

总时限默认 120 秒，包含配置读取、队列、限速和网络；没有自动重试。相同会话、相同接口、请求参数和密钥的在途请求合并，完成后清除，不缓存答案。单个等待者取消不影响其他等待者；最后一个等待者取消时停止上游等待。卸载会取消未完成调用并关闭连接池。本地取消不保证上游停止计算或不计费。

请求总时限支持 1～600 秒。两个 Tool 和两个命令的组件 RPC 声明为 660 秒，并适配 SDK 2.5.2 的嵌套元数据，避免被宿主默认 60 秒提前截断；这不会把实际请求等待时间统一改成 660 秒。

状态命令 /deepseek_web_status 不调用远端接口。/deepseek_web_search_test 关键词 会执行一次真实请求。旧命令别名继续可用。

API 请求会把查询或目标 URL 发给 DeepSeek。响应和摘要返回给 MaiBot 主模型，该模型也会接收这些内容。搜索来源仅写日志，不自动直接发给聊天；Tool 内容中的 URL 用于让主模型核验或继续抓取。

## 测试

~~~bash
uv sync
uv run pytest -q -m "not integration"
uv run python -m py_compile plugin.py
~~~

离线测试使用合成模型配置与 HTTPX MockTransport，不读取真实供应商密钥或调用付费接口。测试含参数边界、凭据复用与轮换、HTTP 错误、空结果、正文分段、并发、限速、去重及卸载清理。

存在同目录 MaiBot 源码时，还会只读提取 Runner 的纯配置重建函数和超时解析器做契约回归；不导入或启动主程序。独立发布的插件测试环境没有这些源码时，仅跳过对应宿主契约测试。

真实测试需设置 RUN_DEEPSEEK_INTEGRATION=1，随后运行 uv run pytest -q -m integration。默认读取本机模型配置；可用 DEEPSEEK_TEST_MODEL_CONFIG 指定测试用的配置位置。它会真实调用 Search 与 Fetch，可能计费；不要把配置或密钥提交到仓库。

参考：[DeepSeek 官方说明](https://api-docs.deepseek.com/zh-cn/guides/search/)、[Search Schema](https://api-docs.deepseek.com/zh-cn/api/search/)、[Fetch Schema](https://api-docs.deepseek.com/zh-cn/api/fetch/)、[MaiBot API 参考](https://docs.mai-mai.org/plugin/api-reference)。
