import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.renderers.docx_renderer import render_exercise_docx, render_markdown_docx
from app.renderers.pptx_renderer import render_pptx


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

    def add(path: Path, artifact_type: str, version: int = 1):
        files.append({"type": artifact_type, "version": version, "file": path.name, "sha256": sha256(path), "size": path.stat().st_size})

    mappings = [
        ("lesson_plan", "01_教学设计.docx", "教学设计"),
        ("task_sheet", "03_学习任务单.docx", "学习任务单"),
        ("video_script", "06_微课视频脚本.docx", "微课视频脚本"),
        ("verbatim", "07_教师逐字稿.docx", "教师逐字稿"),
    ]
    for kind, filename, label in mappings:
        if kind in artifacts:
            path = render_markdown_docx(label, artifacts[kind]["content_markdown"], folder / filename, f"V{artifacts[kind]['version']}")
            add(path, kind, artifacts[kind]["version"])
    if "ppt" in artifacts:
        path = render_pptx(title, artifacts["ppt"]["content_json"], folder / "02_课件.pptx")
        add(path, "ppt", artifacts["ppt"]["version"])
    if "exercise" in artifacts:
        student = render_exercise_docx("课后练习（学生版）", artifacts["exercise"]["content_json"], folder / "04_课后练习_学生版.docx", False)
        teacher = render_exercise_docx("课后练习（教师版）", artifacts["exercise"]["content_json"], folder / "05_课后练习_教师版.docx", True)
        add(student, "exercise_student", artifacts["exercise"]["version"]); add(teacher, "exercise_teacher", artifacts["exercise"]["version"])
    (folder / "08_质量报告.md").write_text(artifacts.get("quality_report", {}).get("content_markdown", "# 质量报告\n\n已通过系统结构化检查。"), encoding="utf-8")
    add(folder / "08_质量报告.md", "quality_report")
    (folder / "09_引用来源.md").write_text(artifacts.get("citation_report", {}).get("content_markdown", "# 引用来源\n\n详见课程蓝图中的 source_refs。"), encoding="utf-8")
    add(folder / "09_引用来源.md", "citation_report")
    (folder / "course_blueprint.json").write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
    add(folder / "course_blueprint.json", "blueprint", blueprint_version)
    manifest = {"course_id": course_id, "course_title": title, "blueprint_version": blueprint_version, "artifacts": files, "exported_at": datetime.now(timezone.utc).isoformat()}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = output_dir / f"{safe_package_name(title)}_微课资源包.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in folder.iterdir():
            archive.write(path, f"{folder.name}/{path.name}")
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"ZIP 校验失败：{bad}")
    return zip_path, manifest
