"""Student-facing extraction receipts, distinct from teaching completeness."""

from pathlib import Path

from .io import project_paths, read_json


def _records(value) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def material_results(workspace: Path, files: list[dict]) -> list[dict]:
    paths = project_paths(workspace)
    try:
        manifest = read_json(paths["manifest"])
        data = read_json(paths["lesson_map"])
    except (OSError, ValueError):
        manifest, data = {}, {}
    if not isinstance(manifest, dict) or not isinstance(data, dict):
        manifest, data = {}, {}
    sources = {row.get("name"): row for row in _records(manifest.get("source_manifest"))}
    notes = data.get("notes") if isinstance(data.get("notes"), dict) else {}
    results = []
    for file in files:
        source = sources.get(file["stored_name"], {})
        source_id = source.get("source_id")
        pages = [row for row in _records(data.get("pages")) if source_id and row.get("source_id") == source_id and "text" in row]
        speech = [row for row in _records(data.get("speech_segments")) if source_id and row.get("source_id") == source_id and str(row.get("text") or "").strip()]
        text_pages = sum(bool(str(row.get("text") or "").strip()) for row in pages)
        previews = [{"page": page.get("page"), "image_path": page["image_path"]} for page in pages if page.get("image_path")]
        rendering = notes.get("rendering") if isinstance(notes.get("rendering"), dict) else {}
        preview_notes = next((item.get("warnings", []) for item in _records(rendering.get("sources")) if item.get("source_id") == source_id), [])
        timed = sum(row.get("start") is not None and row.get("end") is not None for row in speech)
        statuses = [row["alignment"].get("status") if isinstance(row.get("alignment"), dict) else None for row in speech]
        navigation = statuses.count("navigation")
        pending = sum(status not in {"aligned", "covered", "ready", "navigation"} for status in statuses)
        issue = any(row.get("source_id") == source_id for row in _records(notes.get("extraction_issues"))) if source_id else False
        row = {"stored_name": file["stored_name"], "name": file["name"], "size_bytes": file["size_bytes"],
               "page_count": len(pages), "text_page_count": text_pages, "segment_count": len(speech),
               "timed_segment_count": timed, "pending_segment_count": pending, "navigation_segment_count": navigation}
        row.update(rendered_page_count=len(previews), preview_pages=previews, preview_notes=preview_notes)
        if not data:
            status, label, detail, action = "pending", "尚未读取", "文件已保存在本机，尚无可用的读取结果。", "等待处理；若任务已中断，可用保存的材料重试。"
        elif issue:
            status, label, detail, action = "unreadable", "无法读取", "这份文件未进入课程讲解。", "取消勾选此文件，再添加可打开的副本；旧版课件请另存为 PPTX 或 PDF。"
        elif source.get("kind") in {"audio", "video"} and not speech:
            status, label, detail, action = "transcription-needed", "录音尚未转写", "本次只保存文件，没有读取其中的讲课内容。", "添加这段录音对应的教师转写（优先 SRT/VTT；也可用 DOCX/TXT）。"
        elif pages:
            status = "text-read" if text_pages == len(pages) else "partial" if text_pages else "no-text"
            label = "文字已读取" if status == "text-read" else "部分页面无文字" if text_pages else "未读到页面文字"
            detail = f"共 {len(pages)} 页，其中 {text_pages} 页提取到文字。图表和公式仍需核对。"
            action = "可补充教师转写以还原推理与课堂重点。" if status == "text-read" else "请添加含文字层的 PDF、可编辑课件或对应转写；扫描图像尚不能自动理解。"
        elif speech:
            status, label = "text-read", "转写已读取"
            detail = f"读取 {len(speech)} 段，其中 {timed} 段有起止时间，{pending} 段与页面的关系待确认。"
            action = "页面配对只是候选，不等于已核实教师观点。" if timed == len(speech) else "无时间戳的内容不能定位原录音；可用 SRT/VTT 替换以便回听核对。"
        else:
            status, label, detail, action = "no-text", "未读到文字", "文件已保存，但没有提取到可供学习的内容。", "请检查是否为空文件，或添加可提取文字的课件和教师转写。"
        if previews:
            detail += f" 已生成 {len(previews)} 页原页预览，可展开对照；预览不等于已理解图示。"
        row.update(status=status, label=label, detail=detail, action=action)
        results.append(row)
    return results
