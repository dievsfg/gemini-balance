# app/services/chat_service.py

import asyncio
import datetime
import json
import time
from typing import Any, AsyncGenerator, Dict, List

from app.config.config import settings
from app.core.constants import GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
from app.database.services import add_error_log, add_request_log
from app.domain.gemini_models import GeminiRequest
from app.handler.response_handler import GeminiResponseHandler
from app.handler.stream_optimizer import gemini_optimizer
from app.log.logger import get_gemini_logger
from app.service.client.api_client import GeminiApiClient
from app.service.key.key_manager import KeyManager
from app.utils.helpers import redact_key_for_logging

logger = get_gemini_logger()


def _has_image_parts(contents: List[Dict[str, Any]]) -> bool:
    """判断消息是否包含图片部分"""
    for content in contents:
        if "parts" in content:
            for part in content["parts"]:
                if "image_url" in part or "inline_data" in part:
                    return True
    return False


def _clean_json_schema_properties(obj: Any) -> Any:
    """清理JSON Schema中Gemini API不支持的字段"""
    if not isinstance(obj, dict):
        return obj

    # Gemini API不支持的JSON Schema字段
    unsupported_fields = {
        "exclusiveMaximum",
        "exclusiveMinimum",
        "const",
        "examples",
        "contentEncoding",
        "contentMediaType",
        "if",
        "then",
        "else",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "definitions",
        "$schema",
        "$id",
        "$ref",
        "$comment",
        "readOnly",
        "writeOnly",
    }

    cleaned = {}
    for key, value in obj.items():
        if key in unsupported_fields:
            continue
        if isinstance(value, dict):
            cleaned[key] = _clean_json_schema_properties(value)
        elif isinstance(value, list):
            cleaned[key] = [_clean_json_schema_properties(item) for item in value]
        else:
            cleaned[key] = value

    return cleaned


