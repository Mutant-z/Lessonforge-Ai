"""lesson_write_section 工具的 LLM block 归一化回归测试。

生产真实缺陷：模型写 {"type": "table", "header": [...]}（schema 要求
kind/columns/rows[{cells}]），写入候选稿后 LessonPlanContentV2 校验失败
（candidate_invalid），模型反复重试直至工具轮次耗尽、初始化失败。
归一化后这些变体一次写入成功。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.agent.agents.lesson_plan.builder import build_initial_builder
from app.agent.agents.lesson_plan.tools._common import normalize_blocks
from app.agents.generators import make_blueprint


def _builder():
    course = SimpleNamespace(
        title="3句话搞定咖啡厅英文点餐", subject="英语", grade_level="成人/通用初级",
        audience="成人初学者", duration_minutes=10, scenario="翻转微课", language="zh-CN",
        settings_json={},
    )
    return build_initial_builder(make_blueprint(course).model_dump())


def test_variant_table_with_header_and_list_rows_is_normalized():
    blocks = normalize_blocks([
        {"type": "table", "header": ["环节", "活动"], "rows": [["导入", "出示菜单"], ["操练", "替换饮品词"]]},
    ])
    assert blocks == [{
        "kind": "table", "title": "",
        "columns": ["环节", "活动"],
        "rows": [{"cells": ["导入", "出示菜单"]}, {"cells": ["操练", "替换饮品词"]}],
    }]


def test_variant_code_block_becomes_fenced_paragraph():
    blocks = normalize_blocks([
        {"type": "code", "language": "text", "code": "Can I get a latte, please?"},
    ])
    assert blocks == [{"kind": "paragraph", "text": "```text\nCan I get a latte, please?\n```"}]


def test_variant_bullets_steps_note_checklist_are_normalized():
    blocks = normalize_blocks([
        {"type": "bullets", "points": ["发音清晰", "两种替换词"]},
        {"type": "steps", "steps": [{"name": "示范", "description": "教师示范"}, "结对练习"]},
        {"kind": "note", "text": "注意 for here or to go。"},
        {"kind": "checklist", "items": [{"text": "完成对话", "checked": False}]},
        "纯字符串块",
        {"type": "paragraph", "content": "content 键的段落"},
    ])
    kinds = [block["kind"] for block in blocks]
    assert kinds == ["bullets", "steps", "note", "checklist", "paragraph", "paragraph"]
    assert blocks[0]["items"] == ["发音清晰", "两种替换词"]
    assert blocks[1]["steps"][0] == {"title": "示范", "detail": "教师示范"}
    assert blocks[1]["steps"][1] == {"title": "结对练习", "detail": ""}
    assert blocks[4] == {"kind": "paragraph", "text": "纯字符串块"}


def test_normalized_blocks_pass_builder_validate_content():
    builder = _builder()
    blocks = normalize_blocks([
        {"type": "table", "header": ["环节", "活动"], "rows": [["导入", "出示菜单"]]},
        {"type": "code", "language": "text", "code": "Can I get a latte?"},
        {"type": "bullets", "points": ["发音清晰"]},
        {"type": "steps", "steps": [{"name": "示范", "description": "教师示范"}]},
        {"kind": "note", "text": "注意应答。"},
    ])
    builder.write_section("SEC-CONTENT", blocks=blocks)
    assert builder.validate_content() == {"ok": True, "error": None}


def test_empty_and_unusable_blocks_are_dropped():
    blocks = normalize_blocks([
        {"type": "table", "header": [], "rows": []},
        {"kind": "paragraph", "text": ""},
        {"type": "note"},
    ])
    assert blocks == []
