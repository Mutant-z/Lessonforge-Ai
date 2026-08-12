from types import SimpleNamespace

import pytest

from app.schemas.artifact import AgentArtifactRevisionPayload
from app.services.course_task_service import (
    _generate_ppt_revision,
    _restore_locked_paths,
    _validate_and_repair_ppt,
)


def _content():
    return {"theme": "lessonforge_deck_academic", "slides": [
        {"id": "S01", "page_type": "cover", "title": "浮力原理", "purpose": "p", "body": ["初中物理"],
         "layout": "cover", "visual_suggestion": "封面留白大标题与副标题", "speaker_notes": "开场引入课程主题并说明本课要回答的核心问题。",
         "duration_seconds": 30, "blocks": []},
        {"id": "S02", "page_type": "objectives", "title": "本课学习目标", "purpose": "p", "body": ["完成本节后能够说明浮力的来源"],
         "layout": "bullet", "visual_suggestion": "编号列表，编号用主题色徽章", "speaker_notes": "逐条说明学习目标并给出课堂环节对应。",
         "duration_seconds": 60, "blocks": []},
    ]}


def test_validate_and_repair_fixes_knowledge_violations():
    content = {"theme": "lessonforge_deck_academic", "slides": [
        {"id": "S01", "page_type": "objectives", "title": "学习目标", "purpose": "p",
         "body": ["这是一条超过二十五个字符的正文要点内容测试超长条目abc"], "layout": "cover",
         "visual_suggestion": "简洁", "speaker_notes": "短", "duration_seconds": 0, "blocks": []},
    ]}
    repaired, err = _validate_and_repair_ppt(content)
    assert err == ""
    slide = repaired["slides"][0]
    assert slide["title"] == "本课学习目标"          # 黑名单标题修复
    assert len(slide["body"][0]) <= 25              # 条目截断
    assert len(slide["speaker_notes"]) >= 30        # 备注补足
    assert slide["layout"] == "bullet"              # 版式修复
    assert slide["duration_seconds"] >= 20          # 时长修复


def test_validate_and_repair_returns_none_on_schema_failure():
    content = {"theme": "lessonforge_deck_academic", "slides": [
        {"id": "S01", "page_type": "cover", "title": "x"},  # 缺必填字段
    ]}
    repaired, err = _validate_and_repair_ppt(content)
    assert repaired is None
    assert "结构校验失败" in err


def test_validate_and_repair_coerces_invented_block_kinds():
    """模型为"打破单调"发明的非法块结构（如 cards）必须规范化为合法 bullets，
    而不是在流水线末端 PPTContent 校验时硬失败。"""
    content = {"theme": "lessonforge_deck_academic", "slides": [
        {"id": "S01", "page_type": "concept", "title": "浮力成因", "purpose": "p",
         "body": ["压力差产生浮力"], "layout": "bullet",
         "visual_suggestion": "左文右图", "speaker_notes": "本页讲解上下表面压力差如何形成浮力。",
         "duration_seconds": 30,
         "blocks": [{"kind": "cards", "cards": [
             {"title": "1. 侧面平衡", "desc": "四周受力对称抵消"},
             {"title": "2. 上下差值", "desc": "下表面压力更大"},
         ]}]},
    ]}
    repaired, err = _validate_and_repair_ppt(content)
    assert err == ""
    block = repaired["slides"][0]["blocks"][0]
    assert block["kind"] == "bullets"
    assert [item["text"] for item in block["items"]] == ["1. 侧面平衡", "四周受力对称抵消", "2. 上下差值", "下表面压力更大"]


def test_validate_and_repair_clips_dense_block_bullets():
    """blocks 的 bullets 条目超 25 字（含装饰前缀）必须被确定性收敛，
    不能继续阻断 QA 门禁/最终校验。"""
    from app.services.ppt_knowledge_service import check_ppt_against_knowledge

    content = {"theme": "lessonforge_deck_academic", "slides": [
        {"id": "S01", "page_type": "concept", "title": "浮力成因", "purpose": "p",
         "body": ["压力差产生浮力"], "layout": "bullet",
         "visual_suggestion": "左文右图", "speaker_notes": "本页讲解上下表面压力差如何形成浮力。",
         "duration_seconds": 30,
         "blocks": [{"kind": "bullets", "items": [
             {"text": "🔹 本质公式：上下表面压力差形成浮力 F浮=F下-F上"},
         ]}]},
    ]}
    repaired, err = _validate_and_repair_ppt(content)
    assert err == ""
    item = repaired["slides"][0]["blocks"][0]["items"][0]
    assert len(item["text"]) <= 25
    assert not item["text"].startswith("🔹")
    assert not check_ppt_against_knowledge(repaired)


