from pathlib import Path
import zipfile

from mst.alignment import align_speech_to_visuals
from mst.extract import extract_pptx_pages, parse_timestamped_text
from mst.models import SpeechSegment, VisualFrame
from mst.multimodal import classify_speech_text, visual_signals


def test_parse_vtt_cues(tmp_path: Path) -> None:
    source = tmp_path / "lecture.vtt"
    source.write_text(
        "WEBVTT\n\n00:00:02.500 --> 00:00:05.000\n先看证据。\n\n"
        "00:00:06.000 --> 00:00:08.000\n再看机制。\n",
        encoding="utf-8",
    )
    rows = parse_timestamped_text(source)
    assert len(rows) == 2
    assert rows[0].start == 2.5
    assert rows[0].end == 5.0
    assert rows[1].text == "再看机制。"
    assert rows[0].metadata["speech_analysis"]["primary_role"] == "general"


def test_plain_text_is_kept_as_untimed_speech(tmp_path: Path) -> None:
    source = tmp_path / "lecture.txt"
    source.write_text("普通转写没有可靠的时间戳。", encoding="utf-8")
    from mst.extract import extract_source

    _, rows = extract_source(source, "transcript")
    assert len(rows) == 1
    assert rows[0].start is None
    assert rows[0].text.startswith("普通转写")


def test_visual_signals_keep_code_formula_and_diagram_cues() -> None:
    result = visual_signals("PC -> ALU\naddi x5, x0, 10\ny = x + 1\n2^10 = 1024")
    assert result["kind"] == "mixed"
    assert result["code_lines"]
    assert result["formula_candidates"]
    assert result["arrow_count"] == 1


def test_speech_roles_distinguish_definition_correction_and_assessment() -> None:
    result = classify_speech_text("定义是状态机。注意不要把状态和输出混淆，这个期末考试会考。")
    assert {"definition", "correction", "assessment"} <= set(result["roles"])
    assert result["assessment_signal"] == "explicit"


def test_semantic_alignment_prefers_matching_page_and_keeps_supplement() -> None:
    pages = [
        VisualFrame(visual_id="p1", title="数据通路", text="PC -> ALU -> 寄存器写回"),
        VisualFrame(visual_id="p2", title="进制转换", text="2^10 = 1024"),
    ]
    segments = [
        SpeechSegment(segment_id="s1", text="数据通路中 PC 经过 ALU 后写回寄存器"),
        SpeechSegment(segment_id="s2", text="大家先休息两分钟"),
    ]
    aligned = align_speech_to_visuals(pages, segments)
    assert aligned[0].alignment is not None
    assert aligned[0].alignment.visual_ids == ["p1"]
    assert aligned[0].alignment.status == "aligned"
    assert aligned[1].alignment is not None
    assert aligned[1].alignment.status == "supplement"


def test_pptx_extraction_records_shape_and_visual_signals(tmp_path: Path) -> None:
    source = tmp_path / "lesson.pptx"
    slide = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree>
        <p:sp><p:nvSpPr><p:cNvPr id="1" name="PC"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="100" cy="100"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>PC</a:t></a:r></a:p></p:txBody></p:sp>
        <p:sp><p:nvSpPr><p:cNvPr id="2" name="ALU"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="200" y="0"/><a:ext cx="100" cy="100"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>ALU</a:t></a:r></a:p></p:txBody></p:sp>
        <p:cxnSp><p:nvCxnSpPr><p:cNvPr id="3" name="PC to ALU"/></p:nvCxnSpPr><p:spPr><a:xfrm><a:off x="100" y="40"/><a:ext cx="100" cy="20"/></a:xfrm><a:prstGeom prst="line"/></p:spPr><a:stCxn id="1" idx="0"/><a:endCxn id="2" idx="0"/></p:cxnSp>
      </p:spTree></p:cSld>
    </p:sld>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
    page = extract_pptx_pages(source)[0]
    assert page.visual_kind in {"diagram", "mixed"}
    assert page.metadata["visual_analysis"]["arrow_count"] >= 1
    assert page.metadata["visual_analysis"]["diagram_edges"] == ["PC → ALU"]
    assert page.visual_summary
