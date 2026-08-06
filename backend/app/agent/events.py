"""流水线事件发射：每条事件同时写入 generation_events（SSE 传输，全局续传游标）
与 pipeline_events（流水线明细，sequence 镜像 generation_events.id）。

复用 course_task_service._publish_task_event 的「短事务逐条提交」模式，
让 SSE 端点立即观察到事件。
"""
import time
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import GenerationRun, GenerationEvent, PipelineEvent, PipelineRun

# 思考文本增量缓冲（按 generation_run_id）：高频 chunk 先入内存，按时间/大小阈值批量落库，
# 避免每个 token 一次短事务写库拖慢流式。缓冲只写入 generation_events（SSE）+ pipeline_events（明细），
# 不做每 chunk 的实时提交。
_THOUGHT_FLUSH_INTERVAL = 0.12   # 秒
_THOUGHT_FLUSH_CHARS = 400       # 字符
_THOUGHT_BUFFERS: dict[str, dict[str, Any]] = {}


class PipelineEventEmitter:
    """向现有 task-events SSE 传输发布流水线事件。"""

    def __init__(self, pipeline_run_id: str, generation_run_id: str, course_id: str, task_id: str | None, task_type: str | None):
        self.pipeline_run_id = pipeline_run_id
        self.generation_run_id = generation_run_id
        self.course_id = course_id
        self.task_id = task_id
        self.task_type = task_type
        self._clock = 0

    @staticmethod
    async def for_run(generation_run: GenerationRun, pipeline_run: PipelineRun | None = None) -> "PipelineEventEmitter":
        return PipelineEventEmitter(
            pipeline_run_id=pipeline_run.id if pipeline_run else "",
            generation_run_id=generation_run.id,
            course_id=generation_run.course_id,
            task_id=getattr(generation_run, "course_task_id", None),
            task_type="ppt",
        )

    def _base(self, **data: Any) -> dict[str, Any]:
        payload = {
            "course_id": self.course_id,
            "run_id": self.generation_run_id,
            "pipeline_run_id": self.pipeline_run_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            **data,
        }
        return payload

    async def emit(self, event_type: str, **data: Any) -> int:
        """短事务写入 generation_events + pipeline_events，返回 generation_events.id。"""
        self._clock += 1
        payload = self._base(**data)
        async with SessionLocal() as db:
            gen = GenerationEvent(run_id=self.generation_run_id, event_type=event_type, data_json=payload)
            db.add(gen)
            await db.flush()
            sequence = int(gen.id)
            if self.pipeline_run_id:
                db.add(PipelineEvent(
                    pipeline_run_id=self.pipeline_run_id, event_type=event_type,
                    sequence=sequence, data_json={**payload, "generation_event_id": sequence},
                ))
            await db.commit()
            return sequence

    # ---- 便捷方法 ----
    async def agent_started(self, agent_key: str, agent_label: str, step_index: int, progress: int | None = None):
        return await self.emit("agent_started", agent_key=agent_key, agent_label=agent_label,
                               node_name=agent_key, agent_type=agent_key, step_index=step_index, progress=progress)

    async def agent_completed(self, agent_key: str, summary: str, duration_ms: int = 0,
                              artifact_id: str | None = None, progress: int | None = None):
        return await self.emit("agent_completed", agent_key=agent_key, node_name=agent_key,
                               agent_type=agent_key, summary=summary, duration_ms=duration_ms,
                               artifact_id=artifact_id, progress=progress)

    async def tool_call_started(self, agent_key: str, tool_name: str, tool_call_id: str, input_summary: str = "", input_json: dict[str, Any] | None = None):
        return await self.emit("tool_call_started", agent_key=agent_key, node_name=agent_key, agent_type=agent_key,
                               tool_name=tool_name, tool_call_id=tool_call_id, input_summary=input_summary, input_json=input_json or {})

    async def tool_call_delta(self, agent_key: str, tool_name: str, tool_call_id: str, delta_json_chunk: str):
        return await self.emit("tool_call_delta", agent_key=agent_key, node_name=agent_key, agent_type=agent_key,
                               tool_name=tool_name, tool_call_id=tool_call_id, chunk=delta_json_chunk)

    async def tool_call_completed(self, agent_key: str, tool_name: str, tool_call_id: str, ok: bool,
                                  output_summary: str = "", duration_ms: int = 0, error: str | None = None, output_json: dict[str, Any] | None = None):
        return await self.emit("tool_call_completed", agent_key=agent_key, node_name=agent_key, agent_type=agent_key,
                               tool_name=tool_name, tool_call_id=tool_call_id, ok=ok,
                               output_summary=output_summary, duration_ms=duration_ms, error=error, output_json=output_json or {})

    async def agent_text_delta(self, agent_key: str, text_chunk: str):
        return await self.emit("agent_text_delta", agent_key=agent_key, node_name=agent_key, agent_type=agent_key, text=text_chunk)

    async def artifact_diff_emitted(self, artifact_id: str, artifact_type: str, hunks: list[dict[str, Any]], summary: str = ""):
        return await self.emit("artifact_diff_emitted", artifact_id=artifact_id, artifact_type=artifact_type, hunks=hunks, summary=summary)

    async def artifact_created(self, artifact_type: str, artifact_id: str, name: str, version: int,
                               producer_agent: str = "", file_path: str = ""):
        return await self.emit("artifact_created", artifact_type=artifact_type, artifact_id=artifact_id,
                               name=name, version=version, producer_agent=producer_agent, file_path=file_path)

    async def asset_generated(self, asset_type: str, file_path: str, mime_type: str = "image/png",
                              width: int = 0, height: int = 0, prompt: str = ""):
        return await self.emit("asset_generated", asset_type=asset_type, file_path=file_path,
                               mime_type=mime_type, width=width, height=height, prompt=prompt[:300])

    async def qa_completed(self, score: float, issues_count: int, severity_counts: dict[str, int],
                           round_: int = 0, degraded: bool = False, issues: list[dict[str, Any]] | None = None):
        return await self.emit("qa_completed", score=score, issues_count=issues_count,
                               severity_counts=severity_counts, round=round_, degraded=degraded,
                               issues=(issues or [])[:12])

    async def revision_started(self, round_: int, max_rounds: int, reason: str = "", target_agents: list[str] | None = None):
        return await self.emit("revision_started", round=round_, max_rounds=max_rounds, reason=reason[:500],
                               target_agents=target_agents or [])

    async def revision_completed(self, round_: int, applied_changes: list[str] | None = None):
        return await self.emit("revision_completed", round=round_, applied_changes=applied_changes or [])

    async def task_paused(self, reason: str = "", checkpoint_step: int = 0):
        return await self.emit("task_paused", reason=reason, checkpoint_step=checkpoint_step)

    async def task_resumed(self, resume_from_step: int = 0):
        return await self.emit("task_resumed", resume_from_step=resume_from_step)

    async def pipeline_completed(self, artifact_id: str | None = None, llm_calls: int = 0, tokens: int = 0):
        return await self.emit("pipeline_completed", artifact_id=artifact_id, llm_calls=llm_calls, tokens=tokens)

    async def pipeline_failed(self, error: str = ""):
        return await self.emit("pipeline_failed", error=error[:500])

    async def pipeline_limit_reached(self, error: str = ""):
        return await self.emit("pipeline_limit_reached", error=error[:500])

    # ---- 流式思考增量（缓冲批量落库，避免逐 token 写库） ----
    async def agent_thought_chunk(self, agent_key: str, text: str, *, flush_now: bool = False) -> None:
        """推送一段思考文本增量。

        首个 chunk 立即落库（保证前端 500ms 内看到首个 token），后续按时间/大小阈值批量落库。
        """
        buf = _THOUGHT_BUFFERS.setdefault(self.generation_run_id, {
            "chunks": [], "agent_key": agent_key, "last_flush": time.monotonic(),
        })
        buf["agent_key"] = agent_key
        first_chunk = not buf["chunks"]
        buf["chunks"].append(text)
        size = sum(len(chunk) for chunk in buf["chunks"])
        now = time.monotonic()
        if flush_now or first_chunk or size >= _THOUGHT_FLUSH_CHARS or now - buf["last_flush"] >= _THOUGHT_FLUSH_INTERVAL:
            await self._flush_thought(buf)

    async def _flush_thought(self, buf: dict[str, Any]) -> None:
        if not buf["chunks"]:
            return
        text = "".join(buf["chunks"])
        buf["chunks"] = []
        buf["last_flush"] = time.monotonic()
        agent_key = buf["agent_key"] or ""
        payload = self._base(text=text, agent_key=agent_key, node_name=agent_key, agent_type=agent_key)
        async with SessionLocal() as db:
            gen = GenerationEvent(run_id=self.generation_run_id, event_type="agent_thought_chunk", data_json=payload)
            db.add(gen)
            await db.flush()
            if self.pipeline_run_id:
                db.add(PipelineEvent(
                    pipeline_run_id=self.pipeline_run_id, event_type="agent_thought_chunk",
                    sequence=int(gen.id), data_json={**payload, "generation_event_id": int(gen.id)},
                ))
            await db.commit()

    async def flush_thought(self) -> None:
        """排空并删除该运行的思考缓冲（Agent 边界 / 流水线结束调用）。"""
        buf = _THOUGHT_BUFFERS.pop(self.generation_run_id, None)
        if buf:
            await self._flush_thought(buf)


def emit_task_elapsed(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)
