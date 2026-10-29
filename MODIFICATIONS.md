# 项目自定义修改记录 (Modifications Log)

本文档记录了基于上游原版 **Gemini Balance** 项目所做的扩展功能与修复变动。

---

## 📅 2026-07-25：Google 新版 API 密钥 (AQ. 前缀) 兼容适配
* **提交版本**：`3c98464`
* **影响文件**：
  1. `app/static/js/config_editor.js`
  2. `app/utils/helpers.py`
  3. `app/log/logger.py`
* **改动说明**：
  * **[密钥格式扩展与兼容]**：支持 Google AI Studio 生成的 `AQ.` 前缀新格式 API 密钥在前端提取、后端校验与访问日志脱敏。
    - [文件 1]：更新 `API_KEY_REGEX` 常量正则表达式，由 `/AIzaSy\S{33}/g` 替换为 `/((AIzaSy\S{33})|(AQ\.[a-zA-Z0-9_\-]{30,80}))/g`，实现前端批量添加与批量删除时对新版密钥的识别与提取。
    - [文件 2]：更新 `is_valid_api_key(key)` 校验函数，新增 `key.startswith("AQ.")` 判断分支，放行长度 >= 30 位的新版合法密钥。
    - [文件 3]：更新 `AccessLogFormatter` 类的 `API_KEY_PATTERNS` 模式列表，追加 `r"\bAQ\.[0-9A-Za-z_-]{30,80}"` 正则规则，确保带新版 Key 的请求写入 Access Log 时自动脱敏打码。

## 📅 2026-07-25：支持按模型独立轮询与 429 错误模型级隔离
* **提交版本**：`b5e97bd`
* **影响文件**：
  1. `app/exception/exceptions.py`
  2. `app/service/key/key_manager.py`
  3. `app/handler/retry_handler.py`
  4. `app/service/chat/gemini_chat_service.py`
  5. `app/service/chat/openai_chat_service.py`
  6. `app/service/chat/vertex_express_chat_service.py`
  7. `app/service/openai_compatiable/openai_compatiable_service.py`
  8. `app/router/gemini_routes.py`
  9. `app/router/openai_routes.py`
  10. `app/router/openai_compatiable_routes.py`
  11. `app/router/vertex_express_routes.py`
  12. `app/scheduler/scheduled_tasks.py`
* **改动说明**：
  * **[异常与密钥状态扩展]**：新增 `NoValidKeyError` 异常，并在 `KeyManager` 中实现按模型粒度的独立轮询与错误计数维护。
    - [文件 1]：定义 `NoValidKeyError` 异常类，当指定模型下无可用 API Key 时触发 429 响应。
    - [文件 2]：重构 `KeyManager` 类，新增 `model_key_failure_counts` 与 `model_key_cycles` 字典；重构 `get_next_working_key` 支持按模型独立轮询；重构 `handle_api_failure`，判断为 429 或配额耗尽错误时仅增加该 Key 对应模型的失败计数，若全 Key 429 直接抛出异常。
  * **[错误信息透传与自动切 Key 优化]**：在重试装饰器与各个 Service 中传递模型名称及异常状态码/错误信息。
    - [文件 3]：更新 `RetryHandler` 装饰器，从调用参数（包括平铺参数及 `request` 对象属性）中提取 `model_name` 并透传至 `handle_api_failure`。
    - [文件 4]：更新 Gemini Chat 服务在捕捉异常时对 `e.args` 进行防御性解构，并透传 `model_name`、`status_code` 与 `error_msg`。
    - [文件 5]：更新 OpenAI Chat 服务在捕捉异常时对 `e.args` 进行防御性解构，并透传 `model_name`、`status_code` 与 `error_msg`。
    - [文件 6]：更新 Vertex Express Chat 服务在捕捉异常时对 `e.args` 进行防御性解构，并透传 `model_name`、`status_code` 与 `error_msg`，调用 `handle_vertex_api_failure`。
    - [文件 7]：更新 OpenAI 兼容服务在捕捉异常时对 `e.args` 进行防御性解构，并透传 `model_name`、`status_code` 与 `error_msg`。
  * **[路由层精确选 Key 适配]**：修改路由层依赖注入，自动从 Request 解析 `model_name`。
    - [文件 8]：修改 `get_next_working_key` 依赖注入函数，从 Request 路径/Query/Body 中提取 `model_name` 并请求专属 Key。
    - [文件 9]：修改 OpenAI 路由中的 `get_next_working_key_wrapper` 依赖注入，支持按请求模型选择 Key。
    - [文件 10]：修改 OpenAI 兼容路由中的 `get_next_working_key_wrapper` 依赖注入，支持按请求模型选择 Key。
    - [文件 11]：修改 Vertex Express 路由中的 `get_next_working_key` 依赖注入，支持按请求模型选择 Vertex Key。
  * **[定时探针恢复优化]**：升级定时检查任务，支持模型级 429 限流恢复。
    - [文件 12]：更新 `check_failed_keys` 定时任务，增加按 `(model_name, key)` 组合发送探针验证，并在验证成功后重置对应模型的失败计数。

