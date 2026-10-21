from pathlib import Path
import zipfile
from xml.etree import ElementTree

import pytest

from mst.alignment import align_speech_to_visuals
from mst.extract import _pptx_diagram_graph, extract_docx_transcript, extract_pptx_pages, parse_timestamped_text
from mst.models import Alignment, SpeechSegment, VisualFrame
from mst.multimodal import classify_speech_text, extract_speech_increment, visual_signals


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
    assert result["domain_signals"]["domain"] == "computer-systems"
    assert "ALU" in result["domain_signals"]["datapath_stages"]
    assert result["domain_signals"]["instruction_tokens"]
    relation = next(item for item in result["formula_relations"] if item["raw"] == "2^10 = 1024")
    assert relation["kind"] == "equation_or_assignment"
    assert relation["operation"] == "等式/赋值关系"


def test_visual_signals_filter_prose_opcode_and_formula_false_positives() -> None:
    result = visual_signals("Von Neumann and EDVAC 101 pages\nStorage - M")
    assert result["code_candidates"] == []
    assert result["formula_relations"] == []
    assert not result["domain_signals"]


def test_visual_signals_keep_structured_riscv_candidates() -> None:
    result = visual_signals("addi r5, r0, 10\nmuli r5, r5, 2\nlw r6, 0(r5)")
    assert [row["opcode"] for row in result["code_candidates"]] == ["addi", "muli", "lw"]
    assert result["code_candidates"][0]["operands"] == ["r5", "r0", "10"]
    assert result["code_candidates"][0]["writes"] == "r5"
    assert result["code_candidates"][0]["effect"] == "r5 ← r0 + 10"
    assert result["code_candidates"][1]["isa_status"] == "lecture_specific"
    assert "不是标准 RISC-V" in result["code_candidates"][1]["caveat"]
    assert "立即数" in result["code_candidates"][0]["operation"]


def test_computer_systems_signal_exposes_ordered_datapath_trace() -> None:
    result = visual_signals("PC instruction memory register file ALU data memory write back next PC")
    assert result["domain_signals"]["datapath_trace"] == [
        "PC", "指令存储器", "寄存器堆", "ALU", "数据存储器", "写回", "下一条 PC"
    ]


def test_speech_roles_distinguish_definition_correction_and_assessment() -> None:
    result = classify_speech_text("定义是状态机。注意不要把状态和输出混淆，这个期末考试会考。")
    assert {"definition", "correction", "assessment"} <= set(result["roles"])
    assert result["assessment_signal"] == "explicit"


def test_speech_increment_keeps_teacher_additions_and_marks_new_anchors() -> None:
    result = extract_speech_increment(
        "页面给出了 PC 和 ALU。注意不要把 ALU 当成寄存器，因为它负责运算。这个期末考试会考。",
        page_text="PC 和 ALU",
        page_title="数据通路",
    )
    assert result["is_increment"] is True
    assert result["kind"] in {"correction", "assessment"}
    assert "不要把 ALU 当成寄存器" in result["text"]
    assert result["new_anchors"]
    assert result["sentence_count"] == 3
    assert result["sentences"][0]["retained"] is False


def test_docx_transcript_infers_end_from_next_timestamp(tmp_path: Path) -> None:
    source = tmp_path / "lecture.docx"
    document = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>00:01 先看 PC。</w:t></w:r></w:p>
      <w:p><w:r><w:t>00:05 再看 ALU。</w:t></w:r></w:p>
    </w:body></w:document>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document)
    rows = extract_docx_transcript(source)
    assert rows[0].start == 1
    assert rows[0].end == 5
    assert rows[0].text == "先看 PC。"
    assert rows[0].metadata["raw_transcript"].startswith("00:01")
    assert rows[1].start == 5
    assert rows[1].end is None


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
    assert aligned[0].metadata["alignment_analysis"]["candidates"][0]["visual_id"] == "p1"
    assert aligned[1].alignment is not None
    assert aligned[1].alignment.status == "navigation"


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
    assert page.metadata["visual_analysis"]["diagram_edges"] == ["PC — ALU"]
    assert page.visual_summary


def test_docx_groups_standalone_markers_and_preserves_resets(tmp_path: Path) -> None:
    source = tmp_path / "export.docx"
    paragraphs = ["课程名称", "授课老师：示例", "2026-06-10第7-8节", "00:00:01", "00:00:05",
                  "先读寄存器。", "再用 ALU 运算。", "00:00:12 接下来写回。", "00:00:02 新的录音开始。"]
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                         + "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs) + "</w:body></w:document>")
    rows = extract_docx_transcript(source)
    assert len(rows) == 5
    assert rows[0].kind == rows[1].kind == "administrative"
    assert rows[1].text == rows[1].transcript == ""  # No raw-timestamp resurrection.
    assert rows[2].text == "先读寄存器。\n再用 ALU 运算。"
    assert rows[2].start == 5 and rows[2].end == 12
    assert rows[2].metadata["end_inferred"] is True
    assert rows[2].metadata["paragraph_numbers"] == [5, 6, 7]
    assert rows[3].end is None  # Never jump over the reset to a later marker.
    assert rows[4].metadata["timeline_block"] == 1
    assert rows[4].end is None


