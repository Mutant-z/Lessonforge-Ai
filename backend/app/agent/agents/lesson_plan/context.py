"""统一教学设计上下文快照（LessonPlanContextSnapshot）。

由服务端确定性生成，模型与 Agent 基于该快照理解整体方案。
包含：
- 基础版本与 Artifact 标识、内容 Hash
- 课程身份、学段、时长、教学场景
- 蓝图与内核事实映射：目标 → 知识点 → 环节 → 评价证据
- 递归大纲章节索引树（包含各层级深度、排序、可见正文摘要与 Hash）
- 稳定内核事实与章节的映射关系
- 作用域隔离：requested_scope / resolved_scope / new_section_ids / preserved_section_ids / locked_paths
- Profile 与兄弟产物摘要
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.lesson_plan import LessonPlanContentV2


def _calc_hash(data: Any) -> str:
    """计算对象的确定性 SHA256 哈希。"""
    try:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(data)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


class SectionSnapshotItem(BaseModel):
    """章节树节点快照。"""

    id: str
    parent_id: str = ""
    order: int = 0
    depth: int = 1
    title: str = ""
    summary: str = ""
    coverage_refs: list[str] = Field(default_factory=list)
    blocks_count: int = 0
    text_hash: str = ""
    text_preview: str = ""
    is_leaf: bool = True
    children_ids: list[str] = Field(default_factory=list)


class LessonPlanContextSnapshot(BaseModel):
    """教学设计全局上下文快照。"""

    schema_version: str = "2.0"
    snapshot_version: int = 1
    snapshot_id: str = ""
    artifact_id: str = ""
    source_version: str = ""
    source_hash: str = ""
    content_hash: str = ""
    snapshot_hash: str = ""
    course_identity: dict[str, Any] = Field(default_factory=dict)
    core_summary: dict[str, Any] = Field(default_factory=dict)
    fact_to_section_ids: dict[str, list[str]] = Field(default_factory=dict)
    fact_owner_map: dict[str, str] = Field(default_factory=dict)
    section_index: dict[str, SectionSnapshotItem] = Field(default_factory=dict)
    top_level_section_ids: list[str] = Field(default_factory=list)
    all_section_ids: list[str] = Field(default_factory=list)
    total_sections: int = 0
    total_visible_chars: int = 0
    requested_section_ids: list[str] = Field(default_factory=list)
    resolved_section_ids: list[str] = Field(default_factory=list)
    preserved_section_ids: list[str] = Field(default_factory=list)
    locked_paths: list[str] = Field(default_factory=list)
    profile_summary: dict[str, Any] = Field(default_factory=dict)
    siblings_summary: dict[str, Any] = Field(default_factory=dict)


def walk_sections_recursive(sections: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str, int, int]]:
    """递归遍历所有章节（包含任意层级子章节）。
    返回: [(section_node, parent_id, order, depth), ...]
    """
    result: list[tuple[dict[str, Any], str, int, int]] = []

    def visit(items: list[dict[str, Any]], parent_id: str, depth: int) -> None:
        for order, item in enumerate(items):
            result.append((item, parent_id, order, depth))
            children = list(item.get("children") or [])
            if children:
                visit(children, str(item.get("id") or ""), depth + 1)

    visit(sections, "", 1)
    return result


def extract_section_visible_text(section: dict[str, Any]) -> str:
    """提取章节的所有可见正文（排除 ID 等元数据键）。"""
    from app.agent.agents.lesson_plan.diff import section_visible_text
    return section_visible_text(section)


def build_lesson_plan_context_snapshot(
    content: dict[str, Any] | LessonPlanContentV2,
    *,
    blueprint: dict[str, Any] | CourseBlueprintSchema | None = None,
    artifact_id: str = "",
    snapshot_version: int = 1,
    requested_section_ids: list[str] | None = None,
    resolved_section_ids: list[str] | None = None,
    locked_paths: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    siblings: dict[str, Any] | None = None,
    source_version: str = "",
    source_hash: str = "",
) -> LessonPlanContextSnapshot:
    """确定性构建当前教学设计的全局上下文快照。

    快照在执行链前创建并不可变：``resolved_section_ids`` 由调用方传入
    （已在请求入口规范化的执行范围），绝不依赖执行结束后才计算的
    ``affected_section_ids``。``preserved_section_ids`` 基于快照时的章节集合推导，
    与目标范围互斥。
    """
    raw_content = content.model_dump() if hasattr(content, "model_dump") else dict(content or {})
    raw_bp = blueprint.model_dump() if hasattr(blueprint, "model_dump") else dict(blueprint or {})
    requested = list(requested_section_ids or [])
    resolved = list(resolved_section_ids or requested)
    locks = list(locked_paths or [])

    course_info = raw_content.get("course_info") or raw_bp.get("course_identity") or {}
    core = raw_content.get("pedagogical_core") or {}
    outline = raw_content.get("outline") or {}
    sections = outline.get("sections") or []

    # 递归索引大纲章节
    section_index: dict[str, SectionSnapshotItem] = {}
    top_level_ids: list[str] = []
    all_ids: list[str] = []
    fact_to_sections: dict[str, list[str]] = {}
    total_chars = 0

    recursive_nodes = walk_sections_recursive(sections)
    for node, parent_id, order, depth in recursive_nodes:
        sid = str(node.get("id") or "")
        if not sid:
            continue
        all_ids.append(sid)
        if depth == 1:
            top_level_ids.append(sid)

        children = list(node.get("children") or [])
        children_ids = [str(c.get("id") or "") for c in children if c.get("id")]
        vis_text = extract_section_visible_text(node)
        total_chars += len(vis_text)

        refs = list(node.get("coverage_refs") or [])
        for ref in refs:
            fact_to_sections.setdefault(ref, []).append(sid)

        summary = str(node.get("summary") or "")
        preview = (summary or vis_text)[:120]

        section_index[sid] = SectionSnapshotItem(
            id=sid,
            parent_id=parent_id,
            order=order,
            depth=depth,
            title=str(node.get("title") or ""),
            summary=summary,
            coverage_refs=refs,
            blocks_count=len(node.get("blocks") or []),
            text_hash=_calc_hash(vis_text),
            text_preview=preview,
            is_leaf=(len(children) == 0),
            children_ids=children_ids,
        )

    # 划分保留章节：不在 resolved_scope 中的所有现有章节
    resolved_set = set(resolved)
    preserved_ids = [sid for sid in all_ids if sid not in resolved_set]

    # 稳定内核摘要
    core_summary = {
        "objective_count": len(core.get("objectives", [])),
        "stage_count": len(core.get("stages", [])),
        "assessment_count": len(core.get("assessment_plan", [])),
        "has_homework": bool(core.get("homework")),
        "has_board_design": bool(core.get("board_design")),
        "has_reflection": bool(core.get("reflection")),
        "stages": [
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "duration_minutes": s.get("duration_minutes"),
            }
            for s in core.get("stages", [])
        ],
    }

    # Profile 与 Siblings 摘要
    prof_sum = {
        k: str(v)[:300]
        for k, v in (profile or {}).items()
        if v not in (None, "", [])
    }
    sib_sum = {
        k: str(v)[:300]
        for k, v in (siblings or {}).items()
        if v not in (None, "", [])
    }

    # 稳定事实归属：每个 fact 的唯一一级章节所有者（无歧义时）。
    fact_owner_map: dict[str, str] = {}
    for fact in sorted(fact_to_sections):
        owners = fact_to_sections[fact]
        top_owners = [sid for sid in owners if sid in set(top_level_ids)]
        if len(top_owners) == 1:
            fact_owner_map[fact] = top_owners[0]

    snapshot = LessonPlanContextSnapshot(
        schema_version="2.0",
        snapshot_version=snapshot_version,
        snapshot_id=f"snap-{_calc_hash(raw_content)[:8]}-{len(all_ids)}",
        artifact_id=artifact_id,
        source_version=source_version,
        source_hash=source_hash,
        content_hash=_calc_hash(raw_content),
        course_identity=course_info,
        core_summary=core_summary,
        fact_to_section_ids=fact_to_sections,
        fact_owner_map=fact_owner_map,
        section_index=section_index,
        top_level_section_ids=top_level_ids,
        all_section_ids=all_ids,
        total_sections=len(all_ids),
        total_visible_chars=total_chars,
        requested_section_ids=requested,
        resolved_section_ids=resolved,
        preserved_section_ids=preserved_ids,
        locked_paths=locks,
        profile_summary=prof_sum,
        siblings_summary=sib_sum,
    )
    snapshot.snapshot_hash = _calc_hash(snapshot.model_dump(exclude={"snapshot_hash"}))
    return snapshot


# ---------------------------------------------------------------------------
# LessonPlanEvidenceBundle：面向任务的证据包
# ---------------------------------------------------------------------------


class SectionEvidence(BaseModel):
    """目标/依赖章节的证据：正文快照 + 哈希 + 元数据。"""

    section_id: str
    title: str = ""
    depth: int = 1
    parent_id: str = ""
    order: int = 0
    text_hash: str = ""
    text_preview: str = ""
    is_leaf: bool = True
    has_visible_text: bool = False


class FactEvidence(BaseModel):
    """教学事实证据（来自蓝图/内核）。"""

    fact_key: str
    source: Literal["blueprint", "core", "materials", "sibling", "derived"] = "blueprint"
    value: str = ""
    ref_id: str = ""
    source_title: str = ""
    relevance: float = 1.0


class MaterialEvidence(BaseModel):
    """课程材料片段证据：保留来源标识，不截断为字符串。"""

    material_id: str = ""
    chunk_id: str = ""
    source: str = ""
    title: str = ""
    relevance: float = 1.0
    snippet: str = ""


class ArtifactEvidence(BaseModel):
    """兄弟产物证据（下游软参考）。"""

    artifact_type: str = ""
    artifact_id: str = ""
    title: str = ""
    version: int = 0
    summary: str = ""


class LessonPlanEvidenceBundle(BaseModel):
    """统一证据包：只读工具结果自动写入，后续 Agent 不需要重新读取。"""

    task_spec_id: str = ""
    source_version: str = ""
    target_sections: list[SectionEvidence] = Field(default_factory=list)
    dependent_sections: list[SectionEvidence] = Field(default_factory=list)
    blueprint_facts: list[FactEvidence] = Field(default_factory=list)
    learner_constraints: list[FactEvidence] = Field(default_factory=list)
    material_evidence: list[MaterialEvidence] = Field(default_factory=list)
    sibling_artifact_evidence: list[ArtifactEvidence] = Field(default_factory=list)
    fact_owner_map: dict[str, str] = Field(default_factory=dict)
    knowledge_gaps: list[str] = Field(default_factory=list)
    sufficiency: Literal["sufficient", "partial", "insufficient"] = "sufficient"


def build_lesson_plan_evidence_bundle(
    content: dict[str, Any],
    *,
    blueprint: dict[str, Any] | CourseBlueprintSchema | None = None,
    profile: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
    task_spec_id: str = "",
    source_version: str = "",
    target_section_ids: list[str] | None = None,
    target_fact_keys: list[str] | None = None,
    requires_teaching_reasoning: bool = True,
) -> LessonPlanEvidenceBundle:
    """确定性构建面向任务的证据包。

    - 格式/确定性任务（requires_teaching_reasoning=False）：只读取目标章节、层级与
      渲染规则，不进行材料检索；
    - 内容修改任务：按目标事实键筛选相关材料片段与兄弟产物，保留来源标识；
    - 证据不足且影响事实正确性时标记 sufficiency=partial/insufficient 与 knowledge_gaps。
    """
    raw_bp = blueprint.model_dump() if hasattr(blueprint, "model_dump") else dict(blueprint or {})
    raw_profile = dict(profile or {})
    raw_knowledge = dict(knowledge or {})
    target_ids = list(target_section_ids or [])
    fact_keys = list(target_fact_keys or [])
    sections = (content.get("outline") or {}).get("sections") or []
    recursive_nodes = walk_sections_recursive(sections)
    node_map = {
        str(node.get("id") or ""): (node, parent_id, order, depth)
        for node, parent_id, order, depth in recursive_nodes
    }
    target_set = set(target_ids)

    def _section_evidence(section_id: str) -> SectionEvidence | None:
        entry = node_map.get(section_id)
        if entry is None:
            return None
        node, parent_id, order, depth = entry
        vis_text = extract_section_visible_text(node)
        return SectionEvidence(
            section_id=section_id,
            title=str(node.get("title") or ""),
            depth=depth,
            parent_id=parent_id,
            order=order,
            text_hash=_calc_hash(vis_text),
            text_preview=(str(node.get("summary") or "") or vis_text)[:120],
            is_leaf=not (node.get("children") or []),
            has_visible_text=bool(vis_text),
        )

    target_sections = [
        item for item in (_section_evidence(sid) for sid in target_ids) if item is not None
    ]
    dependent_ids = [sid for sid in node_map if sid not in target_set]
    dependent_sections = [
        item for item in (_section_evidence(sid) for sid in sorted(dependent_ids)) if item is not None
    ]

    objectives = raw_bp.get("objectives") or []
    knowledge_points = raw_bp.get("knowledge_points") or []
    blueprint_facts: list[FactEvidence] = []
    for objective in objectives:
        blueprint_facts.append(FactEvidence(
            fact_key="objectives", source="blueprint",
            value=str(objective.get("statement") or objective.get("behavior") or ""),
            ref_id=str(objective.get("id") or ""), relevance=1.0,
        ))
    for kp in knowledge_points:
        blueprint_facts.append(FactEvidence(
            fact_key="knowledge_points", source="blueprint",
            value=str(kp.get("name") or ""), ref_id=str(kp.get("id") or ""), relevance=1.0,
        ))
    learner_constraints: list[FactEvidence] = []
    for key in ("prior_knowledge", "learner_characteristics", "likely_misconceptions", "constraints"):
        values = raw_bp.get("learning_analysis") or {}
        for item in (values.get(key) if isinstance(values, dict) else []) or []:
            learner_constraints.append(FactEvidence(
                fact_key=key, source="blueprint", value=str(item), relevance=1.0,
            ))
    for key in ("learner_profile", "teaching_scenario", "constraints"):
        value = raw_profile.get(key)
        if value not in (None, "", []):
            learner_constraints.append(FactEvidence(
                fact_key=key, source="blueprint", value=str(value)[:300], relevance=0.8,
            ))

    # 材料证据：仅内容修改任务检索；格式任务不进行材料检索。
    material_evidence: list[MaterialEvidence] = []
    knowledge_gaps: list[str] = []
    if requires_teaching_reasoning and fact_keys:
        materials = raw_knowledge.get("materials") or []
        for material in materials:
            text = json.dumps(material, ensure_ascii=False, default=str)
            if any(fact in text for fact in fact_keys):
                material_evidence.append(MaterialEvidence(
                    material_id=str(material.get("id") or material.get("material_id") or ""),
                    chunk_id=str(material.get("chunk_id") or ""),
                    source=str(material.get("source") or material.get("type") or ""),
                    title=str(material.get("title") or material.get("name") or ""),
                    relevance=1.0,
                    snippet=str(material.get("summary") or material.get("snippet") or "")[:500],
                ))
    elif not requires_teaching_reasoning:
        # 确定性/格式任务：不检索材料，证据天然充分。
        pass
    if requires_teaching_reasoning and fact_keys and not material_evidence:
        knowledge_gaps.append("目标事实在课程材料中缺少直接证据")

    sibling_artifact_evidence: list[ArtifactEvidence] = []
    siblings = raw_knowledge.get("sibling_artifacts") or raw_knowledge.get("upstream") or {}
    if isinstance(siblings, dict):
        for artifact_type, value in siblings.items():
            if isinstance(value, list):
                for item in value[:5]:
                    sibling_artifact_evidence.append(ArtifactEvidence(
                        artifact_type=str(artifact_type),
                        artifact_id=str(item.get("id") or ""),
                        title=str(item.get("title") or item.get("name") or ""),
                        version=int(item.get("version") or 0),
                        summary=str(item.get("summary") or "")[:200],
                    ))
            elif isinstance(value, dict):
                sibling_artifact_evidence.append(ArtifactEvidence(
                    artifact_type=str(artifact_type),
                    artifact_id=str(value.get("id") or ""),
                    title=str(value.get("title") or value.get("name") or ""),
                    version=int(value.get("version") or 0),
                    summary=str(value.get("summary") or "")[:200],
                ))

    fact_owner_map: dict[str, str] = {}
    for fact in sorted(fact_keys):
        owners = [sid for sid in target_ids if sid in node_map]
        if len(owners) == 1:
            fact_owner_map[fact] = owners[0]
    if not fact_owner_map:
        top_level_owners = _fact_to_top_level(content)
        fact_owner_map = {fact: sid for fact, sid in top_level_owners.items()}

    sufficiency: Literal["sufficient", "partial", "insufficient"] = "sufficient"
    if knowledge_gaps:
        sufficiency = "partial"
    if requires_teaching_reasoning and fact_keys and not fact_owner_map:
        sufficiency = "insufficient"

    return LessonPlanEvidenceBundle(
        task_spec_id=task_spec_id,
        source_version=source_version,
        target_sections=target_sections,
        dependent_sections=dependent_sections[:24],
        blueprint_facts=blueprint_facts[:40],
        learner_constraints=learner_constraints[:20],
        material_evidence=material_evidence,
        sibling_artifact_evidence=sibling_artifact_evidence,
        fact_owner_map=fact_owner_map,
        knowledge_gaps=knowledge_gaps,
        sufficiency=sufficiency,
    )


def _fact_to_top_level(content: dict[str, Any]) -> dict[str, str]:
    """fact → 唯一一级章节所有者（无歧义时）。"""
    top_level = (content.get("outline") or {}).get("sections") or []
    owners: dict[str, list[str]] = {}
    for section in top_level:
        for ref in section.get("coverage_refs") or []:
            owners.setdefault(str(ref), []).append(str(section.get("id") or ""))
    return {
        fact: ids[0]
        for fact, ids in owners.items()
        if len(ids) == 1
    }