## 📅 2026-07-25：修复 Jinja2 模板渲染在新版 Starlette 中的签名兼容问题
* **提交版本**：`6064067`
* **影响文件**：
  1. `app/router/routes.py`
* **改动说明**：
  * **[Starlette 模板渲染语法适配]**：适配新版 Starlette 中 `TemplateResponse` 的函数签名要求。
    - [文件 1]：更新页面路由 `auth_page`、`keys_page`、`config_page` 和 `logs_page` 中的 `templates.TemplateResponse` 调用格式，显式通过 `request=request, name="..."` 传递参数，解决新版 Starlette 中因旧版位置参数导致的 `TypeError: unhashable type: 'dict'` 异常。

## 📅 2026-07-26：修复 thinkingBudget 为 0 导致 500 异常的问题
* **提交版本**：`0e86eff`
* **影响文件**：
  1. `app/service/chat/gemini_chat_service.py`
  2. `app/service/chat/openai_chat_service.py`
  3. `app/service/chat/vertex_express_chat_service.py`
* **改动说明**：
  * **[思考参数自动清洗]**：解决客户端请求中 `thinkingBudget: 0` 导致 Gemini 上游 API 报 400 及后端 500 异常。
    - [文件 1]：更新 `_build_payload` 函数，当客户端指定 `thinkingBudget` 为 `0` 时，自动剥离 `thinkingConfig` 字段，向上游发起标准非思考请求。
    - [文件 2]：更新 OpenAI Chat 服务的 `_build_payload`，当 `thinkingBudget` 为 `0` 时自动剔除 `thinkingConfig` 字段。
    - [文件 3]：更新 Vertex Express Chat 服务的 `_build_payload`，当 `thinkingBudget` 为 `0` 时自动剔除 `thinkingConfig` 字段。

## 📅 2026-07-26：新增本日调用统计 (美西太平洋午夜刷新)
* **提交版本**：`4f5eb81`
* **影响文件**：
  1. `app/service/stats/stats_service.py`
  2. `app/router/routes.py`
  3. `app/templates/keys_status.html`
  4. `app/static/js/keys_status.js`
* **改动说明**：
  * **[美西午夜重置统计支持]**：新增基于美西太平洋时间（America/Los_Angeles）零点重置的“本日调用”统计。
    - [文件 1]：引入 `zoneinfo.ZoneInfo` 实现 `get_pacific_today_start()` 函数；新增 `get_calls_today_pacific` 统计方法并注入 `get_api_usage_stats`；扩展 `get_api_call_details` 支持 `period="today"` 详情查询。
    - [文件 2]：在页面路由 `keys_page` 的异常兜底数据结构中补全 `calls_today` 字段。
    - [文件 3]：在概览面板中新增“本日调用”可视化卡片，卡片 title 增加换行备注“(美西太平洋时间0点重置)”。
    - [文件 4]：在 `showApiCallDetails` 详情弹窗函数中适配 `"today"` 标识的标题展示。

## 📅 2026-07-28：管理员登录过期时间支持 UI 配置与最大 1 年延长
* **提交版本**：`05b26b6`
* **影响文件**：
  1. `app/config/config.py`
  2. `app/router/routes.py`
  3. `app/templates/config_editor.html`
  4. `app/static/js/config_editor.js`
* **改动说明**：
  * **[登录过期配置扩展]**：放宽管理员会话过期时间上限并在控制台暴露设置项。
    - [文件 1]：更新 `ADMIN_SESSION_EXPIRE` 校验规则，上限由 `86400`（24小时）提高至 `31536000`（1年）。
    - [文件 2]：在 `response.set_cookie` 种植 `auth_token` 时显式指定 `path="/"` 全局作用域。
    - [文件 3]：在控制台网页配置编辑器中新增“管理员登录过期时间 (秒)”设置输入框与提示文案。
    - [文件 4]：增加过期时间单位实时换算提示（秒转小时/天）。

