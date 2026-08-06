"""上下文管理：按 Agent 职责加载相关 Artifact，工具结果回喂下一轮 LLM。

ContextState 持有一批「块」：固定块（蓝图/上游产物/知识库/用户指令/锁定路径/源文件）
+ 有序工具结果块。to_prompt() 序列化为 JSON 区块并做大小截断（先丢最旧工具结果），
保证每个 Agent 只加载与其职责相关的上下文，避免把全部日志/文件发给每次 LLM 请求。
"""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


MAX_BLOCK_CHARS = 6000       # 单块最大字符数
MAX_CONTEXT_CHARS = 48_000   # 单次 prompt 上下文预算（工具结果先丢最旧）
KEEP_TOOL_RESULTS = 12       # 保留最近 N 条工具结果


def estimate_tokens(text: str) -> int:
    """CJK 密集文本的 token 估算（≈ 每字符 0.5 token）。"""
    return max(1, (len(text) + 1) // 2)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class ContextBlock:
    kind: str                # blueprint | upstream | knowledge | user_instruction | locks | source | tool_result | note
    title: str
    payload: Any
    agent_key: str = ""      # 仅 tool_result 使用
    tool_name: str = ""
    tool_call_id: str = ""
    created_order: int = 0

    def serialize(self) -> str:
        if isinstance(self.payload, str):
            body = self.payload
        else:
            try:
                body = json.dumps(self.payload, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                body = str(self.payload)
        return _clip(body, MAX_BLOCK_CHARS)


@dataclass
class ContextState:
    """固定块 + 工具结果块。"""

    course: Any = None
    blueprint: Any = None                # CourseBlueprintSchema 或 dict
    profile: Any = None
    knowledge: dict[str, Any] = field(default_factory=dict)
    source_artifact: Any = None          # 当前 ppt Artifact（修订时）
    user_instruction: str = ""
    locks: list[Any] = field(default_factory=list)
    upstream: dict[str, Any] = field(default_factory=dict)   # {kind: content_json}
    template: dict[str, Any] = field(default_factory=dict)   # resolve_ppt_template 结果
    extra_notes: list[str] = field(default_factory=list)
    tool_results: list[ContextBlock] = field(default_factory=list)
    _order: int = 0
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def append_tool_result(self, tool_call_id: str, agent_key: str, tool_name: str, output: dict[str, Any], error: str | None = None):
        self._order += 1
        self.tool_results.append(ContextBlock(
            kind="tool_result",
            title=f"{tool_name}({tool_call_id[:8]})",
            payload={"ok": error is None, "output": output, "error": error} if error else {"ok": True, "output": output},
            agent_key=agent_key,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            created_order=self._order,
        ))
        # 保留最近 N 条工具结果
        if len(self.tool_results) > KEEP_TOOL_RESULTS:
            self.tool_results = self.tool_results[-KEEP_TOOL_RESULTS:]

    def add_note(self, text: str):
        self.extra_notes.append(text)

    def has_tool_result(self, tool_name: str) -> bool:
        return any(block.tool_name == tool_name for block in self.tool_results)

    def get_tool_output(self, tool_name: str) -> Any:
        """取最近一次指定工具成功执行的 output（供 mock Agent 读取工具结果）。"""
        for block in reversed(self.tool_results):
            if block.tool_name == tool_name:
                payload = block.payload
                if isinstance(payload, dict) and payload.get("ok"):
                    return payload.get("output")
                return None
        return None

    def _fixed_blocks(self) -> list[ContextBlock]:
        blocks: list[ContextBlock] = []
        if self.blueprint is not None:
            blocks.append(ContextBlock("blueprint", "已批准课程蓝图", self.blueprint if isinstance(self.blueprint, dict) else self.blueprint.model_dump()))
        for kind, value in self.upstream.items():
            blocks.append(ContextBlock("upstream", f"上游产物 {kind}", value))
        if self.source_artifact is not None:
            blocks.append(ContextBlock("source", "当前 PPT 内容", getattr(self.source_artifact, "content_json", self.source_artifact)))
        if self.template:
            blocks.append(ContextBlock("template", "模板设计系统", self.template))
        if self.knowledge:
            blocks.append(ContextBlock("knowledge", "PPT 设计知识库", self.knowledge))
        if self.user_instruction:
            blocks.append(ContextBlock("user_instruction", "用户/教师指令", self.user_instruction))
        if self.locks:
            paths = [getattr(lock, "json_path", None) or (lock.get("json_path") if isinstance(lock, dict) else None) for lock in self.locks]
            blocks.append(ContextBlock("locks", "锁定路径", [p for p in paths if p]))
        if self.extra_notes:
            blocks.append(ContextBlock("note", "运行备注", self.extra_notes))
        return blocks

    def to_prompt(self, agent_key: str) -> str:
        """把相关上下文序列化为单段 JSON，超出预算时先丢最旧工具结果。"""
        fixed = self._fixed_blocks()
        tool_blocks = list(self.tool_results)
        parts: list[str] = []
        used = 0
        for block in fixed:
            text = block.serialize()
            used += len(text)
            parts.append(f"## {block.kind}: {block.title}\n{text}")
        for block in reversed(tool_blocks):
            text = block.serialize()
            if used + len(text) > MAX_CONTEXT_CHARS:
                continue
            used += len(text)
            parts.append(f"## tool_result (agent={block.agent_key}, tool={block.tool_name})\n{text}")
        return "\n".join(parts)

    def context_hash(self) -> str:
        return hashlib.sha256(self.to_prompt("").encode("utf-8")).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        return {
            "user_instruction": self.user_instruction,
            "tool_results": [b.model_dump() if hasattr(b, "model_dump") else self._block_dict(b) for b in self.tool_results],
            "extra_notes": self.extra_notes,
        }

    @staticmethod
    def _block_dict(b: ContextBlock) -> dict[str, Any]:
        return {"kind": b.kind, "title": b.title, "payload": b.payload, "agent_key": b.agent_key, "tool_name": b.tool_name}

    def restore(self, data: dict[str, Any] | None):
        if not data:
            return
        self.user_instruction = data.get("user_instruction") or self.user_instruction
        self.extra_notes = list(data.get("extra_notes") or [])
        restored: list[ContextBlock] = []
        for item in data.get("tool_results") or []:
            restored.append(ContextBlock(
                kind=item.get("kind", "tool_result"), title=item.get("title", "tool_result"),
                payload=item.get("payload"), agent_key=item.get("agent_key", ""),
                tool_name=item.get("tool_name", ""), tool_call_id=item.get("tool_call_id", ""),
            ))
        if restored:
            self.tool_results = restored
