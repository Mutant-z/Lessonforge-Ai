import re
from collections import Counter

from app.schemas.artifact import (
    ExerciseContent,
    ExerciseQuestionGroup,
    LegacyExerciseContent,
    LegacyVideoScriptContent,
    LessonPlanContent,
    PPTContent,
    TaskSheetContent,
    VerbatimContent,
    VideoScriptContent,
)
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


def _duplicates(values: list[str]) -> set[str]:
    counts = Counter(values)
    return {value for value, count in counts.items() if count > 1}


def validate_task_sheet(bp: CourseBlueprintSchema, raw: dict, lesson_plan_raw: dict | None = None) -> list[dict]:
    if raw.get("schema_version") != "2.0":
        return [issue(
            "minor", "task_sheet", "$", "compatibility",
            "当前任务单仍使用 V1 结构", "下一次修改时升级为结构化学生版任务单 V2", "task_sheet_agent",
        )]
    sheet = TaskSheetContent.model_validate(raw)
    issues = []
    objective_ids = {item.id for item in bp.objectives}
    knowledge_ids = {item.id for item in bp.knowledge_points}
    blueprint_stage_durations = {
        item.segment_id: item.end_minute - item.start_minute
        for item in bp.timeline
    }
    stage_durations = blueprint_stage_durations
    lesson_stage_ids: set[str] | None = None
    if lesson_plan_raw:
        lesson_plan = LessonPlanContent.model_validate(lesson_plan_raw)
        stage_durations = {item.id: item.duration_minutes for item in lesson_plan.stages}
        lesson_stage_ids = set(stage_durations)

    id_groups = {
        "learning_objectives": [item.id for item in sheet.learning_objectives],
        "tasks": [item.id for item in sheet.tasks],
        "learning_questions": [item.id for item in sheet.learning_questions],
        "self_assessment": [item.id for item in sheet.self_assessment],
    }
    for group, ids in id_groups.items():
        for duplicate in sorted(_duplicates(ids)):
            duplicate_index = next(index for index, value in enumerate(ids) if value == duplicate)
            issues.append(issue(
                "major", "task_sheet", f"$.{group}[{duplicate_index}].id", "integrity",
                f"ID {duplicate} 重复", "使用唯一 ID 重新编号", "task_sheet_agent",
            ))

    for index, objective in enumerate(sheet.learning_objectives):
        if objective.id not in objective_ids:
            issues.append(issue(
                "critical", "task_sheet", f"$.learning_objectives[{index}].id", "alignment",
                f"引用了不存在的目标 {objective.id}", "改为已批准蓝图中的目标 ID", "task_sheet_agent",
            ))

    covered_objectives = Counter()
    in_class_minutes = 0.0
    stage_minutes = Counter()
    has_record_table = sheet.record_table is not None
    for task_index, task in enumerate(sheet.tasks):
        location = f"$.tasks[{task_index}]"
        for objective_id in task.objective_ids:
            covered_objectives[objective_id] += 1
            if objective_id not in objective_ids:
                issues.append(issue("critical", "task_sheet", location, "alignment", f"引用了不存在的目标 {objective_id}", "改为蓝图中的目标 ID", "task_sheet_agent"))
        for knowledge_id in task.knowledge_point_ids:
            if knowledge_id not in knowledge_ids:
                issues.append(issue("critical", "task_sheet", location, "alignment", f"引用了不存在的知识点 {knowledge_id}", "改为蓝图中的知识点 ID", "task_sheet_agent"))
        if task.stage_id and task.stage_id not in blueprint_stage_durations:
            issues.append(issue("major", "task_sheet", f"{location}.stage_id", "alignment", f"引用了蓝图中不存在的教学环节 {task.stage_id}", "改为已批准蓝图中的环节 ID", "task_sheet_agent"))
        elif task.stage_id and lesson_stage_ids is not None and task.stage_id not in lesson_stage_ids:
            issues.append(issue("major", "task_sheet", f"{location}.stage_id", "alignment", f"教学设计中不存在对应环节 {task.stage_id}", "将课中任务映射到教学设计的实际环节", "task_sheet_agent"))
        if task.stage_id and task.phase != "in_class":
            issues.append(issue("major", "task_sheet", f"{location}.phase", "alignment", f"{task.phase} 任务映射到了课中教学环节 {task.stage_id}", "移除环节映射或将任务阶段改为课中", "task_sheet_agent"))
        if task.phase == "in_class":
            in_class_minutes += task.estimated_minutes
            if task.stage_id:
                stage_minutes[task.stage_id] += task.estimated_minutes
        has_record_table = has_record_table or task.record_table is not None

    for objective_id in sorted(objective_ids):
        if not covered_objectives[objective_id]:
            issues.append(issue("major", "task_sheet", "$.tasks", "alignment", f"目标 {objective_id} 未被任务覆盖", "补充对应的学习任务和学习证据", "task_sheet_agent"))
    if in_class_minutes > bp.course_identity.duration_minutes + 0.5:
        issues.append(issue("major", "task_sheet", "$.tasks", "timing", f"课中任务合计 {in_class_minutes} 分钟，超过课程时长", "压缩任务用时或移至课后", "task_sheet_agent"))
    for stage_id, minutes in stage_minutes.items():
        if stage_id in stage_durations and minutes > stage_durations[stage_id] + 0.5:
            task_index = next((index for index, task in enumerate(sheet.tasks) if task.stage_id == stage_id), 0)
            issues.append(issue("major", "task_sheet", f"$.tasks[{task_index}].estimated_minutes", "timing", f"环节 {stage_id} 任务用时 {minutes} 分钟，超过教学设计分配", "调整任务时长与教学环节一致", "task_sheet_agent"))
    if not has_record_table:
        issues.append(issue("major", "task_sheet", "$.record_table", "usability", "任务单没有可填写的观察或记录表", "增加顶层 record_table 或为至少一项任务增加 record_table", "task_sheet_agent"))

    referenced_groups = [
        ("learning_questions", [(item.id, item.objective_ids, item.stage_id) for item in sheet.learning_questions]),
        ("self_assessment", [(item.id, item.objective_ids, None) for item in sheet.self_assessment]),
    ]
    for group, entries in referenced_groups:
        for entry_index, (_, refs, stage_id) in enumerate(entries):
            for objective_id in refs:
                if objective_id not in objective_ids:
                    issues.append(issue("major", "task_sheet", f"$.{group}[{entry_index}].objective_ids", "alignment", f"引用了不存在的目标 {objective_id}", "改为蓝图中的目标 ID", "task_sheet_agent"))
            if stage_id and stage_id not in blueprint_stage_durations:
                issues.append(issue("major", "task_sheet", f"$.{group}[{entry_index}].stage_id", "alignment", f"引用了蓝图中不存在的环节 {stage_id}", "改为已批准蓝图中的环节 ID", "task_sheet_agent"))
            elif stage_id and lesson_stage_ids is not None and stage_id not in lesson_stage_ids:
                issues.append(issue("major", "task_sheet", f"$.{group}[{entry_index}].stage_id", "alignment", f"教学设计中不存在对应环节 {stage_id}", "改为教学设计中的实际环节 ID", "task_sheet_agent"))
    return issues


