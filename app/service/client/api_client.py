# app/services/chat/api_client.py

import asyncio
import copy
import json
import random
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Optional

import httpx

from app.config.config import settings
from app.core.constants import DEFAULT_TIMEOUT
from app.log.logger import get_api_client_logger

logger = get_api_client_logger()


class ApiClient(ABC):
    """API客户端基类"""

    @abstractmethod
    async def generate_content(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def stream_generate_content(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> AsyncGenerator[str, None]:
        pass


class GeminiApiClient(ApiClient):
    """Gemini API客户端"""

    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url
        self.timeout = timeout

    def _get_real_model(self, model: str) -> str:
        if model.endswith("-search"):
            model = model[:-7]
        if model.endswith("-image"):
            model = model[:-6]
        if model.endswith("-non-thinking"):
            model = model[:-13]
        if "-search" in model and "-non-thinking" in model:
            model = model[:-20]
        return model

    def _prepare_headers(self) -> Dict[str, str]:
        headers = {}
        if settings.CUSTOM_HEADERS:
            headers.update(settings.CUSTOM_HEADERS)
            logger.info(f"Using custom headers: {settings.CUSTOM_HEADERS}")
        return headers

    async def get_models(self, api_key: str) -> Optional[Dict[str, Any]]:
        """获取可用的 Gemini 模型列表"""
        timeout = httpx.Timeout(timeout=5)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers()
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/models?key={api_key}&pageSize=1000"
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"获取模型列表失败: {e.response.status_code}")
                logger.error(e.response.text)
                return None
            except httpx.RequestError as e:
                logger.error(f"请求模型列表失败: {e}")
                return None

    async def generate_content(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        model = self._get_real_model(model)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers()

        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/models/{model}:generateContent?key={api_key}"
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                error_content = response.text
                logger.error(
                    f"API call failed - Status: {response.status_code}, Content: {error_content}"
                )
                raise Exception(response.status_code, error_content)
            response_data = response.json()

            # 检查响应结构的基本信息
            if not response_data.get("candidates"):
                logger.warning("No candidates found in API response")

            return response_data

    async def stream_generate_content(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> AsyncGenerator[str, None]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        model = self._get_real_model(model)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers()
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
            async with client.stream(
                method="POST", url=url, json=payload, headers=headers
            ) as response:
                if response.status_code != 200:
                    error_content = await response.aread()
                    error_msg = error_content.decode("utf-8")
                    raise Exception(response.status_code, error_msg)
                async for line in response.aiter_lines():
                    yield line

    async def stream_generate_content_as_response(
        self,
        payload: Dict[str, Any],
        model: str,
        api_key: str,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """向上游发起流式请求，并在流式响应完全结束或超时后聚合为一个完整的 response 字典。"""
        if timeout is None:
            timeout = getattr(settings, "FAKE_STREAM_STREAMING_TIMEOUT_SECONDS", 120)
        timeout = max(1, timeout)

        async def _consume_stream() -> Dict[str, Any]:
            aggregated_candidates: list[Dict[str, Any]] = []
            final_usage_metadata: Optional[Dict[str, Any]] = None
            final_prompt_feedback: Optional[Dict[str, Any]] = None
            error_info: Optional[Any] = None

            async for line in self.stream_generate_content(payload, model, api_key):
                if not line or not line.startswith("data:"):
                    continue
                chunk_str = line[5:].strip()
                if not chunk_str:
                    continue
                try:
                    chunk = json.loads(chunk_str)
                except Exception:
                    continue

                if "error" in chunk:
                    error_info = chunk["error"]

                if "promptFeedback" in chunk:
                    final_prompt_feedback = chunk["promptFeedback"]

                if "usageMetadata" in chunk:
                    final_usage_metadata = chunk["usageMetadata"]

                candidates = chunk.get("candidates", [])
                for cand in candidates:
                    index = cand.get("index", 0)
                    while len(aggregated_candidates) <= index:
                        aggregated_candidates.append(
                            {
                                "content": {"parts": [], "role": "model"},
                                "finishReason": None,
                                "index": len(aggregated_candidates),
                            }
                        )
                    target_cand = aggregated_candidates[index]

                    if cand.get("finishReason"):
                        target_cand["finishReason"] = cand["finishReason"]

                    cand_parts = cand.get("content", {}).get("parts", [])
                    for p in cand_parts:
                        if not isinstance(p, dict):
                            continue
                        if target_cand["content"]["parts"]:
                            last_p = target_cand["content"]["parts"][-1]
                            if (
                                "text" in p
                                and "text" in last_p
                                and p.get("thought") == last_p.get("thought")
                                and set(p.keys()).issubset({"text", "thought"})
                                and set(last_p.keys()).issubset({"text", "thought"})
                            ):
                                last_p["text"] += p["text"]
                            else:
                                target_cand["content"]["parts"].append(copy.deepcopy(p))
                        else:
                            target_cand["content"]["parts"].append(copy.deepcopy(p))

            res: Dict[str, Any] = {"candidates": aggregated_candidates}
            if final_usage_metadata is not None:
                res["usageMetadata"] = final_usage_metadata
            if final_prompt_feedback is not None:
                res["promptFeedback"] = final_prompt_feedback
            if error_info is not None:
                res["error"] = error_info
            return res

        try:
            return await asyncio.wait_for(_consume_stream(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(
                f"Upstream streaming response timed out after {timeout} seconds for model {model}"
            )
            raise Exception(504, f"Upstream streaming response timed out after {timeout} seconds")

    async def count_tokens(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        model = self._get_real_model(model)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for counting tokens: {proxy_to_use}")

        headers = self._prepare_headers()
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/models/{model}:countTokens?key={api_key}"
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                raise Exception(response.status_code, error_content)
            return response.json()

    async def embed_content(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> Dict[str, Any]:
        """单一嵌入内容生成"""
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        model = self._get_real_model(model)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for embedding: {proxy_to_use}")

        headers = self._prepare_headers()
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/models/{model}:embedContent?key={api_key}"
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                logger.error(
                    f"Embedding API call failed - Status: {response.status_code}, Content: {error_content}"
                )
                raise Exception(response.status_code, error_content)
            return response.json()

    async def batch_embed_contents(
        self, payload: Dict[str, Any], model: str, api_key: str
    ) -> Dict[str, Any]:
        """批量嵌入内容生成"""
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        model = self._get_real_model(model)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for batch embedding: {proxy_to_use}")

        headers = self._prepare_headers()
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/models/{model}:batchEmbedContents?key={api_key}"
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                logger.error(
                    f"Batch embedding API call failed - Status: {response.status_code}, Content: {error_content}"
                )
                raise Exception(response.status_code, error_content)
            return response.json()


class OpenaiApiClient(ApiClient):
    """OpenAI API客户端"""

    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url
        self.timeout = timeout

    def _prepare_headers(self, api_key: str) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {api_key}"}
        if settings.CUSTOM_HEADERS:
            headers.update(settings.CUSTOM_HEADERS)
            logger.info(f"Using custom headers: {settings.CUSTOM_HEADERS}")
        return headers

    async def get_models(self, api_key: str) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers(api_key)
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/openai/models"
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                raise Exception(response.status_code, error_content)
            return response.json()

    async def generate_content(
        self, payload: Dict[str, Any], api_key: str
    ) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        logger.info(
            f"settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY: {settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY}"
        )
        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers(api_key)
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/openai/chat/completions"
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                raise Exception(response.status_code, error_content)
            return response.json()

    async def stream_generate_content(
        self, payload: Dict[str, Any], api_key: str
    ) -> AsyncGenerator[str, None]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)
        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers(api_key)
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/openai/chat/completions"
            async with client.stream(
                method="POST", url=url, json=payload, headers=headers
            ) as response:
                if response.status_code != 200:
                    error_content = await response.aread()
                    error_msg = error_content.decode("utf-8")
                    raise Exception(response.status_code, error_msg)
                async for line in response.aiter_lines():
                    yield line

    async def create_embeddings(
        self, input: str, model: str, api_key: str
    ) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers(api_key)
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/openai/embeddings"
            payload = {
                "input": input,
                "model": model,
            }
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                raise Exception(response.status_code, error_content)
            return response.json()

    async def generate_images(
        self, payload: Dict[str, Any], api_key: str
    ) -> Dict[str, Any]:
        timeout = httpx.Timeout(self.timeout, read=self.timeout)

        proxy_to_use = None
        if settings.PROXIES:
            if settings.PROXIES_USE_CONSISTENCY_HASH_BY_API_KEY:
                proxy_to_use = settings.PROXIES[hash(api_key) % len(settings.PROXIES)]
            else:
                proxy_to_use = random.choice(settings.PROXIES)
            logger.info(f"Using proxy for getting models: {proxy_to_use}")

        headers = self._prepare_headers(api_key)
        async with httpx.AsyncClient(timeout=timeout, proxy=proxy_to_use) as client:
            url = f"{self.base_url}/openai/images/generations"
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                error_content = response.text
                raise Exception(response.status_code, error_content)
            return response.json()