## 📅 2026-09-10：假流式功能增强（Gemini原生支持、异常结束标识拦截与优先等待机制）
* **提交版本**：`15b1553`
* **影响文件**：
  1. `app/config/config.py`
  2. `app/templates/config_editor.html`
  3. `app/static/js/config_editor.js`
  4. `app/service/chat/openai_chat_service.py`
  5. `app/service/chat/gemini_chat_service.py`
  6. `app/service/chat/vertex_express_chat_service.py`
  7. `app/handler/response_handler.py`
* **改动说明**：
  * **[假流式配置项扩展]**：新增 Gemini 原生假流式、异常结束标识校验与优先等待上游配置项。
    - [文件 1]：在 `Settings` 配置类中新增 `GEMINI_FAKE_STREAM_ENABLED`、`FAKE_STREAM_CHECK_FINISH_REASON`、`FAKE_STREAM_WAIT_UPSTREAM_ENABLED` 与 `FAKE_STREAM_MAX_WAIT_SECONDS` 字段。
    - [文件 2]：在配置编辑器前端界面假流式配置卡片中新增上述配置的开关与数值输入控件及提示说明。
    - [文件 3]：在前端脚本中完善新增假流式配置项的默认值初始化、表单数据回显与保存提交逻辑。
  * **[OpenAI 假流式错误拦截与等待优化]**：支持优先等待上游响应并在异常时直返 HTTP 错误或下发 SSE 错误结构体。
    - [文件 4]：在 `_fake_stream_logic_impl` 中实现优先等待上游返回机制，未发心跳前发生异常直接抛错由路由返回 HTTP 400/500 JSON，已发心跳后发生异常按方案1下发标准 OpenAI SSE Error 数据块。
  * **[Gemini 原生假流式及异常拦截]**：为 Gemini 原生流式接口实现完整的伪流式、心跳保活与错误拦截机制。
    - [文件 5]：新增 `_fake_stream_logic_impl` 与 `_real_stream_logic_impl` 分流逻辑，支持保活心跳、未发心跳直返 HTTP 错误及已发心跳下发 Gemini 标准 SSE 错误包。
    - [文件 6]：同步为 Vertex 原生流式接口实现假流式分流、优先等待及异常拦截逻辑。
  * **[多 Part 响应解析与思考分离修复]**：修复假流式与流式下多 parts 内容被截断或错误覆盖思考标记的问题。
    - [文件 7]：在 `_extract_result` 中统一遍历全部 parts 分离提取思考过程（`thought: True`）与正式正文，并在 `_handle_gemini_stream_response` 中独立构建思考与正文 parts 列表。

## 📅 2026-09-10：新增请求失败重试间隔配置（支持序列与倍数退避）
* **提交版本**：`fa5b6fc`
* **影响文件**：
  1. `app/config/config.py`
  2. `app/utils/helpers.py`
  3. `app/templates/config_editor.html`
  4. `app/static/js/config_editor.js`
  5. `app/handler/retry_handler.py`
  6. `app/service/chat/openai_chat_service.py`
  7. `app/service/chat/gemini_chat_service.py`
  8. `app/service/chat/vertex_express_chat_service.py`
  9. `app/service/openai_compatiable/openai_compatiable_service.py`
* **改动说明**：
  * **[配置项与算法支持]**：添加重试间隔配置项并实现退避序列计算算法。
    - [文件 1]：在 `Settings` 配置类中新增 `RETRY_INTERVALS` 字段。
    - [文件 2]：实现 `calculate_retry_delay` 函数，支持具体秒数列表、倍数退避计算与 300 秒安全上限保护。
  * **[控制台前端呈现]**：在 Web 配置界面暴露重试间隔设置。
    - [文件 3]：在“最大重试次数”下方新增“失败重试间隔（秒）”输入框及规则说明 Tooltip。
    - [文件 4]：在前端脚本中补充 `RETRY_INTERVALS` 的默认值初始化。
  * **[重试等待调用生效]**：在非流式与流式服务重试时加入间隔等待。
    - [文件 5]：在 `RetryHandler` 装饰器中增加异常重试时的 `asyncio.sleep` 等待。
    - [文件 6]：在 `OpenAIChatService._handle_stream_completion` 循环中增加重试等待逻辑。
    - [文件 7]：在 `GeminiChatService.stream_generate_content` 循环中增加重试等待逻辑。
    - [文件 8]：在 `VertexExpressChatService.stream_generate_content` 循环中增加重试等待逻辑。
    - [文件 9]：在 `OpenAICompatiableService._handle_stream_completion` 循环中增加重试等待逻辑。

