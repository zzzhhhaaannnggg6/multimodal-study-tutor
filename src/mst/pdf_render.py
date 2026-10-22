"""Isolated, bounded local PDF preview worker; never OCR or a teaching model."""

from __future__ import annotations

import argparse
import math
import os
import sys
import threading
from pathlib import Path

from .io import write_json

MAX_PAGES = 200
MAX_OUTPUT_BYTES = 160 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_EDGE = 2400


def render_pages(source: Path, output: Path, *, page_limit=MAX_PAGES, byte_limit=MAX_OUTPUT_BYTES) -> dict:
    import pypdfium2 as pdfium

    result = {"renderer": "pdfium", "total_pages": None, "pages": {}, "warnings": []}
    report = output / "render-result.json"
    output.mkdir(parents=True, exist_ok=True)
    used = 0
    try:
        with pdfium.PdfDocument(str(source)) as document:
            total = len(document)
            result["total_pages"] = total
            if not total:
                result["warnings"].append("PDF 中没有可预览的页面。")
            if total > page_limit:
                result["warnings"].append(f"PDF 共 {total} 页，本次最多生成前 {page_limit} 页预览；其余页面仍待处理。")
            write_json(report, result)
            for index in range(min(total, page_limit)):
                page = bitmap = None
                try:
                    page = document[index]
                    width, height = page.get_size()
                    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                        raise ValueError("invalid page size")
                    scale = min(120 / 72, MAX_EDGE / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))
                    filename = f"page-{index + 1:04d}.png"
                    path = output / filename
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil()
                    try:
                        image.save(path, format="PNG")
                    finally:
                        image.close()
                    size = path.stat().st_size
                    if used + size > byte_limit:
                        path.unlink()
                        result["warnings"].append(f"页面预览已达到保存上限，第 {index + 1} 页及后续页面未生成；可按章节拆分材料。")
                        break
                    used += size
                    result["pages"][str(index + 1)] = filename
                except Exception:
                    # Keep the original page number after a per-page failure.
                    result["warnings"].append(f"第 {index + 1} 页预览失败；这一页的图示和公式仍待核对。")
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    if page is not None:
                        page.close()
                write_json(report, result)
    except Exception:
        result["warnings"].append("PDF 预览无法打开；文件可能损坏或需要密码。文字读取结果会另行说明。")
    write_json(report, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--page-limit", type=int, default=MAX_PAGES)
    parser.add_argument("--byte-limit", type=int, default=MAX_OUTPUT_BYTES)
    parser.add_argument("--watch-parent", action="store_true")
    args = parser.parse_args(argv)
    if not 0 < args.page_limit <= MAX_PAGES or not 0 < args.byte_limit <= MAX_OUTPUT_BYTES:
        parser.error("invalid preview budget")
    if args.watch_parent:
        def parent_closed():
            while os.read(sys.stdin.fileno(), 1024):
                pass
            os._exit(3)  # A closed app must not leave a native renderer running.
        threading.Thread(target=parent_closed, daemon=True).start()
    render_pages(args.source, args.output, page_limit=args.page_limit, byte_limit=args.byte_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
