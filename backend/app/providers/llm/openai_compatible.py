import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.http_client import build_async_client
from app.providers.llm.base import LLMProvider, LLMProviderError, T


class ConnectionProbe(BaseModel):
    ok: bool


CONTENT_ERROR_CODES = {
    "upstream_empty_response",
    "upstream_invalid_response",
    "upstream_empty_content",
    "upstream_invalid_json",
    "upstream_schema_mismatch",
}


def _retryable_provider_error(exc: BaseException) -> bool:
    return isinstance(exc, LLMProviderError) and exc.retryable


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model_name: str | None = None, timeout_seconds: int | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.base_url = base_url or settings.openai_base_url
        self.model_name = model_name or settings.openai_model
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _response_error(
        self,
        code: str,
        message: str,
        response: httpx.Response | None = None,
        *,
        retryable: bool = False,
    ) -> LLMProviderError:
        return LLMProviderError(
            code=code,
            user_message=message,
            retryable=retryable,
            status_code=response.status_code if response else None,
            content_type=response.headers.get("content-type", "") if response else "",
            response_length=len(response.content) if response else 0,
            request_id=(
                response.headers.get("x-request-id", "")
                or response.headers.get("request-id", "")
                if response
                else ""
            ),
        )

    @retry(
        retry=retry_if_exception(_retryable_provider_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=8),
        reraise=True,
    )
    async def _post_chat(self, payload: dict[str, Any]) -> tuple[dict[str, Any], httpx.Response]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        try:
            async with build_async_client(url, timeout=self.timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise self._response_error(
                "upstream_timeout",
                "模型服务响应超时，请稍后重试或检查模型配置。",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise self._response_error(
                "upstream_http_error",
                "无法连接模型服务，请检查 Base URL、网络或网关状态。",
                retryable=True,
            ) from exc

        if not response.is_success:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise self._response_error(
                "upstream_http_error",
                f"模型服务返回 HTTP {response.status_code}，请检查模型配置或稍后重试。",
                response,
                retryable=retryable,
            )
        if not response.content or not response.text.strip():
            raise self._response_error(
                "upstream_empty_response",
                "模型服务返回了空响应，请检查 Base URL、模型名称或网关兼容性。",
                response,
            )
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise self._response_error(
                "upstream_invalid_response",
                "模型服务返回的响应格式不兼容，请检查 Base URL 或接口协议。",
                response,
            ) from exc
        if not isinstance(data, dict):
            raise self._response_error(
                "upstream_invalid_response",
                "模型服务返回的响应结构不兼容，请检查所选模型与接口协议。",
                response,
            )
        return data, response

    def _content_from_response(self, data: dict[str, Any], response: httpx.Response) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise self._response_error(
                "upstream_invalid_response",
                "模型服务返回的响应结构不兼容，请检查所选模型与接口协议。",
                response,
            ) from exc

        if isinstance(content, list):
            content = "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
            )
        if not isinstance(content, str) or not content.strip():
            raise self._response_error(
                "upstream_empty_content",
                "模型服务未返回可解析内容，请检查模型名称或结构化输出兼容性。",
                response,
            )
        return content.strip()

    @staticmethod
    def _strip_json_fence(content: str) -> str:
        clean = content.strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()

        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1 and start < end:
            return clean[start : end + 1].strip()

        return clean

    async def _structured_request(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        *,
        json_mode: bool,
    ) -> T:
        settings = get_settings()
        if not self.api_key:
            raise LLMProviderError("upstream_http_error", "当前模型未配置 API Key，请先完成模型设置。")
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        structured_prompt = f"{prompt}\n\n请仅返回符合以下 JSON Schema 的 JSON 对象：\n{schema_json}"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": structured_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": settings.llm_max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data, response = await self._post_chat(payload)
        content = self._strip_json_fence(self._content_from_response(data, response))
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            raise self._response_error(
                "upstream_invalid_json",
                "模型返回的内容不是有效 JSON，请检查模型的结构化输出能力。",
                response,
            ) from exc
        try:
            return schema.model_validate(decoded)
        except ValidationError as exc:
            raise self._response_error(
                "upstream_schema_mismatch",
                "模型返回的需求结构不完整，请重试或切换支持结构化输出的模型。",
                response,
            ) from exc

    async def structured(self, system: str, prompt: str, schema: type[T]) -> T:
        try:
            return await self._structured_request(system, prompt, schema, json_mode=True)
        except LLMProviderError as exc:
            if exc.code not in CONTENT_ERROR_CODES:
                raise
        try:
            return await self._structured_request(system, prompt, schema, json_mode=False)
        except LLMProviderError as exc:
            if exc.code not in CONTENT_ERROR_CODES:
                raise
            recovery_prompt = (
                prompt
                + "\n\n上一次返回为空或不符合结构。请直接输出一个紧凑的 JSON 对象，"
                "不要输出分析、Markdown 代码围栏或额外说明。"
            )
            return await self._structured_request(system, recovery_prompt, schema, json_mode=False)

    async def stream_text(self, system: str, prompt: str):
        if not self.api_key:
            raise LLMProviderError("upstream_http_error", "当前模型未配置 API Key，请先完成模型设置。")
        payload = {
            "model": self.model_name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.3,
            "stream": True,
        }
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        async with build_async_client(url, timeout=self.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)["choices"][0]["delta"].get("content", "")
                    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                        chunk = ""
                    if chunk:
                        yield chunk

    async def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 API Key"
        try:
            result = await self.structured(
                "你是模型连接探测器。",
                '返回 JSON：{"ok": true}',
                ConnectionProbe,
            )
            if result.ok:
                return True, "模型连接及结构化输出能力正常！"
            return False, "模型已响应，但结构化探测结果不正确。"
        except LLMProviderError as exc:
            return False, exc.user_message
        except Exception:
            return False, "模型连接测试异常，请检查模型配置或服务日志。"
