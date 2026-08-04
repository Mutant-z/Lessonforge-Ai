import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    component: str
    message: str


class PPTXPackageValidator:
    """针对生成的 .pptx 文件进行 OOXML 规范与 XML 结构校验"""

    REQUIRED_PARTS = [
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    ]

    @classmethod
    def validate_pptx(cls, pptx_path: Path) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not pptx_path.exists():
            return [ValidationIssue("error", "file", f"文件不存在: {pptx_path}")]

        if not zipfile.is_zipfile(pptx_path):
            return [ValidationIssue("error", "zip", "该文件不是合法的 ZIP/PPTX 格式归档")]

        try:
            with zipfile.ZipFile(pptx_path, "r") as zf:
                namelist = set(zf.namelist())

                # 1. 检查必需的文件项
                for part in cls.REQUIRED_PARTS:
                    if part not in namelist:
                        issues.append(ValidationIssue("error", "ooxml_structure", f"缺少 OOXML 核心组件: {part}"))

                # 2. 检查 Slide 关系引用
                slide_files = [name for name in namelist if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
                if not slide_files:
                    issues.append(ValidationIssue("error", "slides", "演示文稿中未包含任何幻灯片页面 (ppt/slides/slideN.xml)"))

                # 3. 逐个解析 XML 防止 XML 语法损坏
                for name in namelist:
                    if name.endswith(".xml") or name.endswith(".rels"):
                        try:
                            content = zf.read(name)
                            ET.fromstring(content)
                        except ET.ParseError as e:
                            issues.append(ValidationIssue("error", "xml_parse", f"XML 语法解析失败 [{name}]: {e}"))
        except Exception as e:
            issues.append(ValidationIssue("error", "unknown", f"读取 PPTX 归档发生异常: {str(e)}"))

        return issues
