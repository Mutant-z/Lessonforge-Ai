from pathlib import Path

from app.schemas.artifact import PPTContent, Slide
from app.services.ppt_knowledge_service import check_ppt_against_knowledge
from app.services.ppt_validation_service import PPTXPackageValidator
from app.renderers.pptx_renderer import render_pptx


def test_anti_pattern_rule_violation_trigger():
    """测试包含装饰下划线或侧边彩条时，能被静态判定器正确捕获"""
    bad_ppt = PPTContent(
        slides=[
            Slide(
                id="S01", page_type="concept",
                title="核心概念讲解结论式标题",
                purpose="讲解概念",
                body=["包含关键要点一"],
                layout="split",
                visual_suggestion="建议在标题下方放置粗黄色装饰下划线，并在侧边放置彩条",
                speaker_notes="这里是详细的演讲备注内容，超过三十个字以满足字数密度要求限制。",
                duration_seconds=60
            )
        ]
    )
    violations = check_ppt_against_knowledge(bad_ppt)
    violation_ids = [v.rule_id for v in violations]
    assert "visual.anti_pattern" in violation_ids


def test_bullet_hardcoded_rule_violation_trigger():
    """测试包含硬编码符号 • 时，能被判定器捕获"""
    bad_ppt = PPTContent(
        slides=[
            Slide(
                id="S01", page_type="concept",
                title="核心概念讲解结论式标题",
                purpose="讲解概念",
                body=["• 包含关键要点一"],
                layout="split",
                visual_suggestion="左侧概念框图、右侧箭头图表示因果关系",
                speaker_notes="这里是详细的演讲备注内容，超过三十个字以满足字数密度要求限制。",
                duration_seconds=60
            )
        ]
    )
    violations = check_ppt_against_knowledge(bad_ppt)
    violation_ids = [v.rule_id for v in violations]
    assert "body.bullet_hardcoded" in violation_ids


def test_pptx_ooxml_package_validation(tmp_path: Path):
    """测试生成的 PPTX 导出的 ZIP 结构能够通过 Package Validator 审查"""
    valid_ppt = PPTContent(
        slides=[
            Slide(
                id="S01", page_type="cover",
                title="课程主题封面标题示例",
                purpose="展示封面",
                body=["主讲人：张老师"],
                layout="cover",
                visual_suggestion="纯白简洁背景，高对比度大字号标题",
                speaker_notes="这里是详细的演讲备注内容，超过三十个字以满足字数密度要求限制。",
                duration_seconds=60
            )
        ]
    )
    out_pptx = tmp_path / "valid_deck.pptx"
    render_pptx(title="测试课程", content=valid_ppt.model_dump(), output=out_pptx)

    issues = PPTXPackageValidator.validate_pptx(out_pptx)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) == 0, f"OOXML 校验产生错误: {errors}"
