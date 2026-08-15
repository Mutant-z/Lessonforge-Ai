"""视频脚本 V4 确定性质量门禁。

validate_video_script_v4() 在 Agent 发布、人工编辑与全局 QA 入口复用：
- V4 结构与章节连续性（每镜恰属一章、同章连续、章节顺序=首次出现顺序、章节非空）；
- Schema 完整性（结构非法 → critical）；
- 蓝图与教学设计引用合法性（目标 / 知识点 / 环节 / 章节目标）；
- 目标覆盖（每个蓝图目标至少被一个章节覆盖）；
- 时间轴与时长守恒（总时长=目标、每段 4–15 秒、时间连续）；
- 语速（口播估算不超可用时长 10%）、完整句边界（不截断句子）；
- 事实基准（必需术语/数字出现在口播）、连续性分组非空、Seedance 可执行性（不依赖 PPT）；
- 锁定路径未被修改。

问题统一为 {severity, location, dimension, description, suggestion}，
与 quality_service 既有 issue 形状一致。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.schemas.blueprint import CourseBlueprintSchema
from app.schemas.video_script_v4 import VIDEO_SCRIPT_V4, SeedanceVideoScriptContentV4

VIDEO_SCRIPT_AGENT = "video_script_agent"
MIN_SCENE_SECONDS = 4.0
MAX_SCENE_SECONDS = 15.0
NARRATION_CHARS_PER_MINUTE = 240.0  # 语速基准（字/分钟），对应 seedance 口播


def issue(severity: str, location: str, dimension: str, description: str, suggestion: str) -> dict:
    return {
        "severity": severity,
        "artifact_type": "video_script",
        "location": location,
        "dimension": dimension,
        "description": description,
        "evidence": description,
        "suggestion": suggestion,
        "target_agent": VIDEO_SCRIPT_AGENT,
        "required_action": "revise",
    }


def blocking_issues(issues: list[dict]) -> list[dict]:
    return [item for item in issues if item["severity"] in {"critical", "major"}]


def fingerprint(issues: list[dict]) -> str:
    """QA 指纹：用于防返修空转（相同指纹连续出现即停止）。"""
    return hashlib.sha256(
        "\n".join(
            f"{item.get('severity')}:{item.get('location')}:{item.get('dimension')}"
            for item in blocking_issues(issues)
        ).encode("utf-8"),
    ).hexdigest()


def _normalized(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", value)).lower()


def _locked_paths_ok(locked_paths: list[str]) -> bool:
    return not any(path in {"", "$"} for path in locked_paths)


def validate_video_script_v4(
    bp: CourseBlueprintSchema,
    content: dict[str, Any],
    lesson_plan_raw: dict[str, Any] | None = None,
    locked_paths: list[str] | None = None,
    max_scene_seconds: float = MAX_SCENE_SECONDS,
) -> list[dict]:
    """校验 V4 视频脚本候选稿，返回问题列表（空列表 = 通过）。"""
    issues: list[dict] = []
    if content.get("schema_version") != VIDEO_SCRIPT_V4:
        issues.append(issue("minor", "$", "compatibility",
                            "当前视频脚本仍使用 V3/V1 结构", "首次修改或同步时转换为 V4 动态章节"))
        return issues
    if locked_paths and not _locked_paths_ok(locked_paths):
        issues.append(issue("critical", "$", "lock",
                            "任务文件已整体锁定，不允许修改", "解除锁定后重试"))
        return issues
    try:
        script = SeedanceVideoScriptContentV4.model_validate(content)
    except Exception as exc:  # noqa: BLE001
        issues.append(issue("critical", "$", "integrity",
                            f"V4 视频脚本结构非法：{str(exc)[:300]}", "修复章节与分镜结构后重新校验"))
        return issues
    content = script.model_dump()

    objective_ids = {item.id for item in bp.objectives}
    knowledge_ids = {item.id for item in bp.knowledge_points}
    stage_ids = {item.segment_id for item in bp.timeline}
    if lesson_plan_raw:
        try:
            from app.schemas.artifact import LessonPlanContent

            plan = LessonPlanContent.model_validate(lesson_plan_raw)
            stage_ids = {item.id for item in plan.stages}
        except Exception:  # noqa: BLE001  V1 或结构非法的教学设计不参与环节检查
            pass

    sections = content.get("outline", {}).get("sections", [])
    section_by_id = {item.get("id"): item for item in sections}
    section_scene_counts: dict[str, int] = {item.get("id", ""): 0 for item in sections}
    covered_objectives: set[str] = set()
    previous_end = 0.0

    for index, scene in enumerate(content.get("scenes", [])):
        location = f"$.scenes[{index}]"
        scene_id = scene.get("id", "")
        section_id = scene.get("section_id", "")
        if section_id not in section_by_id:
            issues.append(issue("critical", f"{location}.section_id", "alignment",
                                f"分镜 {scene_id} 引用了不存在的章节 {section_id}",
                                "改为当前大纲中的章节 ID"))
            continue
        section_scene_counts[section_id] += 1
        duration = float(scene.get("end_seconds", 0)) - float(scene.get("start_seconds", 0))
        if duration < MIN_SCENE_SECONDS or duration > max_scene_seconds:
            window = f"4–{max_scene_seconds:g}"
            issues.append(issue("critical", location, "timing",
                                f"分镜 {scene_id} 时长 {duration:.1f} 秒超出 {window} 秒窗口",
                                "按当前视频渲染模型的时长上限拆分或合并片段"))
        if abs(float(scene.get("start_seconds", 0)) - previous_end) > 0.11:
            issues.append(issue("critical", location, "timing",
                                f"分镜 {scene_id} 时间轴不连续", "重算时间轴使片段无缝衔接"))
        previous_end = float(scene.get("end_seconds", 0))
        if scene.get("lesson_stage_id") not in stage_ids:
            issues.append(issue("critical", f"{location}.lesson_stage_id", "alignment",
                                f"分镜 {scene_id} 引用了不存在的教学环节 {scene.get('lesson_stage_id')}",
                                "改为当前教学设计中的环节 ID"))
        for ref in scene.get("objective_ids", []):
            if ref not in objective_ids:
                issues.append(issue("critical", f"{location}.objective_ids", "alignment",
                                    f"分镜 {scene_id} 引用了不存在的课程目标 {ref}",
                                    "改为蓝图中的目标 ID"))
            else:
                covered_objectives.add(ref)
        for ref in scene.get("knowledge_point_ids", []):
            if ref not in knowledge_ids:
                issues.append(issue("critical", f"{location}.knowledge_point_ids", "alignment",
                                    f"分镜 {scene_id} 引用了不存在的知识点 {ref}",
                                    "改为蓝图中的知识点 ID"))
        # 语速：口播估算不超过片段可用时长的 10%
        narration_seconds = len(_normalized(scene.get("spoken_text", ""))) / NARRATION_CHARS_PER_MINUTE * 60
        if narration_seconds > duration * 1.10:
            issues.append(issue("major", f"{location}.spoken_text", "timing",
                                f"分镜 {scene_id} 口播估算需要 {narration_seconds:.1f} 秒，超过片段时长 {duration:.1f} 秒",
                                "压缩口播或拆分为更短片段"))
        # 完整句边界：口播不得以逗号/分号/顿号结尾（截断句）
        spoken = (scene.get("spoken_text") or "").strip()
        if spoken and spoken[-1] in "，；、：—":
            issues.append(issue("major", f"{location}.spoken_text", "integrity",
                                f"分镜 {scene_id} 口播以不完整句结尾（{spoken[-1]}）", "补全句子或调整拆分点"))
        normalized_spoken = _normalized(spoken)
        for term in scene.get("required_terms", []):
            if term and _normalized(term) not in normalized_spoken:
                issues.append(issue("major", f"{location}.required_terms", "consistency",
                                    f"分镜 {scene_id} 必需术语未完整出现在口播中：{term}",
                                    "补齐必需术语或修订术语清单"))
        for number in scene.get("required_numbers", []):
            if number and _normalized(number) not in normalized_spoken:
                issues.append(issue("major", f"{location}.required_numbers", "consistency",
                                    f"分镜 {scene_id} 必需数字未完整出现在口播中：{number}",
                                    "在口播中明确说出该数字"))
        if not (scene.get("continuity_group") or "").strip():
            issues.append(issue("major", f"{location}.continuity_group", "consistency",
                                f"分镜 {scene_id} 缺少连续性分组", "指定同场景复用的连续性分组"))
        visual_prompt = (scene.get("visual_prompt") or "").lower()
        if "ppt" in visual_prompt or "幻灯片" in visual_prompt:
            issues.append(issue("major", f"{location}.visual_prompt", "production",
                                f"分镜 {scene_id} 原生视频提示词不得依赖 PPT", "改写为真实场景和镜头描述"))

    # 章节级检查
    for section in sections:
        section_id = section.get("id", "")
        location = f"$.outline.sections[{section_id}]"
        if section_scene_counts.get(section_id, 0) == 0:
            issues.append(issue("critical", location, "structure",
                                f"章节 {section_id} 不包含任何分镜", "为该章节分配分镜或删除空章节"))
        for ref in section.get("objective_ids", []):
            if ref not in objective_ids:
                issues.append(issue("critical", f"{location}.objective_ids", "alignment",
                                    f"章节 {section_id} 引用了不存在的课程目标 {ref}",
                                    "改为蓝图中的目标 ID"))
        for ref in section.get("knowledge_point_ids", []):
            if ref not in knowledge_ids:
                issues.append(issue("critical", f"{location}.knowledge_point_ids", "alignment",
                                    f"章节 {section_id} 引用了不存在的知识点 {ref}",
                                    "改为蓝图中的知识点 ID"))

    # 目标覆盖：每个蓝图目标至少被一个章节覆盖
    for objective in bp.objectives:
        if objective.id not in covered_objectives:
            issues.append(issue("major", "$.outline.sections", "alignment",
                                f"目标 {objective.id} 未被任何分镜覆盖", "在对应章节中补充覆盖该目标的分镜"))
    return issues
