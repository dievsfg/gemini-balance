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
* **提交版本**：`<Current>`
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
