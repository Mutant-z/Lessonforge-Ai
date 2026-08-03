import json

from pydantic import BaseModel, Field

from app.providers.llm.base import LLMProvider
from app.providers.llm.mock import MockProvider
from app.schemas.artifact import ExerciseContent


class ExerciseReviewFinding(BaseModel):
    path: str = Field(min_length=1)
    severity: str = "major"
    description: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class ExerciseTextReview(BaseModel):
    passed: bool
    findings: list[ExerciseReviewFinding] = Field(default_factory=list)


REVIEW_SYSTEM = (
    "你是课后练习质量复核器。只检查答案正确性、干扰项唯一性、材料可解性、解析一致性、"
    "主观题评分点可判定性、年级适切性，以及是否直接复用任务单。"
    "不得修改课程事实，不展示推理过程，只返回结构化问题。"
)


def degrade_unreviewed_visuals(raw: dict) -> tuple[dict, list[str]]:
    """Replace unsafe/unreviewed generated visuals with their required fallback."""
    content = json.loads(json.dumps(raw, ensure_ascii=False))
    notes: list[str] = []
    for section in content.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("kind") != "question_group":
                continue
            for stimulus in block.get("stimuli", []):
                visual = stimulus.get("visual") if stimulus.get("kind") == "visual" else None
                if not visual or visual.get("mode") != "generated_image":
                    continue
                if visual.get("status") == "approved" and visual.get("asset_id"):
                    continue
                visual_id = visual.get("visual_id") or stimulus.get("id") or "未编号视觉材料"
                fallback = visual.get("fallback_stimulus") or visual.get("alt_text") or "请根据题干文字作答。"
                stimulus.clear()
                stimulus.update({
                    "id": f"{visual_id}-fallback",
                    "kind": "text",
                    "title": "替代材料",
                    "text": fallback,
                    "columns": [],
                    "rows": [],
                    "visual": None,
                })
                notes.append(f"{visual_id} 未通过视觉复核，已自动使用等价文字材料。")
    return content, notes


async def _review(provider: LLMProvider, content: ExerciseContent, task_sheet: dict | None) -> ExerciseTextReview:
    if isinstance(provider, MockProvider):
        return ExerciseTextReview(passed=True)
    prompt = json.dumps({
        "exercise": content.model_dump(),
        "task_sheet_reference": task_sheet or {},
        "output_rules": "findings 必须给出具体 JSON path；没有问题时 passed=true 且 findings=[]。",
    }, ensure_ascii=False)
    return await provider.structured(REVIEW_SYSTEM, prompt, ExerciseTextReview)


async def review_and_repair_exercise(
    provider: LLMProvider,
    content: ExerciseContent,
    task_sheet: dict | None,
) -> tuple[ExerciseContent, list[dict]]:
    first = await _review(provider, content, task_sheet)
    if first.passed and not first.findings:
        data = content.model_dump()
        data["review_summary"]["text_review_status"] = "passed"
        return ExerciseContent.model_validate(data), []

    if not isinstance(provider, MockProvider):
        repair_prompt = json.dumps({
            "current_exercise": content.model_dump(),
            "findings": [item.model_dump() for item in first.findings],
            "instruction": (
                "只修复 findings 指向的问题；保持课程身份、三区顺序、目标和知识点合法引用，"
                "总分必须为100，主观题评分点之和等于题目分值。review_summary 保持 pending。"
            ),
        }, ensure_ascii=False)
        content = await provider.structured(
            "你是课后练习定向修复器。只返回修复后的 ExerciseContent JSON，不展示推理。",
            repair_prompt,
            ExerciseContent,
        )
        second = await _review(provider, content, task_sheet)
    else:
        second = first

    unresolved = [item.model_dump() for item in second.findings]
    data = content.model_dump()
    data["review_summary"]["text_review_status"] = "passed" if not unresolved else "needs_attention"
    data["review_summary"]["needs_teacher_attention"] = bool(unresolved)
    data["review_summary"]["notes"].extend(item["description"] for item in unresolved)
    return ExerciseContent.model_validate(data), unresolved