## 📅 2026-09-10：新增成功 API 请求完整请求体与响应体保存与详情查看功能
* **提交版本**：`69bc161`
* **影响文件**：
  1. `app/config/config.py`
  2. `app/database/models.py`
  3. `app/database/services.py`
  4. `app/service/stats/stats_service.py`
  5. `app/router/error_log_routes.py`
  6. `app/service/chat/openai_chat_service.py`
  7. `app/service/chat/gemini_chat_service.py`
  8. `app/service/chat/vertex_express_chat_service.py`
  9. `app/service/openai_compatiable/openai_compatiable_service.py`
  10. `app/templates/config_editor.html`
  11. `app/static/js/config_editor.js`
  12. `app/static/js/keys_status.js`
* **改动说明**：
  * **[成功详情存储与模型支持]**：新增 `SuccessLog` 模型并在配置中增加保存开关与条数上限。
    - [文件 1]：在 `Settings` 配置类中新增 `RECORD_SUCCESS_LOG_DETAIL_ENABLED` 与 `SUCCESS_LOG_MAX_RECORDS`。
    - [文件 2]：新增 `SuccessLog` 表模型（`t_success_logs`），包含关联日志 ID、时间、Key、模型、请求体与响应体等字段。
    - [文件 3]：实现 `add_success_log_detail`、`cleanup_excess_success_logs` 淘汰清理机制（最多保留 300 条）及 `find_success_log_by_info`。
  * **[服务层请求与响应数据捕获]**：在非流式与流式服务中捕获并持久化完整的请求体与响应体。
    - [文件 4]：在 `StatsService` 的调用详情查询中比对返回 `has_detail` 标记，用于前端识别有效详情。
    - [文件 5]：在日志路由中暴露 `/api/logs/success/lookup` 端点，供前端按条件检索成功详情。
    - [文件 6]：在 `OpenAIChatService` 普通与流式聊天结束时分别组装并持久化完整请求体与响应体。
    - [文件 7]：在 `GeminiChatService` 普通与流式聊天结束时分别捕获完整请求与响应内容。
    - [文件 8]：在 `VertexExpressChatService` 普通与流式逻辑中同步记录完整请求与响应数据。
    - [文件 9]：在 `OpenAICompatiableService` 中补全普通与流式调用的请求与响应保存。
  * **[前端界面展示与交互]**：在控制台界面展示成功详情与配置项。
    - [文件 10]：在配置编辑器界面新增成功请求保存详情开关与最大保留条数输入框。
    - [文件 11]：在前端脚本中补充新增成功日志配置项的默认值初始化。
    - [文件 12]：在 API 调用详情列表的成功记录行渲染绿色「详情」按钮，点击弹窗支持高亮格式化展示完整请求体/响应体并支持一键复制。

## 📅 2026-10-15：假流式向上游实际发起流式请求与超时机制支持
* **提交版本**：`6f99220`
* **影响文件**：
  1. `app/config/config.py`
  2. `.env.example`
  3. `README_ZH.md`
  4. `README.md`
  5. `app/service/client/api_client.py`
  6. `app/service/chat/openai_chat_service.py`
  7. `app/service/chat/gemini_chat_service.py`
  8. `app/service/chat/vertex_express_chat_service.py`
  9. `app/templates/config_editor.html`
  10. `app/static/js/config_editor.js`
