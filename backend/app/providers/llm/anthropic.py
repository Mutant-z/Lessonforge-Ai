from collections.abc import AsyncIterator
import json
import logging
import re
from typing import Any, TypeVar
from pydantic import BaseModel, ValidationError

from app.core.http_client import build_async_client
from app.core.config import get_settings
from app.providers.llm.base import LLMProvider
from app.providers.llm.streaming import ThinkingStreamParser

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_native_tools = True

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.anthropic.com",
        model_name: str = "claude-3-5-sonnet-20241022",
        timeout_seconds: int = 90,
    ):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.model_name = model_name or "claude-3-5-sonnet-20241022"
        self.timeout = float(timeout_seconds)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async def structured(self, system: str, prompt: str, schema: type[T]) -> T:
        prompt_with_schema = (
            f"{prompt}\n\n请严格返回且仅返回符合以下 JSON Schema 的 JSON 对象：\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt_with_schema}],
        }
        async with build_async_client(url, timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = ""
            for item in data.get("content", []):
                if item.get("type") == "text":
                    raw_text += item.get("text", "")
            
            clean = raw_text.strip()
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
            if fence_match:
                clean = fence_match.group(1).strip()
            else:
                start = clean.find("{")
                end = clean.rfind("}")
                if start != -1 and end != -1 and start < end:
                    clean = clean[start : end + 1].strip()
            
            return schema.model_validate_json(clean)

    async def structured_with_image(self, system: str, prompt: str, image_b64: str,
                                    image_media_type: str, schema: type[T]) -> T:
        """带图像输入的结构化输出：图像 content block + tool_use 强制 JSON 输出。"""
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": image_media_type, "data": image_b64,
                }},
                {"type": "text", "text": prompt},
            ]}],
            "tools": [{"type": "custom", "name": "output",
                       "description": "输出 JSON",
                       "input_schema": schema.model_json_schema()}],
            "tool_choice": {"type": "tool", "name": "output"},
        }
        async with build_async_client(url, timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
        raw = next((item.get("input") for item in data.get("content", [])
                    if item.get("type") == "tool_use"), "")
        return schema.model_validate(raw)

    @staticmethod
    def _multimodal_content(prompt: str, attachments: list[dict[str, str]]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for attachment in attachments:
            mime = attachment.get("mime_type", "application/octet-stream")
            data = attachment.get("data_b64", "")
            if not data:
                continue
            if mime.startswith("image/"):
                blocks.append({"type": "image", "source": {
                    "type": "base64", "media_type": mime, "data": data,
                }})
            elif mime == "application/pdf":
                blocks.append({"type": "document", "source": {
                    "type": "base64", "media_type": mime, "data": data,
                }})
        blocks.append({"type": "text", "text": prompt})
        return blocks

    async def structured_with_attachments(
        self, system: str, prompt: str, attachments: list[dict[str, str]], schema: type[T],
    ) -> T:
        """Anthropic Messages request with native image/PDF blocks."""
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": self._multimodal_content(prompt, attachments)}],
            "tools": [{"type": "custom", "name": "output", "description": "输出 JSON",
                       "input_schema": schema.model_json_schema()}],
            "tool_choice": {"type": "tool", "name": "output"},
        }
        async with build_async_client(url, timeout=self.timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
        raw = next((item.get("input") for item in data.get("content", [])
                    if item.get("type") == "tool_use"), None)
        if raw is None:
            raise ValueError("Anthropic 多模态响应缺少结构化输出")
        return schema.model_validate(raw)

    async def native_agent_decision_with_attachments(
        self,
        system: str,
        prompt: str,
        attachments: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ):
        from app.agent.schemas import AgentDecision, ToolCall

        if not self.api_key:
            return None
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": self._multimodal_content(prompt, attachments)}],
        }
        if tools:
            payload["tools"] = [{
                "type": "custom", "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema") or {},
            } for tool in tools if tool.get("name")]
        try:
            async with build_async_client(f"{self.base_url}/v1/messages", timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/v1/messages", headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        text = ""
        calls: list[ToolCall] = []
        for item in data.get("content", []):
            if item.get("type") == "text":
                text += item.get("text", "")
            elif item.get("type") == "tool_use" and item.get("name"):
                value = item.get("input") if isinstance(item.get("input"), dict) else {}
                calls.append(ToolCall(id=str(item.get("id") or ""), tool_name=item["name"], input=value))
        if calls:
            return AgentDecision(thinking=text[:2000], tool_calls=calls, message="已调用工具继续执行。")
        try:
            return AgentDecision.model_validate_json(text.strip())
        except (ValidationError, json.JSONDecodeError):
            return None

    async def stream_decision_with_attachments(
        self, system: str, prompt: str, attachments: list[dict[str, str]], schema: type[T],
    ):
        """Streaming Anthropic decision with native visual blocks."""
        prompt_with_schema = (
            f"{prompt}\n\n请严格返回且仅返回符合以下 JSON Schema 的 JSON 对象：\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "stream": True,
            "messages": [{"role": "user", "content": self._multimodal_content(prompt_with_schema, attachments)}],
        }
        parser = ThinkingStreamParser()
        buffer: list[str] = []
        try:
            async with build_async_client(url, timeout=self.timeout) as client:
                async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            data = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta" and delta.get("text"):
                                chunk = delta["text"]
                                buffer.append(chunk)
                                thought = parser.feed(chunk)
                                if thought:
                                    yield ("thought_delta", thought)
        except Exception as exc:
            logger.warning("anthropic 多模态 stream_decision 失败，回退 structured：%s", exc)
            yield ("decision_ready", await self.structured_with_attachments(system, prompt, attachments, schema))
            return
        try:
            clean = "".join(buffer).strip()
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
            if match:
                clean = match.group(1).strip()
            else:
                start, end = clean.find("{"), clean.rfind("}")
                if start != -1 and end != -1 and start < end:
                    clean = clean[start:end + 1]
            decision = schema.model_validate_json(clean)
        except (ValidationError, json.JSONDecodeError):
            decision = await self.structured_with_attachments(system, prompt, attachments, schema)
        yield ("decision_ready", decision)

    async def stream_decision(self, system: str, prompt: str, schema: type[T]):
        """流式返回结构化决策：yield thinking 增量 + decision_ready，异常回退 structured。"""
        prompt_with_schema = (
            f"{prompt}\n\n请严格返回且仅返回符合以下 JSON Schema 的 JSON 对象：\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "stream": True,
            "messages": [{"role": "user", "content": prompt_with_schema}],
        }
        parser = ThinkingStreamParser()
        buffer: list[str] = []
        try:
            async with build_async_client(url, timeout=self.timeout) as client:
                async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                chunk = delta.get("text", "")
                                if chunk:
                                    buffer.append(chunk)
                                    thought = parser.feed(chunk)
                                    if thought:
                                        yield ("thought_delta", thought)
        except Exception as exc:  # noqa: BLE001
            logger.warning("anthropic stream_decision 流式失败，回退 structured：%s", exc)
            decision = await self.structured(system, prompt, schema)
            yield ("decision_ready", decision)
            return

        full = "".join(buffer)
        try:
            clean = full.strip()
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean, re.IGNORECASE)
            if fence_match:
                clean = fence_match.group(1).strip()
            else:
                start = clean.find("{")
                end = clean.rfind("}")
                if start != -1 and end != -1 and start < end:
                    clean = clean[start : end + 1].strip()
            decision = schema.model_validate_json(clean)
        except (ValidationError, json.JSONDecodeError) as exc:
            logger.warning("anthropic stream_decision 内容异常，回退 structured：%s", str(exc)[:200])
            decision = await self.structured(system, prompt, schema)
        yield ("decision_ready", decision)

    async def native_agent_decision(
        self,
        system: str,
        prompt: str,
        tools: list[dict[str, Any]],
    ):
        """原生 tool calling（方案 §3.1）：Anthropic tool_use content block。

        响应中的 tool_use block 转换为 AgentDecision.tool_calls；文本内容按
        AgentDecision 结构化解析。协议错误返回 None，由调用方回退结构化协议。
        """
        from app.agent.schemas import AgentDecision, ToolCall

        if not self.api_key:
            return None
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "custom",
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema") or {},
                }
                for tool in tools
                if tool.get("name")
            ]
        url = f"{self.base_url}/v1/messages"
        try:
            async with build_async_client(url, timeout=self.timeout) as client:
                resp = await client.post(url, headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception:  # noqa: BLE001  协议错误 → 回退结构化
            return None
        raw_text = ""
        parsed_tools: list[ToolCall] = []
        for item in data.get("content", []):
            if item.get("type") == "text":
                raw_text += item.get("text", "")
            elif item.get("type") == "tool_use":
                name = item.get("name") or ""
                if not name:
                    continue
                arguments = item.get("input") or {}
                if not isinstance(arguments, dict):
                    arguments = {}
                parsed_tools.append(ToolCall(id=str(item.get("id") or ""), tool_name=name, input=arguments))
        if parsed_tools:
            return AgentDecision(
                thinking=raw_text[:2000],
                tool_calls=parsed_tools,
                message="已调用工具继续执行。",
            )
        clean = raw_text.strip()
        try:
            return AgentDecision.model_validate_json(clean)
        except (ValidationError, json.JSONDecodeError):
            return None

    async def stream_text(self, system: str, prompt: str) -> AsyncIterator[str]:
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": get_settings().llm_max_tokens,
            "system": system,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with build_async_client(url, timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                    except Exception:
                        pass

    async def test_connection(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置 API Key"
        payload = {
            "model": self.model_name,
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "Ping"}],
        }
        try:
            url = f"{self.base_url.rstrip('/')}/v1/messages"
            async with build_async_client(url, timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                if resp.status_code == 200:
                    return True, "Anthropic 协议连通正常！"
                else:
                    return False, f"接口返回 HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
