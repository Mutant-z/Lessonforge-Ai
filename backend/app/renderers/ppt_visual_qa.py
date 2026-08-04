import shutil
import subprocess
from pathlib import Path


class PPTVisualQARenderer:
    """使用 Headless LibreOffice 与 pdftoppm 将 PPTX 文件渲染为图片帧"""

    @staticmethod
    def is_available() -> bool:
        """检查系统环境是否安装了 soffice 与 pdftoppm"""
        has_soffice = shutil.which("soffice") is not None or shutil.which("libreoffice") is not None
        has_pdftoppm = shutil.which("pdftoppm") is not None
        return has_soffice and has_pdftoppm

    @classmethod
    def convert_pptx_to_images(cls, pptx_path: Path, output_dir: Path, dpi: int = 150) -> list[Path]:
        """
        1. 调用 LibreOffice 将 PPTX 导出为 PDF
        2. 调用 pdftoppm 将 PDF 转换为 slide-1.jpg, slide-2.jpg ...
        """
        if not cls.is_available():
            raise RuntimeError("系统缺失 soffice 或 pdftoppm 命令行工具，无法开启 Visual QA 渲染器")

        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f"{pptx_path.stem}.pdf"

        soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")

        # 步骤 1: PPTX -> PDF
        soffice_cmd = [
            soffice_bin,
            "--headless",
            "--convert-to", "pdf",
            str(pptx_path),
            "--outdir", str(output_dir),
        ]
        subprocess.run(soffice_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 步骤 2: 清理旧图并执行 PDF -> JPEG (pdftoppm)
        for old_img in output_dir.glob("slide-*.jpg"):
            old_img.unlink()

        prefix = str(output_dir / "slide")
        pdftoppm_cmd = [
            "pdftoppm",
            "-jpeg",
            "-r", str(dpi),
            str(pdf_path),
            prefix,
        ]
        subprocess.run(pdftoppm_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 步骤 3: 按文件名编号自然排序返回图片路径列表
        image_paths = sorted(list(output_dir.glob("slide-*.jpg")), key=lambda p: p.name)
        return image_paths