def test_speech_increment_omits_repetition_logistics_and_filler() -> None:
    for text in ("寄存器保存当前状态。", "大家先休息两分钟。", "嗯，嗯，什么。"):
        result = extract_speech_increment(text, page_text="寄存器保存当前状态。")
        assert result["is_increment"] is False
        assert result["text"] == ""
    result = extract_speech_increment("寄存器保存当前状态。\n注意不要把组合运算结果当作已经写回的状态。", page_text="寄存器保存当前状态。")
    assert result["text"].startswith("注意不要")
    assert result["roles"] == ["correction"]
    assert classify_speech_text("the latest result")["assessment_signal"] == "none_observed"


def test_alignment_ignores_generated_cues_numbers_and_ties() -> None:
    pages = [VisualFrame(visual_id="p1", text="第 12 页 00:00:05", visual_summary="多周期控制器状态机"),
             VisualFrame(visual_id="p2", text="多周期控制器状态机"),
             VisualFrame(visual_id="p3", text="多周期控制器状态机")]
    rows = align_speech_to_visuals(iter(pages), iter([
        SpeechSegment(segment_id="s1", text="00:00:05 第12页"),
        SpeechSegment(segment_id="s2", text="多周期控制器状态机"),
    ]))
    assert len(rows) == 2
    assert rows[0].status == "pending" and not rows[0].alignment.visual_ids
    assert rows[1].status == "pending"
    assert set(rows[1].alignment.visual_ids) == {"p2", "p3"}


def test_alignment_supports_bilingual_source_anchors() -> None:
    pages = [VisualFrame(visual_id="p1", text="Datapath PC register file ALU"), VisualFrame(visual_id="p2", text="binary complement")]
    rows = align_speech_to_visuals(pages, [SpeechSegment(text="数据通路：程序计数器、寄存器堆和算术逻辑单元。")])
    assert rows[0].alignment.visual_ids == ["p1"]
    assert rows[0].status == "aligned"


def test_alignment_holds_weakly_supported_transcript_for_pairing_review() -> None:
    pages = [VisualFrame(visual_id="p1", text="Binary complement"), VisualFrame(visual_id="p2", text="CPU registers memory")]
    segments = [SpeechSegment(source_id="later-lecture", text="Binary complement")]
    segments += [SpeechSegment(source_id="later-lecture", text=f"多周期控制器使用状态机选择下一状态，当前状态编码为 {i}，寄存器写入由状态决定。") for i in range(9)]
    rows = align_speech_to_visuals(pages, segments)
    assert all(s.status == "pending" for s in rows)
    assert all(s.metadata["alignment_analysis"]["pairing_status"] == "needs_review" for s in rows)


def _diagram_xml(contents: str):
    return ElementTree.fromstring('<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>' + contents + '</p:spTree></p:cSld></p:sld>')


def _node(node_id: int, label: str, x: int, y: int) -> str:
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{node_id}"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="100" cy="100"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>{label}</a:t></a:r></a:p></p:txBody></p:sp>'


@pytest.mark.parametrize(("heads", "symbol"), [("", "—"), ('<a:headEnd type="triangle"/>', "←"), ('<a:tailEnd type="triangle"/>', "→"), ('<a:headEnd type="triangle"/><a:tailEnd type="triangle"/>', "↔")])
def test_connector_arrowheads_determine_direction(heads: str, symbol: str) -> None:
    connector = f'<p:cxnSp><a:stCxn id="1"/><a:endCxn id="2"/><p:spPr><a:ln>{heads}</a:ln></p:spPr></p:cxnSp>'
    _, edges = _pptx_diagram_graph(_diagram_xml(_node(1, "PC", 0, 0) + _node(2, "ALU", 200, 0) + connector))
    assert edges == [f"PC {symbol} ALU"]