def test_validate_and_repair_clips_long_unit_without_ellipsis_overflow():
    """截断不得产生 26 字（25 字 + 省略号）：无尾随标点时也必须 ≤25 字，
    否则修复轮永远无法收敛（第 1 个文本单元 26 字 > 25 字）。"""
    from app.services.ppt_knowledge_service import check_ppt_against_knowledge

    content = {"theme": "lessonforge_deck_academic", "slides": [
        {"id": "S01", "page_type": "concept", "title": "浮力成因", "purpose": "p",
         "body": ["压力差产生浮力"], "layout": "bullet",
         "visual_suggestion": "左文右图", "speaker_notes": "本页讲解上下表面压力差如何形成浮力。",
         "duration_seconds": 30,
         "blocks": [{"kind": "quote", "text": "深度增加使水压显著增大，但完全浸没后浮力为什么保持不变？",
                     "citation": "预习难点剖析"}]},
    ]}
    repaired, err = _validate_and_repair_ppt(content)
    assert err == ""
    text = repaired["slides"][0]["blocks"][0]["text"]
    assert len(text) <= 25
    assert not check_ppt_against_knowledge(repaired)


def test_restore_locked_paths_preserves_locked_values():
    source = _content()
    ai = _content()
    ai["slides"][0]["title"] = "被AI修改的标题"
    ai["slides"][1]["body"] = ["被改"]
    locks = [SimpleNamespace(json_path="$.slides.S01.title")]
    restored = _restore_locked_paths(ai, source, locks)
    assert restored["slides"][0]["title"] == "浮力原理"       # 锁定还原
    assert restored["slides"][1]["body"] == ["被改"]          # 未锁定的允许修改


class _FakeProvider:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    async def structured(self, system, prompt, schema):
        self.calls.append(schema.__name__)
        return self._payloads.pop(0)


@pytest.mark.asyncio
async def test_ppt_revision_uses_ai_full_content_and_returns_reply():
    revised = _content()
    revised["slides"][0]["title"] = "润色后的标题"
    provider = _FakeProvider([AgentArtifactRevisionPayload(content_json=revised, assistant_reply="已润色标题")])
    profile = SimpleNamespace(rendered_system_prompt="sys", rendered_task_template="TASK {{output_schema_json}}")
    source = SimpleNamespace(content_json=_content())
    revision = await _generate_ppt_revision(provider, profile, {}, "润色", source, [])
    assert revision.content_json["slides"][0]["title"] == "润色后的标题"
    assert revision.assistant_reply == "已润色标题"
    assert provider.calls == ["AgentArtifactRevisionPayload"]


@pytest.mark.asyncio
async def test_ppt_revision_retries_when_first_output_invalid():
    # 第 1 次结构非法 → 重试；第 2 次合法 → 采用
    invalid = {"slides": [{"id": "S01"}]}  # 缺必填字段，结构校验失败
    revised = _content()
    revised["slides"][0]["title"] = "重试后标题"
    provider = _FakeProvider([
        AgentArtifactRevisionPayload(content_json=invalid, assistant_reply="第一版"),
        AgentArtifactRevisionPayload(content_json=revised, assistant_reply="第二版"),
    ])
    profile = SimpleNamespace(rendered_system_prompt="sys", rendered_task_template="TASK {{output_schema_json}}")
    source = SimpleNamespace(content_json=_content())
    revision = await _generate_ppt_revision(provider, profile, {}, "润色", source, [])
    assert revision.content_json["slides"][0]["title"] == "重试后标题"
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_ppt_revision_falls_back_to_original_when_all_invalid():
    provider = _FakeProvider([
        AgentArtifactRevisionPayload(content_json={"slides": [{"id": "S01"}]}, assistant_reply="一"),
        AgentArtifactRevisionPayload(content_json={"slides": [{"id": "S01"}]}, assistant_reply="二"),
    ])
    profile = SimpleNamespace(rendered_system_prompt="sys", rendered_task_template="TASK {{output_schema_json}}")
    source = SimpleNamespace(content_json=_content())
    revision = await _generate_ppt_revision(provider, profile, {}, "润色", source, [])
    assert revision.content_json == source.content_json  # 保留原稿
    assert "已保留原稿" in revision.assistant_reply
