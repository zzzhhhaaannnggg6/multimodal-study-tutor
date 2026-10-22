"""Optional local rendering of visual sources into reviewable page images."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .io import read_json
from .pdf_render import MAX_OUTPUT_BYTES, MAX_PAGES

PDF_TIMEOUT_SECONDS = 90


@dataclass
class RenderResult:
    source: str
    images: list[Path] = field(default_factory=list)
    renderer: str = "none"
    warnings: list[str] = field(default_factory=list)
    page_images: dict[int, Path] = field(default_factory=dict)
    total_pages: int | None = None


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _pdfium_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("pypdfium2", "PIL"))


def _render_pdf(pdf_path: Path, output_dir: Path, stem: str, *, page_limit=MAX_PAGES, byte_limit=MAX_OUTPUT_BYTES) -> RenderResult:
    if _pdfium_available():
        result = RenderResult(str(pdf_path), renderer="pdfium")
        # Stage each invocation so failed/repeated renders cannot reuse an old
        # image as evidence for a different or changed page.
        with tempfile.TemporaryDirectory(prefix=".pdf-preview-", dir=output_dir) as temporary:
            stage = Path(temporary)
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--render-pdf"]
            else:
                command = [sys.executable, "-m", "mst.pdf_render"]
            command += [str(pdf_path), str(stage), "--page-limit", str(page_limit), "--byte-limit", str(byte_limit), "--watch-parent"]
            environment = dict(os.environ)
            if not getattr(sys, "frozen", False):
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            try:
                child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=environment)
                try:
                    code = child.wait(PDF_TIMEOUT_SECONDS)
                    if code:
                        result.warnings.append("PDF 预览进程未正常完成；已生成的页面仍可查看，其余页面待处理。")
                except subprocess.TimeoutExpired:
                    result.warnings.append("PDF 页面预览超时；已生成的页面仍可查看，可按章节拆分后重试。")
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                    child.stdin.close()
            except OSError:
                result.warnings.append("PDF 预览未能启动；文字读取结果会另行说明。")
            try:
                report = read_json(stage / "render-result.json")
                result.total_pages = report.get("total_pages")
                result.warnings.extend(report.get("warnings", []))
                for number, filename in report.get("pages", {}).items():
                    page = int(number)
                    if not 0 < page <= page_limit or filename != f"page-{page:04d}.png":
                        continue
                    image = stage / filename
                    if not image.is_file():
                        continue
                    target = output_dir / f"{stem}-{page:04d}.png"
                    image.replace(target)
                    result.page_images[page] = target
            except (OSError, ValueError, TypeError, AttributeError):
                result.warnings.append("未得到完整的 PDF 预览记录，缺失页面仍待处理。")
        result.images = [path for _, path in sorted(result.page_images.items())]
        return result
    pdftoppm = _tool("pdftoppm")
    if not pdftoppm:
        return RenderResult(str(pdf_path), warnings=["未安装 PDF 页面预览组件；文字仍可读取。可使用自带预览组件的桌面版，或安装项目的 pdf 可选依赖。"])
    result = RenderResult(str(pdf_path), renderer="pdftoppm")
    with tempfile.TemporaryDirectory(prefix=".pdf-preview-", dir=output_dir) as temporary:
        stage = Path(temporary)
        command = [pdftoppm, "-png", "-r", "120", "-scale-to", "2400", "-f", "1", "-l", str(page_limit), str(pdf_path), str(stage / "page")]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PDF_TIMEOUT_SECONDS)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            result.warnings.append("PDF 页面预览未完整完成；已生成的页面仍可查看，其余页面待处理。")
        used = 0
        numbered = [(int(match[1]), path) for path in stage.glob("page-*.png") if (match := re.fullmatch(r"page-(\d+)\.png", path.name))]
        for page, image in sorted(numbered):
            if page > page_limit:
                continue
            used += image.stat().st_size
            if used > byte_limit:
                result.warnings.append("页面预览已达到保存上限；后续页面未生成，可按章节拆分材料。")
                break
            target = output_dir / f"{stem}-{page:04d}.png"
            image.replace(target)
            result.page_images[page] = target
        if len(result.page_images) == page_limit:
            result.warnings.append(f"本次最多预览前 {page_limit} 页；若原文件更多，后续页面仍待处理。")
    result.images = [path for _, path in sorted(result.page_images.items())]
    return result


def render_visual_source(source: str | Path, output_dir: str | Path, *, page_limit=MAX_PAGES, byte_limit=MAX_OUTPUT_BYTES) -> RenderResult:
    """Render a PDF/PPTX to PNG pages without touching the source file."""

    source_path = Path(source).expanduser().resolve()
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf(source_path, target, source_path.stem, page_limit=page_limit, byte_limit=byte_limit)
    if suffix not in {".pptx", ".ppt"}:
        return RenderResult(str(source_path), warnings=[f"暂不支持渲染 {suffix or '无扩展名'} 页面。"])

    soffice = _tool("soffice") or _tool("libreoffice")
    if not soffice:
        return RenderResult(str(source_path), warnings=["未找到 soffice/libreoffice，无法把 PPT 转成页面图像。"])
    with tempfile.TemporaryDirectory(prefix="mst-render-") as temporary:
        temporary_dir = Path(temporary)
        command = [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(temporary_dir),
            str(source_path),
        ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PDF_TIMEOUT_SECONDS)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return RenderResult(str(source_path), renderer="soffice", warnings=["PPT 页面预览失败或超时；可将课件另存为 PDF 后重新导入。"])
        converted = temporary_dir / f"{source_path.stem}.pdf"
        if not converted.exists():
            candidates = sorted(temporary_dir.glob("*.pdf"))
            converted = candidates[0] if candidates else converted
        if not converted.exists():
            return RenderResult(str(source_path), renderer="soffice", warnings=["PPT 转换完成但没有找到临时 PDF。"])
        result = _render_pdf(converted, target, source_path.stem, page_limit=page_limit, byte_limit=byte_limit)
        result.source = str(source_path)
        result.renderer = "soffice+" + result.renderer
        return result


__all__ = ["RenderResult", "render_visual_source"]