def test_rotated_bidirectional_preset_and_distant_labels() -> None:
    arrow = '<p:sp><p:nvSpPr><p:cNvPr id="3"/></p:nvSpPr><p:spPr><a:xfrm rot="5400000"><a:off x="100" y="100"/><a:ext cx="100" cy="100"/></a:xfrm><a:prstGeom prst="leftRightArrow"/></p:spPr></p:sp>'
    _, edges = _pptx_diagram_graph(_diagram_xml(_node(1, "CPU", 100, 0) + _node(2, "Memory", 100, 200) + arrow))
    assert edges == ["CPU ↔ Memory"]
    _, edges = _pptx_diagram_graph(_diagram_xml(_node(1, "CPU", 100, -1000) + _node(2, "Memory", 100, 2000) + arrow))
    assert edges == []


def test_nested_group_coordinate_transform_keeps_connector_local() -> None:
    group = '<p:grpSp><p:grpSpPr><a:xfrm><a:off x="1000" y="2000"/><a:ext cx="600" cy="200"/><a:chOff x="0" y="0"/><a:chExt cx="300" cy="100"/></a:xfrm></p:grpSpPr>'
    line = '<p:cxnSp><p:spPr><a:xfrm><a:off x="100" y="50"/><a:ext cx="100" cy="0"/></a:xfrm><a:ln><a:tailEnd type="triangle"/></a:ln></p:spPr></p:cxnSp>'
    _, edges = _pptx_diagram_graph(_diagram_xml(group + _node(1, "PC", 0, 0) + _node(2, "ALU", 200, 0) + line + '</p:grpSp>'))
    assert edges == ["PC → ALU"]


def test_flipped_arrow_reverses_geometry_without_inventing_arrowheads() -> None:
    arrow = '<p:sp><p:nvSpPr><p:cNvPr id="3"/></p:nvSpPr><p:spPr><a:xfrm flipH="1"><a:off x="100" y="0"/><a:ext cx="100" cy="100"/></a:xfrm><a:prstGeom prst="rightArrow"/></p:spPr></p:sp>'
    _, edges = _pptx_diagram_graph(_diagram_xml(_node(1, "PC", 0, 0) + _node(2, "ALU", 200, 0) + arrow))
    assert edges == ["ALU → PC"]


def test_admin_sentence_does_not_hide_the_following_explanation() -> None:
    segment = SpeechSegment(text="大家先休息两分钟。注意不要把内存地址与这个位置的数据混淆。")
    row = align_speech_to_visuals([], [segment])[0]
    assert row.status == "pending"
    increment = row.metadata["speech_increment"]
    assert "注意不要" in increment["text"]
    assert "休息" not in increment["text"]


def test_alignment_preserves_reviewed_mapping() -> None:
    segment = SpeechSegment(text="这段意译已经由人工核对。", status="verified", alignment=Alignment(visual_ids=["p1"], confidence="high", status="aligned"))
    row = align_speech_to_visuals([VisualFrame(visual_id="p1", text="Datapath")], [segment])[0]
    assert row.status == "verified"
    assert row.alignment.visual_ids == ["p1"]
    assert row.metadata["alignment_analysis"]["pairing_status"] == "reviewed"


def test_pptx_text_keeps_formatted_exponents_and_paragraphs(tmp_path: Path) -> None:
    source = tmp_path / "formula.pptx"
    slide = _diagram_xml('<p:sp><p:txBody><a:p><a:r><a:t>Powers</a:t></a:r></a:p><a:p><a:r><a:t>2</a:t></a:r><a:r><a:rPr baseline="30000"/><a:t>10</a:t></a:r><a:r><a:t> = 1024</a:t></a:r></a:p><a:p><a:r><a:t>x</a:t></a:r><a:r><a:rPr baseline="-25000"/><a:t>1</a:t></a:r></a:p></p:txBody></p:sp>')
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", ElementTree.tostring(slide))
    page = extract_pptx_pages(source)[0]
    assert page.text == "Powers\n2^{10} = 1024\nx_{1}"
    assert page.title == "Powers"
    assert any(row["raw"] == "2^{10} = 1024" for row in page.metadata["visual_analysis"]["formula_relations"])
    assert visual_signals("(0)H = 0000")["formula_relations"][0]["lhs"] == "(0)H"


def test_code_parser_requires_adjacent_operands_and_explains_memory_actions() -> None:
    assert not visual_signals("add\nx1 x2 x3")["code_candidates"]
    assert not visual_signals("add is a word, x1 x2 x3")["code_candidates"]
    assert not visual_signals("addi x1, x0, 3.5")["code_candidates"]
    rows = visual_signals("sw x5, 8(x6)\nlw x0, 8(x6)\nbeq x1, x2, loop")["code_candidates"]
    assert rows[0]["writes"] == "内存[x6 + 8]"
    assert "数据寄存器 x5" in rows[0]["reads"]
    assert "被丢弃" in rows[1]["writes"]
    assert rows[2]["writes"] == "PC"
    assert "条件成立" in rows[2]["pc_effect"]
