"""流水线事件发射：每条事件同时写入 generation_events（SSE 传输，全局续传游标）
与 pipeline_events（流水线明细，sequence 镜像 generation_events.id）。

复用 course_task_service._publish_task_event 的「短事务逐条提交」模式，
让 SSE 端点立即观察到事件。
"""
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import AgentMessage, GenerationRun, GenerationEvent, PipelineEvent, PipelineRun

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
        # —— 对话单线（整轮 pipeline 一条「教学 Agent」assistant 消息）——
        self._dialogue_message_id: str | None = None
        self._dialogue_buffer: list[str] = []
        self._dialogue_last_flush: float = 0.0
        self._dialogue_last_agent: str = ""   # 换 Agent 时插入换行分隔
        self._dialogue_mirror_status: bool = True   # False：status_delta 不镜像（message 触发正文走最终回复）

    @staticmethod
    async def for_run(
        generation_run: GenerationRun,
        pipeline_run: PipelineRun | None = None,
        task_type: str | None = None,
    ) -> "PipelineEventEmitter":
        """构造事件发射器。

        ``task_type`` 默认 "ppt" 保持 PPT 行为不变；教学设计等新任务传入自己的
        task_type（如 "lesson_plan"），事件协议本身与任务类型无关。
        """
        return PipelineEventEmitter(
            pipeline_run_id=pipeline_run.id if pipeline_run else "",
            generation_run_id=generation_run.id,
            course_id=generation_run.course_id,
            task_id=getattr(generation_run, "course_task_id", None),
            task_type=task_type or "ppt",
        )

    def _base(self, **data: Any) -> dict[str, Any]:
        # `sequence` is scoped to this emitter and gives clients a stable
        # ordering hint in addition to the global GenerationEvent id.
        payload = {
            "course_id": self.course_id,
            "run_id": self.generation_run_id,
            "pipeline_run_id": self.pipeline_run_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "sequence": self._clock,
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
            payload = {**payload, "sequence": sequence, "event_id": sequence}
            gen.data_json = payload
            if self.pipeline_run_id:
                db.add(PipelineEvent(
                    pipeline_run_id=self.pipeline_run_id, event_type=event_type,
                    sequence=sequence, data_json={**payload, "generation_event_id": sequence},
                ))
            await db.commit()
            return sequence

    async def pipeline_started(self, trigger_type: str = ""):
        return await self.emit("pipeline_started", trigger_type=trigger_type,
                               status="running")

    async def emit_domain(
        self,
        event_type: str,
        *,
        message: str = "",
        agent: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
        slide: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ):
        """Emit the canonical dotted event envelope alongside legacy events."""
        return await self.emit(
            event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            message=message[:1000], agent=agent or {}, progress=progress or {},
            artifact=artifact or {}, slide=slide or {}, payload=payload or {},
            protocol_version="1.0",
        )

    async def skill_completed(self, name: str, *, ok: bool = True, summary: str = ""):
        return await self.emit_domain(
            "skill.completed" if ok else "skill.failed",
            message=summary or (f"Skill {name} 已完成" if ok else f"Skill {name} 执行失败"),
            payload={"name": name, "ok": ok},
        )

    # ---- 便捷方法 ----
    async def agent_started(self, agent_key: str, agent_label: str, step_index: int, progress: int | None = None):
        return await self.emit("agent_started", agent_key=agent_key, agent_label=agent_label,
                               node_name=agent_key, agent_type=agent_key, step_index=step_index, progress=progress)

    async def agent_completed(self, agent_key: str, summary: str, duration_ms: int = 0,
                              artifact_id: str | None = None, progress: int | None = None):
        return await self.emit("agent_completed", agent_key=agent_key, node_name=agent_key,
                               agent_type=agent_key, summary=summary, duration_ms=duration_ms,
                               artifact_id=artifact_id, progress=progress)

    async def agent_status_delta(self, agent_key: str, text: str, *, message_id: str | None = None):
        """Publish a user-visible execution summary, never raw chain-of-thought."""
        gen_id = await self.emit("agent_status_delta", agent_key=agent_key, node_name=agent_key,
                                 agent_type=agent_key, text=text[:2000],
                                 message_id=message_id or f"status-{self.generation_run_id}-{agent_key}")
        # 对话单线镜像：可见摘要同步追加到「教学 Agent」气泡正文（节流 flush）
        if self._dialogue_message_id and self._dialogue_mirror_status:
            if self._dialogue_last_agent and self._dialogue_last_agent != agent_key and self._dialogue_buffer:
                self._dialogue_buffer.append("\n\n")
            self._dialogue_last_agent = agent_key
            await self._dialogue_append(text)
        return gen_id

    async def agent_status_completed(self, agent_key: str, text: str = ""):
        gen_id = await self.emit("agent_status_completed", agent_key=agent_key, node_name=agent_key,
                                 agent_type=agent_key, text=text[:2000])
        if self._dialogue_message_id and self._dialogue_mirror_status:
            await self._dialogue_flush()
            if text:
                await self._dialogue_append(text)
        return gen_id

    async def tool_call_started(self, agent_key: str, tool_name: str, tool_call_id: str, input_summary: str = "", input_json: dict[str, Any] | None = None, model_call_id: str = ""):
        return await self.emit("tool_call_started", agent_key=agent_key, node_name=agent_key, agent_type=agent_key,
                               tool_name=tool_name, tool_call_id=tool_call_id, model_call_id=model_call_id,
                               input_summary=input_summary, input_json=input_json or {})

    async def tool_call_delta(self, agent_key: str, tool_name: str, tool_call_id: str, delta_json_chunk: str):
        return await self.emit("tool_call_delta", agent_key=agent_key, node_name=agent_key, agent_type=agent_key,
                               tool_name=tool_name, tool_call_id=tool_call_id, chunk=delta_json_chunk)

    async def tool_call_completed(self, agent_key: str, tool_name: str, tool_call_id: str, ok: bool,
                                  output_summary: str = "", duration_ms: int = 0, error: str | None = None,
                                  output_json: dict[str, Any] | None = None, model_call_id: str = "",
                                  error_code: str | None = None, retryable: bool = False):
        return await self.emit("tool_call_completed", agent_key=agent_key, node_name=agent_key, agent_type=agent_key,
                               tool_name=tool_name, tool_call_id=tool_call_id, model_call_id=model_call_id, ok=ok,
                               output_summary=output_summary, duration_ms=duration_ms, error=error,
                               error_code=error_code, retryable=retryable, output_json=output_json or {})

    async def tool_call_delta(self, agent_key: str, tool_name: str, tool_call_id: str, text: str):
        return await self.emit("tool_call_delta", agent_key=agent_key, node_name=agent_key,
                               agent_type=agent_key, tool_name=tool_name,
                               tool_call_id=tool_call_id, text=text[:4000])

    async def artifact_started(self, artifact_type: str, artifact_id: str, *,
                               producer_agent: str = "", slide_index: int | None = None):
        return await self.emit("artifact_started", artifact_type=artifact_type,
                               artifact_id=artifact_id, producer_agent=producer_agent,
                               slide_index=slide_index)

    async def artifact_patch(self, artifact_id: str, artifact_type: str,
                             patch: list[dict[str, Any]], summary: str = "",
                             slide_index: int | None = None):
        return await self.emit("artifact_patch", artifact_id=artifact_id,
                               artifact_type=artifact_type, patch=patch[:100],
                               summary=summary[:500], slide_index=slide_index)

    async def qa_issue_found(self, issue: dict[str, Any]):
        return await self.emit("qa_issue_found", issue={key: issue.get(key) for key in (
            "severity", "slide_id", "rule_id", "message", "target_agent")})

    async def agent_text_delta(self, agent_key: str, text_chunk: str):
        return await self.emit("agent_text_delta", agent_key=agent_key, node_name=agent_key, agent_type=agent_key, text=text_chunk)

    async def artifact_diff_emitted(self, artifact_id: str, artifact_type: str, hunks: list[dict[str, Any]], summary: str = ""):
        return await self.emit("artifact_diff_emitted", artifact_id=artifact_id, artifact_type=artifact_type, hunks=hunks, summary=summary)

    async def artifact_created(self, artifact_type: str, artifact_id: str, name: str, version: int,
                               producer_agent: str = "", file_path: str = ""):
        return await self.emit("artifact_created", artifact_type=artifact_type, artifact_id=artifact_id,
                               name=name, version=version, producer_agent=producer_agent, file_path=file_path)

    async def asset_generated(self, asset_type: str, file_path: str, mime_type: str = "image/png",
                              width: int = 0, height: int = 0, prompt: str = "",
                              *, asset_id: str = "", provider: str = "", degraded: bool = False,
                              degraded_reason: str = ""):
        return await self.emit("asset_generated", asset_type=asset_type, file_path=file_path,
                               mime_type=mime_type, width=width, height=height, prompt=prompt[:300],
                               asset_id=asset_id, provider=provider, degraded=degraded,
                               degraded_reason=degraded_reason[:300])

    async def qa_completed(self, score: float, issues_count: int, severity_counts: dict[str, int],
                           round_: int = 0, degraded: bool = False, issues: list[dict[str, Any]] | None = None,
                           *, qa_level: str = "geometry", geometry_score: float | None = None,
                           visual_quality_score: float | None = None, improvement_delta: float = 0.0):
        return await self.emit("qa_completed", score=score, issues_count=issues_count,
                               severity_counts=severity_counts, round=round_, degraded=degraded,
                               issues=(issues or [])[:12], qa_level=qa_level,
                               geometry_score=geometry_score,
                               visual_quality_score=visual_quality_score,
                               improvement_delta=improvement_delta)

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
        self._clock += 1
        payload = self._base(text=text, agent_key=agent_key, node_name=agent_key,
                             agent_type=agent_key,
                             message_id=f"status-{self.generation_run_id}-{agent_key}")
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

    # ---- 对话单线（「教学 Agent」assistant 消息，整轮 pipeline 一条） ----
    # 事件只写 generation_events（SSE），不写 pipeline_events —— 与
    # course_task_service._emit 一致，保持它们不进流水线明细表。
    # 正文 = agent_status_delta 可见摘要的节流镜像（非 CoT），每 Agent 边界强制落库。

    def _emit_dialogue(self, db, event_type: str, **data: Any) -> None:
        """在当前事务内写一条只进 generation_events 的对话事件。"""
        self._clock += 1
        payload = self._base(**data)
        gen = GenerationEvent(run_id=self.generation_run_id, event_type=event_type, data_json=payload)
        db.add(gen)

    async def agent_message_started(self, title: str = "教学 Agent", *, mirror_status: bool = True) -> str | None:
        """创建/复用一条 streaming 的 assistant 对话消息，开启对话单线。

        暂停/恢复场景：命中已有消息且已有 content 时保留正文（不重置），
        恢复后 deltas 在服务端累积内容上续写。
        mirror_status=False：status_delta 不镜像进正文（message 触发时正文走最终回复）。
        """
        if not self.generation_run_id:
            return None
        async with SessionLocal() as db:
            existing = await db.scalar(select(AgentMessage).where(
                AgentMessage.run_id == self.generation_run_id,
                AgentMessage.role == "assistant",
            ))
            resume_content = ""
            if existing is not None:
                resume_content = existing.content or ""
                existing.status = "streaming"
            else:
                existing = AgentMessage(
                    course_id=self.course_id,
                    task_id=self.task_id,
                    run_id=self.generation_run_id,
                    module_type=self.task_type or "ppt",
                    role="assistant",
                    content="",
                    status="streaming",
                )
                db.add(existing)
                await db.flush()
            message_id = existing.id
            self._dialogue_message_id = message_id
            self._dialogue_buffer = []
            self._dialogue_last_flush = time.monotonic()
            self._dialogue_last_agent = ""
            self._dialogue_mirror_status = mirror_status
            self._emit_dialogue(db, "agent_message_started", title=title, message={
                "id": message_id,
                "role": "assistant",
                "content": resume_content,
                "run_id": self.generation_run_id,
                "status": "streaming",
            })
            await db.commit()
        return message_id

    async def agent_message_append(self, text: str) -> None:
        """非镜像路径追加一段正文并立即落库（message 触发：最终回复作为对话正文流式推送）。"""
        if not self._dialogue_message_id or not text:
            return
        await self._dialogue_append(text)
        await self._dialogue_flush()

    async def _dialogue_append(self, text: str) -> None:
        """把一段可见摘要增量写入对话缓冲，按 24 字符 / 0.15s 阈值节流落库。"""
        if not self._dialogue_message_id or not text:
            return
        self._dialogue_buffer.append(text)
        size = sum(len(chunk) for chunk in self._dialogue_buffer)
        now = time.monotonic()
        if size >= 24 or now - self._dialogue_last_flush >= 0.15:
            await self._dialogue_flush()

    async def _dialogue_flush(self) -> None:
        """把对话缓冲落库：AgentMessage.content 追加 + 发 agent_message_delta（短事务）。"""
        if not self._dialogue_message_id or not self._dialogue_buffer:
            return
        text = "".join(self._dialogue_buffer)
        self._dialogue_buffer = []
        self._dialogue_last_flush = time.monotonic()
        async with SessionLocal() as db:
            row = await db.get(AgentMessage, self._dialogue_message_id)
            if row is not None:
                row.content = (row.content or "") + text
            self._emit_dialogue(db, "agent_message_delta", message_id=self._dialogue_message_id,
                                delta=text, reset=False)
            await db.commit()

    async def agent_message_completed(self, summary: str | None = None,
                                      sub_agents: list[dict] | None = None,
                                      artifact_id: str | None = None) -> None:
        """完成对话单线：强制 flush，可选整段替换正文，写 completed 事件并清空镜像状态。"""
        if not self._dialogue_message_id:
            return None
        await self._dialogue_flush()
        async with SessionLocal() as db:
            row = await db.get(AgentMessage, self._dialogue_message_id)
            if row is None:
                self._dialogue_message_id = None
                return None
            final_content = summary if summary is not None else (row.content or "")
            if summary is not None:
                row.content = summary
                # 先发整段替换让前端流式内容同步，再发 completed
                self._emit_dialogue(db, "agent_message_delta", message_id=row.id,
                                    delta=summary, reset=True)
            row.status = "completed"
            if artifact_id is not None:
                row.artifact_id = artifact_id
            self._emit_dialogue(db, "agent_message_completed", message={
                "id": row.id,
                "role": "assistant",
                "content": final_content,
                "run_id": self.generation_run_id,
                "status": "completed",
                "artifact_id": artifact_id,
            }, sub_agents=sub_agents or [])
            await db.commit()
        self._dialogue_message_id = None
        return None

    async def agent_message_failed(self, message: str = "") -> None:
        """失败收尾：消息置 failed，发 agent_message_failed，清空镜像状态。"""
        message_id = self._dialogue_message_id
        if not message_id:
            return None
        self._dialogue_message_id = None
        async with SessionLocal() as db:
            row = await db.get(AgentMessage, message_id)
            if row is not None:
                row.status = "failed"
            self._emit_dialogue(db, "agent_message_failed", message_id=message_id,
                                error=message[:200])
            await db.commit()
        return None


def emit_task_elapsed(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)
