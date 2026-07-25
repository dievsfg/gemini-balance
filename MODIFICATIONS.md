# 项目自定义修改记录 (Modifications Log)

本文档记录了基于上游原版 **Gemini Balance** 项目所做的扩展功能与修复变动。

---

## 📅 2026-07-25：Google 新版 API 密钥 (AQ. 前缀) 兼容适配
* **提交版本**：`<Current>`
* **影响文件**：
  1. `app/static/js/config_editor.js`
  2. `app/utils/helpers.py`
  3. `app/log/logger.py`
* **改动说明**：
  * **[密钥格式扩展与兼容]**：支持 Google AI Studio 生成的 `AQ.` 前缀新格式 API 密钥在前端提取、后端校验与访问日志脱敏。
    - [文件 1]：更新 `API_KEY_REGEX` 常量正则表达式，由 `/AIzaSy\S{33}/g` 替换为 `/((AIzaSy\S{33})|(AQ\.[a-zA-Z0-9_\-]{30,80}))/g`，实现前端批量添加与批量删除时对新版密钥的识别与提取。
    - [文件 2]：更新 `is_valid_api_key(key)` 校验函数，新增 `key.startswith("AQ.")` 判断分支，放行长度 >= 30 位的新版合法密钥。
    - [文件 3]：更新 `AccessLogFormatter` 类的 `API_KEY_PATTERNS` 模式列表，追加 `r"\bAQ\.[0-9A-Za-z_-]{30,80}"` 正则规则，确保带新版 Key 的请求写入 Access Log 时自动脱敏打码。