def _build_tools(model: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构建工具"""

    def _has_function_call(contents: List[Dict[str, Any]]) -> bool:
        """检查内容中是否包含 functionCall"""
        if not contents or not isinstance(contents, list):
            return False
        for content in contents:
            if not content or not isinstance(content, dict) or "parts" not in content:
                continue
            parts = content.get("parts", [])
            if not parts or not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and "functionCall" in part:
                    return True
        return False

    def _merge_tools(tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        record = dict()
        for item in tools:
            if not item or not isinstance(item, dict):
                continue

            for k, v in item.items():
                if k == "functionDeclarations" and v and isinstance(v, list):
                    functions = record.get("functionDeclarations", [])
                    # 清理每个函数声明中的不支持字段
                    cleaned_functions = []
                    for func in v:
                        if isinstance(func, dict):
                            cleaned_func = _clean_json_schema_properties(func)
                            cleaned_functions.append(cleaned_func)
                        else:
                            cleaned_functions.append(func)
                    functions.extend(cleaned_functions)
                    record["functionDeclarations"] = functions
                else:
                    record[k] = v
        return record

    def _is_structured_output_request(payload: Dict[str, Any]) -> bool:
        """检查请求是否要求结构化JSON输出"""
        try:
            generation_config = payload.get("generationConfig", {})
            return generation_config.get("responseMimeType") == "application/json"
        except (AttributeError, TypeError):
            return False

    tool = dict()
    if payload and isinstance(payload, dict) and "tools" in payload:
        if payload.get("tools") and isinstance(payload.get("tools"), dict):
            payload["tools"] = [payload.get("tools")]
        items = payload.get("tools", [])
        if items and isinstance(items, list):
            tool.update(_merge_tools(items))

    # "Tool use with a response mime type: 'application/json' is unsupported"
    # Gemini API限制：不支持同时使用tools和结构化输出(response_mime_type='application/json')
    # 当请求指定了JSON响应格式时，跳过所有工具的添加以避免API错误
    has_structured_output = _is_structured_output_request(payload)
    if not has_structured_output:
        if (
            settings.TOOLS_CODE_EXECUTION_ENABLED
            and not (model.endswith("-search") or "-thinking" in model)
            and not _has_image_parts(payload.get("contents", []))
        ):
            tool["codeExecution"] = {}

        if model.endswith("-search"):
            tool["googleSearch"] = {}

        real_model = _get_real_model(model)
        if real_model in settings.URL_CONTEXT_MODELS and settings.URL_CONTEXT_ENABLED:
            tool["urlContext"] = {}

    # 解决 "Tool use with function calling is unsupported" 问题
    if tool.get("functionDeclarations") or _has_function_call(
        payload.get("contents", [])
    ):
        tool.pop("googleSearch", None)
        tool.pop("codeExecution", None)
        tool.pop("urlContext", None)

    return [tool] if tool else []


def _get_real_model(model: str) -> str:
    if model.endswith("-search"):
        model = model[:-7]
    if model.endswith("-image"):
        model = model[:-6]
    if model.endswith("-non-thinking"):
        model = model[:-13]
    if "-search" in model and "-non-thinking" in model:
        model = model[:-20]
    return model


def _get_safety_settings(model: str) -> List[Dict[str, str]]:
    """获取安全设置"""
    if model == "gemini-2.0-flash-exp":
        return GEMINI_2_FLASH_EXP_SAFETY_SETTINGS
    return settings.SAFETY_SETTINGS


def _build_payload(model: str, request: GeminiRequest) -> Dict[str, Any]:
    """构建请求payload"""
    request_dict = request.model_dump(exclude_none=False)
    if request.generationConfig:
        if request.generationConfig.maxOutputTokens is None:
            # 如果未指定最大输出长度，则不传递该字段，解决截断的问题
            request_dict["generationConfig"].pop("maxOutputTokens")

    payload = {
        "contents": request_dict.get("contents", []),
        "tools": _build_tools(model, request_dict),
        "safetySettings": _get_safety_settings(model),
        "generationConfig": request_dict.get("generationConfig"),
        "systemInstruction": request_dict.get("systemInstruction"),
    }

    if model.endswith("-image") or model.endswith("-image-generation"):
        payload.pop("systemInstruction")
        payload["generationConfig"]["responseModalities"] = ["Text", "Image"]

    # 处理思考配置：优先使用客户端提供的配置，否则使用默认配置
    client_thinking_config = None
    if request.generationConfig and request.generationConfig.thinkingConfig:
        client_thinking_config = request.generationConfig.thinkingConfig

    if client_thinking_config is not None:
        # 客户端提供了思考配置
        if isinstance(client_thinking_config, dict) and client_thinking_config.get("thinkingBudget") == 0:
            payload["generationConfig"].pop("thinkingConfig", None)
        else:
            payload["generationConfig"]["thinkingConfig"] = client_thinking_config
    else:
        # 客户端没有提供思考配置，使用默认配置
        if model.endswith("-non-thinking"):
            if "gemini-2.5-pro" in model:
                payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 128}
            else:
                payload["generationConfig"].pop("thinkingConfig", None)
        elif _get_real_model(model) in settings.THINKING_BUDGET_MAP:
            if settings.SHOW_THINKING_PROCESS:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingBudget": settings.THINKING_BUDGET_MAP.get(model, 1000),
                    "includeThoughts": True,
                }
            else:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingBudget": settings.THINKING_BUDGET_MAP.get(model, 1000)
                }

    # 防御性校验：若 thinkingConfig 中包含非法或者为 0 的 thinkingBudget，直接剔除 thinkingConfig 字段
    tc = payload["generationConfig"].get("thinkingConfig")
    if isinstance(tc, dict) and tc.get("thinkingBudget") == 0:
        payload["generationConfig"].pop("thinkingConfig", None)

    return payload


class GeminiChatService:
    """聊天服务"""

    def __init__(self, base_url: str, key_manager: KeyManager):
        self.api_client = GeminiApiClient(base_url, settings.TIME_OUT)
        self.key_manager = key_manager
        self.response_handler = GeminiResponseHandler()

    def _extract_text_from_response(self, response: Dict[str, Any]) -> str:
        """从响应中提取文本内容"""
        if not response.get("candidates"):
            return ""

        candidate = response["candidates"][0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        if parts and "text" in parts[0]:
            return parts[0].get("text", "")
        return ""

    def _create_char_response(
        self, original_response: Dict[str, Any], text: str
    ) -> Dict[str, Any]:
        """创建包含指定文本的响应"""
        response_copy = json.loads(json.dumps(original_response))  # 深拷贝
        if response_copy.get("candidates") and response_copy["candidates"][0].get(
            "content", {}
        ).get("parts"):
            response_copy["candidates"][0]["content"]["parts"][0]["text"] = text
        return response_copy

    async def generate_content(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> Dict[str, Any]:
        """生成内容"""
        payload = _build_payload(model, request)
        start_time = time.perf_counter()
        request_datetime = datetime.datetime.now()
        is_success = False
        status_code = None
        response = None

        try:
            response = await self.api_client.generate_content(payload, model, api_key)
            is_success = True
            status_code = 200
            return self.response_handler.handle_response(response, model, stream=False)
        except Exception as e:
            is_success = False
            status_code = e.args[0] if len(e.args) > 0 and isinstance(e.args[0], int) else 500
            error_log_msg = e.args[1] if len(e.args) > 1 else str(e)
            logger.error(f"Normal API call failed with error: {error_log_msg}")

            await add_error_log(
                gemini_key=api_key,
                model_name=model,
                error_type="gemini-chat-non-stream",
                error_log=error_log_msg,
                error_code=status_code,
                request_msg=payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None,
                request_datetime=request_datetime,
            )
            raise e
        finally:
            end_time = time.perf_counter()
            latency_ms = int((end_time - start_time) * 1000)
            await add_request_log(
                model_name=model,
                api_key=api_key,
                is_success=is_success,
                status_code=status_code,
                latency_ms=latency_ms,
                request_time=request_datetime,
            )

    async def _fake_stream_logic_impl(
        self, model: str, payload: Dict[str, Any], api_key: str
    ) -> AsyncGenerator[str, None]:
        """处理 Vertex Gemini 伪流式 (fake stream) 的核心逻辑"""
        logger.info(
            f"Fake streaming enabled for Vertex model: {model}. Calling non-streaming endpoint."
        )

        api_response_task = asyncio.create_task(
            self.api_client.generate_content(payload, model, api_key)
        )

        has_yielded_heartbeat = False
        heartbeat_interval = max(1, settings.FAKE_STREAM_EMPTY_DATA_INTERVAL_SECONDS)

        try:
            if settings.FAKE_STREAM_WAIT_UPSTREAM_ENABLED:
                max_wait_seconds = max(1, settings.FAKE_STREAM_MAX_WAIT_SECONDS)
                waited = 0
                while not api_response_task.done() and waited < max_wait_seconds:
                    await asyncio.sleep(1)
                    waited += 1

                if not api_response_task.done():
                    # 超过最大等待时间，发送首个心跳包并进入心跳循环
                    empty_chunk = {
                        "candidates": [
                            {"content": {"parts": [], "role": "model"}, "index": 0}
                        ]
                    }
                    yield f"data: {json.dumps(empty_chunk)}\n\n"
                    has_yielded_heartbeat = True
                    logger.debug(
                        "Initial wait timed out. Sent first empty data chunk for Vertex fake stream heartbeat."
                    )

                    i = 0
                    while not api_response_task.done():
                        await asyncio.sleep(1)
                        if not api_response_task.done():
                            i += 1
                            if i >= heartbeat_interval:
                                i = 0
                                empty_chunk = {
                                    "candidates": [
                                        {
                                            "content": {
                                                "parts": [],
                                                "role": "model",
                                            },
                                            "index": 0,
                                        }
                                    ]
                                }
                                yield f"data: {json.dumps(empty_chunk)}\n\n"
                                logger.debug(
                                    "Sent empty data chunk for Vertex fake stream heartbeat."
                                )
            else:
                i = 0
                while not api_response_task.done():
                    await asyncio.sleep(1)
                    if not api_response_task.done():
                        i += 1
                        if i >= heartbeat_interval:
                            i = 0
                            empty_chunk = {
                                "candidates": [
                                    {
                                        "content": {
                                            "parts": [],
                                            "role": "model",
                                        },
                                        "index": 0,
                                    }
                                ]
                            }
                            yield f"data: {json.dumps(empty_chunk)}\n\n"
                            has_yielded_heartbeat = True
                            logger.debug(
                                "Sent empty data chunk for Vertex fake stream heartbeat."
                            )
        finally:
            response = await api_response_task

        candidates = (
            response.get("candidates", []) if isinstance(response, dict) else []
        )
        candidate = candidates[0] if candidates else {}
        finish_reason = candidate.get("finishReason")

        is_abnormal = False
        error_msg = ""

        if not response or not candidates:
            is_abnormal = True
            error_msg = "No candidates returned from model"
            if isinstance(response, dict) and response.get("error"):
                err_info = response.get("error")
                error_msg = (
                    err_info.get("message", error_msg)
                    if isinstance(err_info, dict)
                    else str(err_info)
                )
            elif isinstance(response, dict) and response.get("promptFeedback"):
                error_msg = f"Prompt blocked: {response.get('promptFeedback')}"
        elif (
            settings.FAKE_STREAM_CHECK_FINISH_REASON
            and finish_reason
            and finish_reason != "STOP"
        ):
            is_abnormal = True
            error_msg = (
                f"Stream generation finished with abnormal finishReason: {finish_reason}"
            )

        if is_abnormal:
            logger.error(
                f"Fake stream abnormal response for Vertex model {model} (has_yielded_heartbeat={has_yielded_heartbeat}): {error_msg}"
            )
            if not has_yielded_heartbeat:
                # 未向客户端发送任何数据包，直接抛出异常，由路由层返回 HTTP 400/500 JSON 错误
                raise Exception(400, error_msg)
            else:
                # 已发送过心跳包，通过 SSE 下发 Gemini 格式的标准错误包
                error_chunk = {
                    "error": {
                        "code": 400,
                        "message": error_msg,
                        "status": (
                            "ABNORMAL_FINISH_REASON"
                            if finish_reason and finish_reason != "STOP"
                            else "API_ERROR"
                        ),
                    }
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                return

        response_data = self.response_handler.handle_response(
            response, model, stream=True
        )
        text = self._extract_text_from_response(response_data)
        if text and settings.STREAM_OPTIMIZER_ENABLED:
            async for (
                optimized_chunk
            ) in gemini_optimizer.optimize_stream_output(
                text,
                lambda t: self._create_char_response(response_data, t),
                lambda c: "data: " + json.dumps(c) + "\n\n",
            ):
                yield optimized_chunk
        else:
            yield "data: " + json.dumps(response_data) + "\n\n"

    async def _real_stream_logic_impl(
        self, model: str, payload: Dict[str, Any], api_key: str
    ) -> AsyncGenerator[str, None]:
        """处理 Vertex Gemini 真实流式 (real stream) 的核心逻辑"""
        async for line in self.api_client.stream_generate_content(
            payload, model, api_key
        ):
            if line.startswith("data:"):
                line_content = line[6:]
                response_data = self.response_handler.handle_response(
                    json.loads(line_content), model, stream=True
                )
                text = self._extract_text_from_response(response_data)
                if text and settings.STREAM_OPTIMIZER_ENABLED:
                    async for (
                        optimized_chunk
                    ) in gemini_optimizer.optimize_stream_output(
                        text,
                        lambda t: self._create_char_response(response_data, t),
                        lambda c: "data: " + json.dumps(c) + "\n\n",
                    ):
                        yield optimized_chunk
                else:
                    yield "data: " + json.dumps(response_data) + "\n\n"

    async def stream_generate_content(
        self, model: str, request: GeminiRequest, api_key: str
    ) -> AsyncGenerator[str, None]:
        """流式生成内容"""
        retries = 0
        max_retries = settings.MAX_RETRIES
        payload = _build_payload(model, request)
        is_success = False
        status_code = None
        final_api_key = api_key

        while retries < max_retries:
            request_datetime = datetime.datetime.now()
            start_time = time.perf_counter()
            current_attempt_key = api_key
            final_api_key = current_attempt_key  # Update final key used
            try:
                stream_generator = None
                if settings.GEMINI_FAKE_STREAM_ENABLED:
                    logger.info(
                        f"Using fake stream logic for Vertex model: {model}, Attempt: {retries + 1}"
                    )
                    stream_generator = self._fake_stream_logic_impl(
                        model, payload, current_attempt_key
                    )
                else:
                    logger.info(
                        f"Using real stream logic for Vertex model: {model}, Attempt: {retries + 1}"
                    )
                    stream_generator = self._real_stream_logic_impl(
                        model, payload, current_attempt_key
                    )

                async for chunk_data in stream_generator:
                    yield chunk_data

                logger.info("Streaming completed successfully")
                is_success = True
                status_code = 200
                break
            except Exception as e:
                retries += 1
                is_success = False
                status_code = e.args[0] if len(e.args) > 0 and isinstance(e.args[0], int) else 500
                error_log_msg = e.args[1] if len(e.args) > 1 else str(e)
                logger.warning(
                    f"Streaming API call failed with error: {error_log_msg}. Attempt {retries} of {max_retries}"
                )

                await add_error_log(
                    gemini_key=current_attempt_key,
                    model_name=model,
                    error_type="gemini-chat-stream",
                    error_log=error_log_msg,
                    error_code=status_code,
                    request_msg=(
                        payload if settings.ERROR_LOG_RECORD_REQUEST_BODY else None
                    ),
                    request_datetime=request_datetime,
                )

                api_key = await self.key_manager.handle_vertex_api_failure(
                    current_attempt_key,
                    retries,
                    model_name=model,
                    status_code=status_code,
                    error_msg=error_log_msg,
                )
                if api_key:
                    logger.info(
                        f"Switched to new API key: {redact_key_for_logging(api_key)}"
                    )
                else:
                    logger.error(f"No valid API key available after {retries} retries.")
                    raise

                if retries >= max_retries:
                    logger.error(f"Max retries ({max_retries}) reached for streaming.")
                    raise
            finally:
                end_time = time.perf_counter()
                latency_ms = int((end_time - start_time) * 1000)
                await add_request_log(
                    model_name=model,
                    api_key=final_api_key,
                    is_success=is_success,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    request_time=request_datetime,
                )
