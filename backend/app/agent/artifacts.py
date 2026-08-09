"""流水线 Artifact 图管理。

- 版本化：同一 (run_id, artifact_type, name) 新版本将旧版本标 superseded
- 依赖边：parent_id + dependencies_json（artifact id 列表）
- 文件落盘：把 artifact 写入工作目录（analysis/content/plans/assets/drafts/qa/output）
"""
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import PipelineArtifact, PipelineRun

# 工作目录子目录映射（对齐需求 §14 任务工作目录）
_TYPE_DIRS: dict[str, str] = {
    "pipeline_plan": "plans",
    "source_snapshot": "content",
    "presentation_narrative": "plans",
    "design_system": "analysis",
    "slide_content": "plans",
    "slide_layout": "plans",
    "visual_plan": "plans",
    "visual_asset": "assets",
    "presentation_file": "drafts",
    "visual_qa": "qa",
    "content_qa": "qa",
    "revision_note": "qa",
}


def _artifact_dir(type_: str) -> str:
    return _TYPE_DIRS.get(type_, "plans")


def _slug(type_: str, name: str, version: int) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name) or "default"
    return f"{type_}_{safe}_v{version}.json"


class PipelineArtifactManager:
    def __init__(self, run: PipelineRun, workspace_root: Path):
        self.run_id = run.id
        self.workspace_root = workspace_root

    @staticmethod
    def _new_payload(row: PipelineArtifact) -> dict[str, Any]:
        return {
            "id": row.id,
            "artifact_type": row.artifact_type,
            "name": row.name,
            "version": row.version,
            "status": row.status,
            "data": row.data_json,
            "file_path": row.file_path,
            "mime_type": row.mime_type,
            "producer_agent": row.producer_agent,
            "producer_tool": row.producer_tool,
            "created_by_step_index": row.created_by_step_index,
            "dependencies": row.dependencies_json,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }

    async def create(
        self,
        artifact_type: str,
        name: str,
        data: dict[str, Any],
        *,
        producer_agent: str = "",
        producer_tool: str = "",
        step_index: int = 0,
        dependencies: list[str] | None = None,
        write_file: bool = True,
    ) -> dict[str, Any]:
        """创建/新版本化 Artifact。同 (run, type, name) 已存在则旧版本标 superseded。"""
        async with SessionLocal() as db:
            prev = await db.scalar(select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == self.run_id,
                PipelineArtifact.artifact_type == artifact_type,
                PipelineArtifact.name == name,
                PipelineArtifact.status != "superseded",
            ).order_by(PipelineArtifact.version.desc()))
            version = (prev.version + 1) if prev else 1
            if prev:
                prev.status = "superseded"
            row = PipelineArtifact(
                pipeline_run_id=self.run_id, artifact_type=artifact_type, name=name, version=version,
                data_json=data, status="validated", producer_agent=producer_agent, producer_tool=producer_tool,
                created_by_step_index=step_index, dependencies_json=list(dependencies or []),
                parent_id=prev.id if prev else None,
            )
            file_path = ""
            if write_file:
                rel_dir = _artifact_dir(artifact_type)
                rel_path = Path(rel_dir) / _slug(artifact_type, name, version)
                abs_path = self.workspace_root / rel_path
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                file_path = str(rel_path)
            row.file_path = file_path
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return self._new_payload(row)

    async def get(self, artifact_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as db:
            row = await db.get(PipelineArtifact, artifact_id)
            return self._new_payload(row) if row else None

    async def latest(self, artifact_type: str, name: str = "default") -> dict[str, Any] | None:
        async with SessionLocal() as db:
            row = await db.scalar(select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == self.run_id,
                PipelineArtifact.artifact_type == artifact_type,
                PipelineArtifact.name == name,
                PipelineArtifact.status != "superseded",
            ).order_by(PipelineArtifact.version.desc()))
            return self._new_payload(row) if row else None

    async def list_all(self) -> list[dict[str, Any]]:
        async with SessionLocal() as db:
            rows = list(await db.scalars(select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == self.run_id,
            ).order_by(PipelineArtifact.created_at)))
            return [self._new_payload(row) for row in rows]

    async def read_data(self, artifact_id: str) -> dict[str, Any] | None:
        async with SessionLocal() as db:
            row = await db.get(PipelineArtifact, artifact_id)
            return row.data_json if row else None

    async def mark_status(self, artifact_id: str, status: str):
        async with SessionLocal() as db:
            row = await db.get(PipelineArtifact, artifact_id)
            if row:
                row.status = status
                await db.commit()

    async def resolve_dependencies(self, artifact_id: str) -> list[dict[str, Any]]:
        async with SessionLocal() as db:
            row = await db.get(PipelineArtifact, artifact_id)
            if not row:
                return []
            ids = list(row.dependencies_json or [])
            resolved = []
            for dep_id in ids:
                dep = await db.get(PipelineArtifact, dep_id)
                if dep:
                    resolved.append(self._new_payload(dep))
            return resolved
