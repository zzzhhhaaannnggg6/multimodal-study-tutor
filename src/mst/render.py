"""Optional local rendering of visual sources into reviewable page images."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RenderResult:
    source: str
    images: list[Path] = field(default_factory=list)
    renderer: str = "none"
    warnings: list[str] = field(default_factory=list)


def _tool(name: str) -> str | None:
    return shutil.which(name)


def _render_pdf(pdf_path: Path, output_dir: Path, stem: str) -> RenderResult:
    pdftoppm = _tool("pdftoppm")
    if not pdftoppm:
        return RenderResult(str(pdf_path), warnings=["未找到 pdftoppm，无法生成 PDF 页面图像。"])
    prefix = output_dir / stem
    command = [pdftoppm, "-png", "-r", "120", str(pdf_path), str(prefix)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        return RenderResult(str(pdf_path), renderer="pdftoppm", warnings=[f"PDF 页面渲染失败：{detail.strip()[:240]}"])
    images = sorted(output_dir.glob(f"{stem}-*.png"))
    return RenderResult(str(pdf_path), images=images, renderer="pdftoppm")


def render_visual_source(source: str | Path, output_dir: str | Path) -> RenderResult:
    """Render a PDF/PPTX to PNG pages without touching the source file."""

    source_path = Path(source).expanduser().resolve()
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf(source_path, target, source_path.stem)
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
            subprocess.run(command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            return RenderResult(str(source_path), renderer="soffice", warnings=[f"PPT 页面渲染失败：{detail.strip()[:240]}"])
        converted = temporary_dir / f"{source_path.stem}.pdf"
        if not converted.exists():
            candidates = sorted(temporary_dir.glob("*.pdf"))
            converted = candidates[0] if candidates else converted
        if not converted.exists():
            return RenderResult(str(source_path), renderer="soffice", warnings=["PPT 转换完成但没有找到临时 PDF。"])
        result = _render_pdf(converted, target, source_path.stem)
        result.source = str(source_path)
        result.renderer = "soffice+pdftoppm"
        return result


__all__ = ["RenderResult", "render_visual_source"]
