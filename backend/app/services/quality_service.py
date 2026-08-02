import re
from collections import Counter

from app.schemas.artifact import ExerciseContent, PPTContent, VerbatimContent, VideoScriptContent
from app.schemas.blueprint import CourseBlueprintSchema


def issue(severity: str, artifact_type: str, location: str, dimension: str, description: str, suggestion: str, target_agent: str) -> dict:
    return {"severity": severity, "artifact_type": artifact_type, "location": location, "dimension": dimension, "description": description, "evidence": description, "suggestion": suggestion, "target_agent": target_agent, "required_action": "revise"}


def validate_blueprint(bp: CourseBlueprintSchema) -> list[dict]:
    issues = []
    objective_ids = [x.id for x in bp.objectives]
    knowledge_ids = [x.id for x in bp.knowledge_points]
    if len(objective_ids) != len(set(objective_ids)):
        issues.append(issue("critical", "blueprint", "objectives", "integrity", "教学目标 ID 不唯一", "重新编号目标", "pedagogy_blueprint_agent"))
    if len(knowledge_ids) != len(set(knowledge_ids)):
        issues.append(issue("critical", "blueprint", "knowledge_points", "integrity", "知识点 ID 不唯一", "重新编号知识点", "pedagogy_blueprint_agent"))
    total = sum(x.end_minute - x.start_minute for x in bp.timeline)
    if abs(total - bp.course_identity.duration_minutes) > 0.5:
        issues.append(issue("major", "blueprint", "timeline", "timing", f"时间线合计 {total} 分钟，与课程时长不一致", "调整环节时间", "pedagogy_blueprint_agent"))
    for obj in bp.objectives:
        if not obj.activity_ids:
            issues.append(issue("major", "blueprint", f"objectives.{obj.id}", "alignment", "目标未关联教学活动", "关联至少一个活动", "pedagogy_blueprint_agent"))
        if not obj.exercise_ids:
            issues.append(issue("major", "blueprint", f"objectives.{obj.id}", "alignment", "目标未关联练习", "关联至少一道练习", "exercise_agent"))
    return issues


def validate_resources(bp: CourseBlueprintSchema, data: dict[str, dict]) -> list[dict]:
    issues = validate_blueprint(bp)
    ppt = PPTContent.model_validate(data["ppt"])
    exercises = ExerciseContent.model_validate(data["exercise"])
    video = VideoScriptContent.model_validate(data["video_script"])
    verbatim = VerbatimContent.model_validate(data["verbatim"])
    slide_ids = [x.id for x in ppt.slides]
    if len(slide_ids) != len(set(slide_ids)):
        issues.append(issue("critical", "ppt", "slides", "integrity", "PPT 页面 ID 不唯一", "重新编号页面", "ppt_agent"))
    for segment in video.segments:
        for slide_id in segment.slide_ids:
            if slide_id not in slide_ids:
                issues.append(issue("critical", "video_script", f"segments.{segment.id}", "consistency", f"引用了不存在的页面 {slide_id}", "修正页面引用", "video_script_agent"))
    for section in verbatim.sections:
        for slide_id in section.slide_ids:
            if slide_id not in slide_ids:
                issues.append(issue("critical", "verbatim", f"sections.{section.id}", "consistency", f"引用了不存在的页面 {slide_id}", "修正页面引用", "verbatim_agent"))
    for item in exercises.items:
        if len(item.options) != len(set(item.options)):
            issues.append(issue("major", "exercise", f"items.{item.id}", "validity", "题目选项重复", "替换重复选项", "exercise_agent"))
        if item.question_type == "single_choice" and len(item.correct_answers) != 1:
            issues.append(issue("critical", "exercise", f"items.{item.id}", "validity", "单选题必须且只能有一个答案", "修正答案", "exercise_agent"))
        if item.question_type == "multiple_choice" and len(item.correct_answers) < 2:
            issues.append(issue("critical", "exercise", f"items.{item.id}", "validity", "多选题至少需要两个答案", "修正答案", "exercise_agent"))
    covered = Counter(x for item in exercises.items for x in item.objective_ids)
    for objective in bp.objectives:
        if not covered[objective.id]:
            issues.append(issue("major", "exercise", "items", "alignment", f"目标 {objective.id} 未被练习覆盖", "补充对应练习", "exercise_agent"))
    return issues


def estimate_chinese_minutes(text: str, chars_per_minute: int = 220) -> float:
    count = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))
    return round(count / chars_per_minute, 2)