def _exercise_questions(content: ExerciseContent):
    for section_index, section in enumerate(content.sections):
        for block_index, block in enumerate(section.blocks):
            if isinstance(block, ExerciseQuestionGroup):
                for question_index, question in enumerate(block.sub_questions):
                    yield question, f"$.sections[{section_index}].blocks[{block_index}].sub_questions[{question_index}]", section.id
            else:
                yield block, f"$.sections[{section_index}].blocks[{block_index}]", section.id


def _normalized_trigrams(value: str) -> set[str]:
    normalized = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value).lower()
    return {normalized[index:index + 3] for index in range(max(0, len(normalized) - 2))}


def _similarity(left: str, right: str) -> float:
    left_set, right_set = _normalized_trigrams(left), _normalized_trigrams(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _normalized_script_text(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", value)).lower()


def validate_video_script(
    bp: CourseBlueprintSchema,
    raw: dict,
    lesson_plan_raw: dict | None,
    ppt_raw: dict,
) -> list[dict]:
    if raw.get("schema_version") != "2.0":
        LegacyVideoScriptContent.model_validate(raw)
        return [issue(
            "minor", "video_script", "$", "compatibility",
            "当前视频脚本仍使用 V1 结构", "下一次修改时升级为结构化视频脚本 V2", "video_script_agent",
        )]
    script = VideoScriptContent.model_validate(raw)
    ppt = PPTContent.model_validate(ppt_raw)
    lesson_plan = LessonPlanContent.model_validate(lesson_plan_raw) if lesson_plan_raw else None
    issues = []
    objective_ids = {item.id for item in bp.objectives}
    knowledge_ids = {item.id for item in bp.knowledge_points}
    stage_ids = {item.id for item in lesson_plan.stages} if lesson_plan else {item.segment_id for item in bp.timeline}
    slide_ids = [item.id for item in ppt.slides]
    slide_index = {slide_id: index for index, slide_id in enumerate(slide_ids)}
    slide_by_id = {item.id: item for item in ppt.slides}
    covered_objectives = Counter()
    covered_knowledge = Counter()
    slide_seconds = Counter()
    used_slides = []

    for index, scene in enumerate(script.scenes):
        location = f"$.scenes[{index}]"
        if scene.slide_id not in slide_index:
            issues.append(issue("critical", "video_script", f"{location}.slide_id", "consistency", f"引用了不存在的页面 {scene.slide_id}", "改为当前 PPT 中真实存在的页面 ID", "video_script_agent"))
        else:
            used_slides.append(scene.slide_id)
            slide_seconds[scene.slide_id] += scene.end_seconds - scene.start_seconds
        if scene.lesson_stage_id not in stage_ids:
            issues.append(issue("critical", "video_script", f"{location}.lesson_stage_id", "alignment", f"引用了不存在的教学环节 {scene.lesson_stage_id}", "改为当前教学设计中的环节 ID", "video_script_agent"))
        for objective_id in scene.objective_ids:
            covered_objectives[objective_id] += 1
            if objective_id not in objective_ids:
                issues.append(issue("critical", "video_script", f"{location}.objective_ids", "alignment", f"引用了不存在的课程目标 {objective_id}", "改为已批准蓝图中的目标 ID", "video_script_agent"))
        for knowledge_id in scene.knowledge_point_ids:
            covered_knowledge[knowledge_id] += 1
            if knowledge_id not in knowledge_ids:
                issues.append(issue("critical", "video_script", f"{location}.knowledge_point_ids", "alignment", f"引用了不存在的知识点 {knowledge_id}", "改为已批准蓝图中的知识点 ID", "video_script_agent"))

        duration = scene.end_seconds - scene.start_seconds
        pause_seconds = sum(item.duration_seconds for item in scene.audio_track.pause_cues)
        available_seconds = max(1, duration - pause_seconds)
        narration_seconds = len(_normalized_script_text(scene.audio_track.narration_text)) / script.production_settings.narration_chars_per_minute * 60
        if narration_seconds > available_seconds * 1.10:
            issues.append(issue("major", "video_script", f"{location}.audio_track.narration_text", "timing", f"旁白估算需要 {narration_seconds:.1f} 秒，超过可用时长 {available_seconds:.1f} 秒", "压缩旁白、减少停顿或重新分配分镜时长", "video_script_agent"))
        has_pacing_cue = bool(scene.interaction or scene.visual_track.animation_cues or scene.audio_track.pause_cues)
        if duration >= 45 and narration_seconds < duration * .40 and not has_pacing_cue:
            issues.append(issue("minor", "video_script", f"{location}.audio_track.narration_text", "timing", "旁白明显不足且没有标注视觉演示或互动留白", "补充可录制旁白或明确静默演示节奏", "video_script_agent"))

        subtitle_text = "".join(item.text for item in scene.text_track.subtitle_chunks)
        if _normalized_script_text(subtitle_text) != _normalized_script_text(scene.audio_track.narration_text):
            issues.append(issue("major", "video_script", f"{location}.text_track.subtitle_chunks", "consistency", "字幕未完整、忠实覆盖当前旁白", "按旁白原文重新切分字幕", "video_script_agent"))
        subtitle_limit = script.production_settings.subtitle_max_chars_per_line * script.production_settings.subtitle_max_lines
        if any(len(item.text.replace("\n", "")) > subtitle_limit or item.text.count("\n") + 1 > script.production_settings.subtitle_max_lines for item in scene.text_track.subtitle_chunks):
            issues.append(issue("minor", "video_script", f"{location}.text_track.subtitle_chunks", "readability", "字幕超过配置的单行字数或最大行数", "缩短字幕块并重新分配显示时间", "video_script_agent"))

        if scene.slide_id in slide_by_id:
            slide = slide_by_id[scene.slide_id]
            ppt_text = "".join([slide.title, *slide.body])
            if _similarity(scene.audio_track.narration_text, ppt_text) >= .78 or _similarity(scene.audio_track.narration_text, slide.speaker_notes) >= .82:
                issues.append(issue("minor", "video_script", f"{location}.audio_track.narration_text", "expression", "旁白与 PPT 正文或教师备注高度重复", "改写为解释、引导和推理语言，避免照读页面", "video_script_agent"))
        if scene.text_track.on_screen_text and _similarity(scene.audio_track.narration_text, "".join(scene.text_track.on_screen_text)) >= .82:
            issues.append(issue("minor", "video_script", f"{location}.text_track.on_screen_text", "expression", "屏幕贴字与旁白大段重复", "只保留关键词、结论或必要标注", "video_script_agent"))

    known_used = [slide_id for slide_id in used_slides if slide_id in slide_index]
    if [slide_index[item] for item in known_used] != sorted(slide_index[item] for item in known_used):
        issues.append(issue("critical", "video_script", "$.scenes", "consistency", "分镜中的 PPT 页面顺序与当前课件不一致", "按 PPT 页面顺序重新排列分镜", "video_script_agent"))
    for slide in ppt.slides:
        if not slide_seconds[slide.id]:
            issues.append(issue("major", "video_script", "$.scenes", "coverage", f"PPT 页面 {slide.id} 没有对应分镜", "为该页面补充分镜", "video_script_agent"))
        elif abs(slide_seconds[slide.id] - slide.duration_seconds) > 1:
            issues.append(issue("major", "video_script", "$.scenes", "timing", f"页面 {slide.id} 的分镜合计 {slide_seconds[slide.id]:.1f} 秒，与 PPT 时长 {slide.duration_seconds} 秒不一致", "校准该页全部分镜时长", "video_script_agent"))
    for objective_id in sorted(objective_ids):
        if not covered_objectives[objective_id]:
            issues.append(issue("major", "video_script", "$.scenes", "alignment", f"课程目标 {objective_id} 未被视频脚本覆盖", "补充对应分镜和学习证据", "video_script_agent"))
    for knowledge_id in sorted(knowledge_ids):
        if not covered_knowledge[knowledge_id]:
            issues.append(issue("major", "video_script", "$.scenes", "alignment", f"知识点 {knowledge_id} 未被视频脚本覆盖", "补充对应讲解、示范或检查分镜", "video_script_agent"))
    return issues


def validate_exercise(
    bp: CourseBlueprintSchema,
    raw: dict,
    task_sheet_raw: dict | None = None,
) -> list[dict]:
    if raw.get("schema_version") != "2.0":
        legacy = LegacyExerciseContent.model_validate(raw)
        issues = [issue(
            "minor", "exercise", "$", "compatibility",
            "当前课后练习仍使用 V1 结构", "下一次修改时升级为结构化练习 V2", "exercise_agent",
        )]
        covered = Counter(ref for item in legacy.items for ref in item.objective_ids)
        for objective in bp.objectives:
            if not covered[objective.id]:
                issues.append(issue("major", "exercise", "$.items", "alignment", f"目标 {objective.id} 未被练习覆盖", "补充对应练习", "exercise_agent"))
        return issues

    exercise = ExerciseContent.model_validate(raw)
    issues: list[dict] = []
    objective_ids = {item.id for item in bp.objectives}
    knowledge_ids = {item.id for item in bp.knowledge_points}
    stage_ids = {item.segment_id for item in bp.timeline}
    seen_ids: dict[str, str] = {}
    covered = Counter()
    generated_visuals = 0
    all_visual_ids: dict[str, str] = {}

    def remember(identifier: str, location: str):
        previous = seen_ids.get(identifier)
        if previous:
            issues.append(issue("major", "exercise", location, "integrity", f"ID {identifier} 与 {previous} 重复", "使用全卷唯一 ID", "exercise_agent"))
        else:
            seen_ids[identifier] = location

    for section_index, section in enumerate(exercise.sections):
        remember(section.id, f"$.sections[{section_index}].id")
        for block_index, block in enumerate(section.blocks):
            block_location = f"$.sections[{section_index}].blocks[{block_index}]"
            if isinstance(block, ExerciseQuestionGroup):
                remember(block.id, f"{block_location}.id")
                for stimulus_index, stimulus in enumerate(block.stimuli):
                    stimulus_location = f"{block_location}.stimuli[{stimulus_index}]"
                    remember(stimulus.id, f"{stimulus_location}.id")
                    if stimulus.visual:
                        visual = stimulus.visual
                        if visual.visual_id in all_visual_ids:
                            issues.append(issue("major", "exercise", f"{stimulus_location}.visual.visual_id", "integrity", f"视觉 ID {visual.visual_id} 重复", "使用全卷唯一视觉 ID", "exercise_agent"))
                        all_visual_ids[visual.visual_id] = stimulus_location
                        if visual.status != "approved" or not visual.asset_id:
                            issues.append(issue("minor", "exercise", f"{stimulus_location}.visual", "visual", "视觉材料尚未生成、复核或缺少资源", "完成确定性渲染/视觉复核，或使用 fallback_stimulus 降级", "exercise_agent"))
                        if visual.mode == "generated_image":
                            generated_visuals += 1

    task_sheet_texts: list[str] = []
    if task_sheet_raw and task_sheet_raw.get("schema_version") == "2.0":
        for task in task_sheet_raw.get("tasks", []):
            task_sheet_texts.extend([
                str(task.get("title", "")), str(task.get("action", "")), str(task.get("object", "")),
                *[str(step) for step in task.get("steps", [])],
            ])
        task_sheet_texts.extend(str(item.get("prompt", "")) for item in task_sheet_raw.get("learning_questions", []))

    total_question_minutes = 0.0
    for question, location, section_id in _exercise_questions(exercise):
        remember(question.id, f"{location}.id")
        covered.update(question.objective_ids)
        total_question_minutes += question.estimated_minutes
        for objective_id in question.objective_ids:
            if objective_id not in objective_ids:
                issues.append(issue("critical", "exercise", f"{location}.objective_ids", "alignment", f"引用了不存在的目标 {objective_id}", "改为已批准蓝图中的目标 ID", "exercise_agent"))
        for knowledge_id in question.knowledge_point_ids:
            if knowledge_id not in knowledge_ids:
                issues.append(issue("critical", "exercise", f"{location}.knowledge_point_ids", "alignment", f"引用了不存在的知识点 {knowledge_id}", "改为已批准蓝图中的知识点 ID", "exercise_agent"))
        for source_ref in question.source_refs:
            if source_ref not in stage_ids and source_ref not in bp.source_refs:
                issues.append(issue("major", "exercise", f"{location}.source_refs", "alignment", f"引用了不存在的教学环节或材料 {source_ref}", "使用蓝图环节 ID 或合法材料来源", "exercise_agent"))
        allowed_levels = {
            "basic_consolidation": {"remember", "understand", "apply"},
            "understanding_application": {"remember", "understand", "apply", "analyze"},
            "transfer_challenge": {"apply", "analyze", "transfer", "evaluate", "create"},
        }
        if question.cognitive_level not in allowed_levels[section_id]:
            issues.append(issue("major", "exercise", f"{location}.cognitive_level", "difficulty", f"认知层级 {question.cognitive_level} 与所在分区不一致", "调整认知层级或移动题目", "exercise_agent"))
        for task_text in task_sheet_texts:
            if _similarity(question.stem, task_text) >= 0.78:
                issues.append(issue("minor", "exercise", f"{location}.stem", "originality", "题干与任务单内容高度相似，可能直接复用了过程性任务", "保留目标但重新设计独立的课后测评情境", "exercise_agent"))
                break

    for objective_id in sorted(objective_ids):
        if not covered[objective_id]:
            issues.append(issue("major", "exercise", "$.sections", "alignment", f"目标 {objective_id} 未被练习覆盖", "补充对应计分题", "exercise_agent"))
    if generated_visuals > 3:
        issues.append(issue("critical", "exercise", "$.sections", "visual", f"生成式图片共 {generated_visuals} 张，超过单卷 3 张上限", "仅保留不可由文字或表格替代的必要配图", "exercise_agent"))
    if exercise.paper_settings.total_score != 100:
        issues.append(issue("critical", "exercise", "$.paper_settings.total_score", "scoring", "V2 课后练习总分必须为 100 分", "重新分配各分区和题目分值", "exercise_agent"))
    lower = bp.course_identity.duration_minutes * .3
    upper = max(bp.course_identity.duration_minutes * 2.5, 30.0)
    estimated = exercise.paper_settings.estimated_minutes
    if estimated < lower or estimated > upper:
        severity = "critical" if estimated > upper else "minor"
        issues.append(issue(severity, "exercise", "$.paper_settings.estimated_minutes", "timing", f"预计用时 {estimated} 分钟，不在合理的答题时间范围内", "调整题量或预计用时", "exercise_agent"))
    if abs(total_question_minutes - estimated) > max(2, estimated * .25):
        issues.append(issue("minor", "exercise", "$.paper_settings.estimated_minutes", "timing", f"题目用时合计 {total_question_minutes} 分钟，与试卷预计用时差异明显", "校准题目和试卷预计用时", "exercise_agent"))
    return issues


def validate_resources(bp: CourseBlueprintSchema, data: dict[str, dict]) -> list[dict]:
    issues = validate_blueprint(bp)
    if "task_sheet" in data:
        issues.extend(validate_task_sheet(bp, data["task_sheet"], data.get("lesson_plan")))
    ppt = PPTContent.model_validate(data["ppt"])
    exercise_raw = data["exercise"]
    video_raw = data["video_script"]
    verbatim = VerbatimContent.model_validate(data["verbatim"])
    slide_ids = [x.id for x in ppt.slides]
    if len(slide_ids) != len(set(slide_ids)):
        issues.append(issue("critical", "ppt", "slides", "integrity", "PPT 页面 ID 不唯一", "重新编号页面", "ppt_agent"))
    if video_raw.get("schema_version") == "2.0":
        issues.extend(validate_video_script(bp, video_raw, data.get("lesson_plan"), data["ppt"]))
    else:
        video = LegacyVideoScriptContent.model_validate(video_raw)
        issues.extend(validate_video_script(bp, video_raw, data.get("lesson_plan"), data["ppt"]))
        for segment in video.segments:
            for slide_id in segment.slide_ids:
                if slide_id not in slide_ids:
                    issues.append(issue("critical", "video_script", f"segments.{segment.id}", "consistency", f"引用了不存在的页面 {slide_id}", "修正页面引用", "video_script_agent"))
    for section in verbatim.sections:
        for slide_id in section.slide_ids:
            if slide_id not in slide_ids:
                issues.append(issue("critical", "verbatim", f"sections.{section.id}", "consistency", f"引用了不存在的页面 {slide_id}", "修正页面引用", "verbatim_agent"))
    issues.extend(validate_exercise(bp, exercise_raw, data.get("task_sheet")))
    return issues


def estimate_chinese_minutes(text: str, chars_per_minute: int = 220) -> float:
    count = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text))
    return round(count / chars_per_minute, 2)
