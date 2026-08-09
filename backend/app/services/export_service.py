import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.agents.generators import deck_from_artifact
from app.renderers.docx_renderer import render_exercise_docx, render_markdown_docx, render_task_sheet_docx, render_video_script_docx
from app.renderers.deck_renderer import render_deck
from app.renderers.pptx_renderer import render_pptx
from app.schemas.blueprint import CourseBlueprintSchema
from app.services.ppt_template_service import ppt_template_catalog_version, resolve_ppt_template

from app.core.config import get_settings  # noqa: E402

CATALOG_DIR = Path(__file__).resolve().parents[3] / "templates" / "pptx"


def safe_package_name(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", title).strip(" .")
    return (cleaned or "课程")[:80]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_course_package(course_id: str, title: str, blueprint: dict, blueprint_version: int, artifacts: dict[str, dict], output_dir: Path) -> tuple[Path, dict]:
    folder = output_dir / f"{safe_package_name(title)}_微课资源包"
    folder.mkdir(parents=True, exist_ok=True)
    files = []

    def add(path: Path, artifact_type: str, version: int = 1, **metadata):
        files.append({"type": artifact_type, "version": version, "file": str(path.relative_to(folder)), "sha256": sha256(path), "size": path.stat().st_size, **metadata})

    mappings = [
        ("lesson_plan", "01_教学设计.docx", "教学设计"),
        ("verbatim", "08_教师逐字稿.docx", "教师逐字稿"),
    ]
    for kind, filename, label in mappings:
        if kind in artifacts:
            path = render_markdown_docx(label, artifacts[kind]["content_markdown"], folder / filename, f"V{artifacts[kind]['version']}")
            add(path, kind, artifacts[kind]["version"])
    if "video_script" in artifacts:
        video = artifacts["video_script"]
        schema_version = video["content_json"].get("schema_version", "1.0")
        source_versions = video.get("source_versions_json") or {}
        if schema_version == "2.0":
            path = render_video_script_docx(
                "微课视频脚本", video["content_json"], folder / "06_微课视频脚本.docx",
                f"V{video['version']}", source_versions,
            )
        else:
            path = render_markdown_docx("微课视频脚本", video["content_markdown"], folder / "06_微课视频脚本.docx", f"V{video['version']}")
        add(path, "video_script", video["version"], schema_version=schema_version, source_versions=source_versions)
        markdown_path = folder / "06_微课视频脚本.md"
        markdown_path.write_text(video["content_markdown"], encoding="utf-8")
        add(markdown_path, "video_script_markdown", video["version"], schema_version=schema_version, source_versions=source_versions)
    if "task_sheet" in artifacts:
        task_sheet = artifacts["task_sheet"]
        if task_sheet["content_json"].get("schema_version") == "2.0":
            path = render_task_sheet_docx("学习任务单", task_sheet["content_json"], folder / "03_学习任务单.docx", f"V{task_sheet['version']}")
        else:
            path = render_markdown_docx("学习任务单", task_sheet["content_markdown"], folder / "03_学习任务单.docx", f"V{task_sheet['version']}")
        add(path, "task_sheet", task_sheet["version"])
        markdown_path = folder / "03_学习任务单.md"
        markdown_path.write_text(task_sheet["content_markdown"], encoding="utf-8")
        add(markdown_path, "task_sheet_markdown", task_sheet["version"])
    if "ppt" in artifacts:
        ppt_content = artifacts["ppt"]["content_json"]
        theme = ppt_content.get("theme")
        template = resolve_ppt_template(theme)
        # 优先使用多 Agent 流水线生成的动态 PPTX（AI 动态布局真正进入成品）
        pipeline_file = Path(get_settings().storage_root) / "generated" / course_id / "ppt" / f"{artifacts['ppt']['version']}.pptx"
        if pipeline_file.is_file():
            path = pipeline_file
        elif any(slide.get("elements") for slide in (ppt_content.get("slides") or [])):
            # Historical agentic revisions (including V34) may predate the
            # versioned PPTX sidecar.  Rebuild them through the same canonical
            # semantic/hybrid/absolute renderer so generated images are not
            # dropped by the legacy deck slot filler.
            from app.renderers.presentation_builder import PresentationBuilder
            path = PresentationBuilder(template["id"]).from_ppt_content(ppt_content).render(folder / "02_课件.pptx")
        elif template.get("composition") == "deck":
            deck_path = (CATALOG_DIR / str(template["file"])).resolve()
            # 用 AI 生成的 artifact slides 内容填模板（不足角色 make_deck 兜底），
            # 使教师修订与 Agent 设计真正进入成品 PPT；render_deck 按模板读槽位填字
            deck = deck_from_artifact(CourseBlueprintSchema.model_validate(blueprint), ppt_content, template["id"])
            path = render_deck(deck_path, deck, folder / "02_课件.pptx", template["id"])
        else:
            path = render_pptx(title, ppt_content, folder / "02_课件.pptx")
        if not path.exists() or folder not in path.parents:
            # 流水线文件位于 storage/generated，复制进导出目录
            final = folder / "02_课件.pptx"
            final.write_bytes(path.read_bytes())
            path = final
        add(
            path,
            "ppt",
            artifacts["ppt"]["version"],
            template_id=template["id"],
            template_catalog_version=ppt_template_catalog_version(),
        )
    if "exercise" in artifacts:
        asset_paths = artifacts["exercise"].get("asset_paths") or {}
        student = render_exercise_docx("课后练习（学生版）", artifacts["exercise"]["content_json"], folder / "04_课后练习_学生版.docx", False, asset_paths)
        teacher = render_exercise_docx("课后练习（教师版）", artifacts["exercise"]["content_json"], folder / "05_课后练习_教师版.docx", True, asset_paths)
        add(student, "exercise_student", artifacts["exercise"]["version"]); add(teacher, "exercise_teacher", artifacts["exercise"]["version"])
    video = artifacts.get("video_generation")
    if video and video.get("status") == "approved":
        asset_paths = video.get("asset_paths") or {}
        outputs = video["content_json"].get("outputs") or {}
        video_folder = folder / "07_视频生成"
        scene_folder = video_folder / "分镜媒体"
        scene_folder.mkdir(parents=True, exist_ok=True)

        def copy_asset(asset_id: str | None, target: Path, artifact_type: str):
            if not asset_id or asset_id not in asset_paths:
                return
            source = Path(asset_paths[asset_id])
            if not source.is_file():
                return
            shutil.copy2(source, target)
            add(target, artifact_type, video["version"])

        copy_asset(outputs.get("final_asset_id"), video_folder / "微课视频.mp4", "video_final")
        copy_asset(outputs.get("preview_asset_id"), video_folder / "视频预览.mp4", "video_preview")
        copy_asset(outputs.get("subtitle_asset_id"), video_folder / "字幕.vtt", "video_subtitle")
        for scene in video["content_json"].get("scenes", []):
            copy_asset(scene.get("video_asset_id"), scene_folder / f"{scene.get('script_scene_id') or scene['id']}.mp4", "video_clip")
        config_path = video_folder / "视频生成配置.json"
        config_path.write_text(json.dumps(video["content_json"], ensure_ascii=False, indent=2), encoding="utf-8")
        add(config_path, "video_generation_config", video["version"])
    (folder / "09_质量报告.md").write_text(artifacts.get("quality_report", {}).get("content_markdown", "# 质量报告\n\n已通过系统结构化检查。"), encoding="utf-8")
    add(folder / "09_质量报告.md", "quality_report")
    (folder / "10_引用来源.md").write_text(artifacts.get("citation_report", {}).get("content_markdown", "# 引用来源\n\n详见课程蓝图中的 source_refs。"), encoding="utf-8")
    add(folder / "10_引用来源.md", "citation_report")
    (folder / "course_blueprint.json").write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
    add(folder / "course_blueprint.json", "blueprint", blueprint_version)
    manifest = {"course_id": course_id, "course_title": title, "blueprint_version": blueprint_version, "artifacts": files, "exported_at": datetime.now(timezone.utc).isoformat()}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = output_dir / f"{safe_package_name(title)}_微课资源包.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, f"{folder.name}/{path.relative_to(folder)}")
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP 校验失败：{bad}")
    return zip_path, manifest