* **改动说明**：
  * **[假流式配置扩展]**：新增假流式向上游实际发起流式请求与流式响应超时配置项。
    - [文件 1]：在 `Settings` 中新增 `FAKE_STREAM_UPSTREAM_STREAMING` 与 `FAKE_STREAM_STREAMING_TIMEOUT_SECONDS`（默认 120 秒）字段。
    - [文件 2]：在 `.env.example` 中补充新增环境变量及注释说明。
    - [文件 3]：在中文说明文档的伪流式参数表格中同步更新配置项定义。
    - [文件 4]：在英文说明文档中同步更新配置项表格说明。
  * **[上游流式聚合与超时熔断]**：在 APIClient 中支持将上游流式响应消费聚合为标准响应结构。
    - [文件 5]：在 `GeminiApiClient` 中新增 `stream_generate_content_as_response` 方法，消费流式 SSE 行并聚合 candidates、parts、finishReason 与 usageMetadata，并通过 `asyncio.wait_for` 强制超时中断（超时抛出 504 异常）。
  * **[服务层假流式流式请求与两阶段异常捕获]**：在各 ChatService 中支持按配置向上游发起流式请求并进行全生命周期异常管控。
    - [文件 6]：在 `OpenAIChatService._fake_stream_logic_impl` 中支持切换上游流式调用，等待流式完全结束再校验 finishReason，同时捕获超时与上游报错，未发心跳前直返 HTTP 错误，已发心跳后下发 SSE 错误。
    - [文件 7]：在 `GeminiChatService._fake_stream_logic_impl` 中同步支持上游流式聚合、超时控制与两阶段异常处理。
    - [文件 8]：在 `VertexExpressChatService._fake_stream_logic_impl` 中同步实现相同的上游流式调用与两阶段异常拦截。
  * **[前端配置编辑器交互]**：在配置管理页面中增加新增假流式选项的表单输入与双向绑定。
    - [文件 9]：在假流式卡片中新增「假流式向上游发起流式请求」开关与「假流式流式响应超时时间」数字输入项。
    - [文件 10]：在前端脚本中补全新增选项的默认值设置、表单回显与数据收集。

## 📅 2026-10-15：假流式上游错误即时熔断、多轮重试机制深度修复与原生错误报文透传
* **提交版本**：`<Current>`
* **影响文件**：
  1. `app/utils/helpers.py`
  2. `app/service/client/api_client.py`
  3. `app/service/chat/gemini_chat_service.py`
  4. `app/service/chat/vertex_express_chat_service.py`
  5. `app/service/chat/openai_chat_service.py`
* **改动说明**：
  * **[上游流式错误即时熔断]**：修复流式数据中途包含 error 数据块被吞并误判成功的漏洞。
    - [文件 2]：在 `GeminiApiClient.stream_generate_content_as_response` 中一旦检测到包含 `error` 字段的 SSE chunk，立即提取错误码并抛出异常中断流拉取。
  * **[假流式异常判定重构]**：彻底重构各服务的假流式异常拦截规则。
    - [文件 3]：在 `GeminiChatService._fake_stream_logic_impl` 中调整异常识别顺序，将 error 校验前置，抛出异常触发重试。
    - [文件 4]：在 `VertexExpressChatService._fake_stream_logic_impl` 中同步重构异常判定与重试抛出。
    - [文件 5]：在 `OpenAIChatService._fake_stream_logic_impl` 中将 `error` 校验优先级前置，并在开启结束原因检查时判定中途断流无 finishReason 的响应为异常并抛出。
  * **[假流式重试机制贯通]**：实现心跳维持下的无感换 Key 重试与重试耗尽兜底。
    - [文件 3]：在 `GeminiChatService.stream_generate_content` 中跟踪 `has_yielded_data`，在上游报错时正常换 Key 并在心跳维持下无感重试，仅在重试耗尽且已发心跳时下发标准 SSE Error 数据块。
    - [文件 4]：在 `VertexExpressChatService.stream_generate_content` 中同步支持心跳阶段的多轮换 Key 重试与兜底下发。
    - [文件 5]：在 `OpenAIChatService._handle_stream_completion` 中同步实现心跳维持下的多轮换 Key 重试机制与重试耗尽兜底。
  * **[上游错误智能解析与原生透传]**：消除 JSON-in-JSON 二次转义并全量透传原生错误报文。
    - [文件 1]：在 `helpers.py` 中新增 `parse_upstream_error`，自动解析上游原始 JSON 报文，提取纯净文本 `clean_message` 与结构化 `error_dict`。
    - [文件 3]：在 `GeminiChatService` 错误下发与异常判定中直接透传 `{"error": error_dict}`，保留原生 status 与错误语义。
    - [文件 4]：在 `VertexExpressChatService` 中同步实现 `error_dict` 原生透传与纯净日志记录。
    - [文件 5]：在 `OpenAIChatService` 中提纯 `clean_message` 填充进 OpenAI 标准错误格式的 `message` 字段。
