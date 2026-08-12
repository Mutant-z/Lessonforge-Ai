import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image


class PPTVisualQARenderer:
    """使用 Headless LibreOffice 与 pdftoppm 将 PPTX 文件渲染为图片帧"""

    @staticmethod
    def _binary(name: str) -> str | None:
        resolved = shutil.which(name)
        if resolved:
            return resolved
        # Desktop builds bundle document binaries outside the service PATH.
        # Discover that runtime explicitly so QA does not silently degrade just
        # because the API process was launched from Finder/systemd.
        bundled = (
            Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime"
            / "dependencies" / "bin" / "override" / name
        )
        if bundled.is_file():
            return str(bundled)
        if name in {"soffice", "libreoffice"}:
            macos = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
            if macos.is_file():
                return str(macos)
        return None

    @staticmethod
    def is_available() -> bool:
        """检查系统环境是否安装了 soffice 与 pdftoppm"""
        has_soffice = PPTVisualQARenderer._binary("soffice") is not None or PPTVisualQARenderer._binary("libreoffice") is not None
        has_pdftoppm = PPTVisualQARenderer._binary("pdftoppm") is not None
        return has_soffice and has_pdftoppm

    @staticmethod
    def _discover_cjk_font() -> tuple[str, Path] | None:
        """Return a host font that actually declares Simplified Chinese glyphs.

        The desktop runtime bundles a self-contained LibreOffice build.  Its
        default fontconfig file only scans the legacy macOS font directories,
        while current macOS releases keep PingFang under ``AssetsV2``.  A
        missing Microsoft YaHei therefore used to make every Chinese glyph
        disappear from candidate previews and visual-QA evidence.
        """
        fc_match = shutil.which("fc-match")
        if not fc_match:
            return None
        try:
            result = subprocess.run(
                [fc_match, "-f", "%{family}\n%{file}\n", ":lang=zh-cn"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        family = lines[0].split(",", 1)[0].strip()
        font_path = Path(lines[1]).expanduser()
        if not family or not font_path.is_file():
            return None
        return family, font_path

    @classmethod
    def _fontconfig_environment(cls, profile_dir: Path) -> dict[str, str]:
        """Build an isolated fontconfig environment for the render process."""
        environment = os.environ.copy()
        discovered = cls._discover_cjk_font()
        if discovered is None:
            return environment
        family, font_path = discovered
        cache_dir = profile_dir / "font-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        config_path = profile_dir / "fonts.conf"
        aliases = (
            "Microsoft YaHei", "Microsoft JhengHei", "SimHei", "SimSun",
            "DengXian", "FangSong", "KaiTi",
        )
        alias_rules = "\n".join(
            (
                "  <match target=\"pattern\">"
                f"<test name=\"family\"><string>{escape(alias)}</string></test>"
                "<edit name=\"family\" mode=\"prepend\" binding=\"strong\">"
                f"<string>{escape(family)}</string></edit></match>"
            )
            for alias in aliases
        )
        font_dirs = [
            font_path.parent,
            Path("/System/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"),
            Path("/Library/Fonts"),
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
        ]
        directory_rules = "\n".join(
            f"  <dir>{escape(str(path))}</dir>"
            for path in dict.fromkeys(font_dirs)
            if path.is_dir()
        )
        config_path.write_text(
            "\n".join((
                '<?xml version="1.0"?>',
                '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">',
                "<fontconfig>",
                directory_rules,
                "  <dir prefix=\"xdg\">fonts</dir>",
                "  <dir>~/.fonts</dir>",
                f"  <cachedir>{escape(str(cache_dir))}</cachedir>",
                alias_rules,
                "  <config><rescan><int>0</int></rescan></config>",
                "</fontconfig>",
            )),
            encoding="utf-8",
        )
        environment["FONTCONFIG_FILE"] = str(config_path)
        return environment

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
        # QA may render several candidates/repair rounds into the same run
        # directory.  LibreOffice does not reliably overwrite a previous PDF
        # and a reused user profile can retain a stale lock after a cancelled
        # conversion, both of which used to surface as false
        # ``render.evidence_missing`` failures.
        pdf_path.unlink(missing_ok=True)
        # Keep the profile in the system temp root.  LibreOffice creates Unix
        # sockets below this directory; nesting it under a long course/run
        # workspace can exceed the platform socket-path limit.
        profile_dir = Path(tempfile.mkdtemp(prefix="lessonforge-lo-"))

        soffice_bin = cls._binary("soffice") or cls._binary("libreoffice")
        pdftoppm_bin = cls._binary("pdftoppm")
        if not soffice_bin or not pdftoppm_bin:
            raise RuntimeError("Visual QA 渲染器二进制不完整")

        # 步骤 1: PPTX -> PDF
        soffice_cmd = [
            soffice_bin,
            "--headless",
            f"-env:UserInstallation=file://{profile_dir.resolve()}",
            "--convert-to", "pdf",
            str(pptx_path),
            "--outdir", str(output_dir),
        ]
        try:
            subprocess.run(
                soffice_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=90, env=cls._fontconfig_environment(profile_dir),
            )
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)

        # 步骤 2: 清理旧图并执行 PDF -> JPEG (pdftoppm)
        for old_img in output_dir.glob("slide-*.jpg"):
            old_img.unlink()

        prefix = str(output_dir / "slide")
        pdftoppm_cmd = [
            pdftoppm_bin,
            "-jpeg",
            "-r", str(dpi),
            str(pdf_path),
            prefix,
        ]
        subprocess.run(
            pdftoppm_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=90,
        )

        # 步骤 3: 按文件名编号自然排序返回图片路径列表
        def page_number(path: Path) -> int:
            match = re.search(r"-(\d+)$", path.stem)
            return int(match.group(1)) if match else 0

        image_paths = sorted(output_dir.glob("slide-*.jpg"), key=page_number)
        return image_paths

    @staticmethod
    def raster_metrics(
        image_path: Path,
        *,
        body_box: tuple[float, float, float, float] | None = None,
        slide_size: tuple[float, float] = (13.333, 7.5),
    ) -> dict[str, float]:
        """Measure actual rendered occupancy instead of textbox bounding boxes.

        The body crop deliberately excludes the title rail.  A wide title can
        therefore no longer make a page whose teaching copy is packed into the
        top third look well-utilised.
        """
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        if body_box is not None:
            x, y, w, h = body_box
            sx, sy = width / slide_size[0], height / slide_size[1]
            crop = (
                max(0, round(x * sx)), max(0, round(y * sy)),
                min(width, round((x + w) * sx)), min(height, round((y + h) * sy)),
            )
            image = image.crop(crop)
        image.thumbnail((800, 500))
        if image.width <= 0 or image.height <= 0:
            return {
                "ink_ratio": 0.0, "vertical_utilization": 0.0,
                "horizontal_utilization": 0.0, "largest_blank_ratio": 1.0,
                "centroid_x": 0.5, "centroid_y": 0.5,
            }

        # Keep raster QA deployable with the service's normal Pillow-only
        # dependency set.  The dominant 4-bit RGB bucket is normally the
        # slide/card background; a downsample is sufficient to identify it.
        sample = image.copy()
        sample.thumbnail((200, 125))
        buckets = Counter(
            (red // 16, green // 16, blue // 16)
            for red, green, blue in sample.get_flattened_data()
        )
        dominant = buckets.most_common(1)[0][0] if buckets else (15, 15, 15)
        background = tuple(value * 16 + 8 for value in dominant)
        rows, cols = 14, 24
        ink_by_cell = [[0] * cols for _ in range(rows)]
        total_by_cell = [[0] * cols for _ in range(rows)]
        ink_count = sum_x = sum_y = 0
        width, height = image.size
        pixels = image.get_flattened_data()
        for y in range(height):
            row_pixels = pixels[y * width:(y + 1) * width]
            grid_y = min(rows - 1, y * rows // height)
            for x, (red, green, blue) in enumerate(row_pixels):
                grid_x = min(cols - 1, x * cols // width)
                total_by_cell[grid_y][grid_x] += 1
                distance_squared = (
                    (red - background[0]) ** 2
                    + (green - background[1]) ** 2
                    + (blue - background[2]) ** 2
                )
                if distance_squared > 28 ** 2:
                    ink_by_cell[grid_y][grid_x] += 1
                    ink_count += 1
                    sum_x += x
                    sum_y += y
        grid = [
            [
                bool(total_by_cell[row][col])
                and ink_by_cell[row][col] / total_by_cell[row][col] >= 0.012
                for col in range(cols)
            ]
            for row in range(rows)
        ]
        occupied_rows = [row for row in range(rows) if any(grid[row])]
        occupied_cols = [col for col in range(cols) if any(grid[row][col] for row in range(rows))]
        vertical = (
            float(occupied_rows[-1] - occupied_rows[0] + 1) / rows
            if occupied_rows else 0.0
        )
        horizontal = (
            float(occupied_cols[-1] - occupied_cols[0] + 1) / cols
            if occupied_cols else 0.0
        )

        # Largest all-empty grid rectangle (histogram algorithm).
        heights = [0] * cols
        largest_blank = 0
        for row in range(rows):
            for col in range(cols):
                heights[col] = 0 if grid[row][col] else heights[col] + 1
            stack: list[int] = []
            for col in range(cols + 1):
                current = heights[col] if col < cols else 0
                while stack and heights[stack[-1]] > current:
                    top = stack.pop()
                    left = stack[-1] + 1 if stack else 0
                    largest_blank = max(largest_blank, heights[top] * (col - left))
                stack.append(col)

        centroid_x = float(sum_x / ink_count / max(1, width - 1)) if ink_count else 0.5
        centroid_y = float(sum_y / ink_count / max(1, height - 1)) if ink_count else 0.5
        return {
            "ink_ratio": round(ink_count / max(1, width * height), 4),
            "vertical_utilization": round(vertical, 4),
            "horizontal_utilization": round(horizontal, 4),
            "largest_blank_ratio": round(largest_blank / (rows * cols), 4),
            "centroid_x": round(centroid_x, 4),
            "centroid_y": round(centroid_y, 4),
        }

    @staticmethod
    def compose_before_after(before: Path, after: Path, output: Path) -> Path:
        """Create one labelled image for a pairwise vision-model review."""
        left = Image.open(before).convert("RGB")
        right = Image.open(after).convert("RGB")
        target_h = max(left.height, right.height)
        if left.height != target_h:
            left = left.resize((round(left.width * target_h / left.height), target_h))
        if right.height != target_h:
            right = right.resize((round(right.width * target_h / right.height), target_h))
        canvas = Image.new("RGB", (left.width + right.width, target_h + 48), "white")
        canvas.paste(left, (0, 48))
        canvas.paste(right, (left.width, 48))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(canvas)
        draw.text((16, 15), "BEFORE / 修改前", fill="black")
        draw.text((left.width + 16, 15), "AFTER / 修改后", fill="black")
        output.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output, format="PNG")
        return output
