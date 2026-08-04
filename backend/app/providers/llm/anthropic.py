from collections.abc import AsyncIterator
import json
import re
from typing import TypeVar
import httpx
from pydantic import BaseModel

from app.providers.llm.base import LLMProvider

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

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
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": prompt_with_schema}],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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

    async def stream_text(self, system: str, prompt: str) -> AsyncIterator[str]:
        url = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": 4096,
            "system": system,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{self.base_url.rstrip('/')}/v1/messages", json=payload, headers=self._headers())
                if resp.status_code == 200:
                    return True, "Anthropic 协议连通正常！"
                else:
                    return False, f"接口返回 HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
