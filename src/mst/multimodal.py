"""Deterministic multimodal signals used before model enrichment.

The first version of the tutor treated extracted text as if it were the whole
slide.  This module keeps the boundary honest: it does not claim to understand
an image, but records useful, inspectable signals about code, formulas,
connectors, tables and speech functions.  A model or human can then review the
small set of pages and segments that need visual or semantic attention.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.$:+\-/]*|\d+(?:\.\d+)?")
_HAN_RE = re.compile(r"[\u3400-\u9fff]+")
_FORMULA_ATOM = r"(?:\([0-9A-Fa-f.]+\)[HhBbOoDd]|[A-Za-z](?:[_0-9]{0,3})?|\{[-+]?\d+(?:\.\d+)?\}|-?\d+(?:\.\d+)?)"
_FORMULA_EXPR = rf"{_FORMULA_ATOM}(?:\s*[+\-*/^×÷]\s*{_FORMULA_ATOM})*"
_FORMULA_RE = re.compile(
    rf"(?:\\(?:frac|sum|prod|int|sqrt|cdot|times|pm)|"
    rf"(?<![A-Za-z0-9_]){_FORMULA_EXPR}\s*(?:=|:=|≤|≥|≠|<|>)\s*{_FORMULA_EXPR}(?![A-Za-z0-9_])|"
    rf"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?(?:\s*[+\-*/^×÷]\s*{_FORMULA_ATOM})+(?![A-Za-z0-9_])|"
    r"[∑∏∫√±≤≥≠∞→←])"
)
_CODE_RE = re.compile(
    r"(?:\b(?:int|float|double|char|return|if|else|for|while|always_ff|assign|module)\b|"
    r"\b[A-Za-z_][A-Za-z0-9_]*\s*(?:\+=|-=|\*=|/=|=)\s*[^=])"
)
_ARROW_RE = re.compile(r"(?:->|=>|→|⇒|↦|←|⇐|⟶|⟵)")
_TABLE_RE = re.compile(r"\|[^\n|]+\||(?:\t[^\n\t]+){2,}")
_RISCV_OPCODE_RE = re.compile(
    r"\b(?:addi|add|sub|mul|muli|div|lw|sw|ld|sd|beq|bne|jal|jalr|and|or|xor|slli|srli|lui|auipc)\b",
    re.IGNORECASE,
)
_RISCV_OPERAND_RE = re.compile(
    r"-?(?:0x[0-9a-f]+|0b[01]+|\d+)(?:\([A-Za-z][A-Za-z0-9_.$]*\))?"
    r"|[A-Za-z_.$][A-Za-z0-9_.$]*",
    re.IGNORECASE,
)
_RISCV_OPERAND_COUNTS = {
    "addi": 3,
    "add": 3,
    "sub": 3,
    "mul": 3,
    "muli": 3,
    "div": 3,
    "and": 3,
    "or": 3,
    "xor": 3,
    "slli": 3,
    "srli": 3,
    "lw": 2,
    "sw": 2,
    "ld": 2,
    "sd": 2,
    "beq": 3,
    "bne": 3,
    "jal": 2,
    "jalr": 2,
    "lui": 2,
    "auipc": 2,
}
_RISCV_REGISTER_RE = re.compile(
    r"(?:x(?:0|[1-9]|[12]\d|3[01])|r(?:0|[1-9]|[12]\d|3[01])|"
    r"zero|ra|sp|gp|tp|fp|a[0-7]|t[0-6]|s(?:[0-9]|1[01]))$",
    re.IGNORECASE,
)
_RISCV_SEMANTICS = {
    "addi": ("寄存器 + 立即数", "rd", "rs1/立即数"),
    "muli": ("寄存器 × 立即数", "rd", "rs1/立即数"),
    "add": ("两个寄存器相加", "rd", "rs1、rs2"),
    "sub": ("两个寄存器相减", "rd", "rs1、rs2"),
    "mul": ("两个寄存器相乘", "rd", "rs1、rs2"),
    "div": ("两个寄存器相除", "rd", "rs1、rs2"),
    "and": ("按位与", "rd", "rs1、rs2"),
    "or": ("按位或", "rd", "rs1、rs2"),
    "xor": ("按位异或", "rd", "rs1、rs2"),
    "slli": ("左移立即数位数", "rd", "rs1/立即数"),
    "srli": ("右移立即数位数", "rd", "rs1/立即数"),
    "lw": ("从内存读一个字", "rd", "地址寄存器/偏移量"),
    "ld": ("从内存读一个双字", "rd", "地址寄存器/偏移量"),
    "sw": ("把寄存器值写入内存", "内存", "rs2/地址寄存器/偏移量"),
    "sd": ("把寄存器值写入内存", "内存", "rs2/地址寄存器/偏移量"),
    "beq": ("相等则改变 PC", "PC", "rs1、rs2/目标"),
    "bne": ("不等则改变 PC", "PC", "rs1、rs2/目标"),
    "jal": ("保存返回地址并跳转", "rd、PC", "目标"),
    "jalr": ("按寄存器地址跳转", "rd、PC", "rs1/偏移量"),
    "lui": ("装入高位立即数", "rd", "立即数"),
    "auipc": ("PC 加高位立即数", "rd", "PC/立即数"),
}
_BINARY_RE = re.compile(r"\b(?:[01]{8,}(?:\.[01]+)?(?:₂|_2|b)?|[01]{3,}(?:₂|_2|b))\b")
_HEX_RE = re.compile(r"\b(?:0x[0-9A-Fa-f]+|(?=[0-9A-Fa-f]*[A-Fa-f])[0-9A-Fa-f]{2,}(?:\.[0-9A-Fa-f]+)?(?:₁₆|_16|h)?)\b")

_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "into", "then", "when",
    "what", "which", "where", "有", "是", "的", "了", "和", "在", "把", "将",
    "然后", "可以", "一个", "这个", "进行", "通过", "因为", "所以", "我们",
}

_ROLE_RULES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("assessment", ("必考", "考试", "期末", "考点", "作业要求", "评分", "得分", "会考", "test", "exam", "graded"), 5),
    ("correction", ("不是", "不要", "别把", "容易错", "常见错误", "纠正", "误解", "注意不要", "wrong", "mistake"), 4),
    ("definition", ("定义", "称为", "叫做", "是指", "指的是", "也就是", "means", "defined as", "refers to"), 3),
    ("derivation", ("因为", "所以", "因此", "推导", "推出", "于是", "because", "therefore", "derive"), 2),
    ("example", ("例如", "比如", "假设", "举例", "例子", "我们看", "for example", "suppose", "consider"), 2),
    ("emphasis", ("重点", "关键", "注意", "重要", "记住", "核心", "特别", "important", "key"), 2),
    ("question", ("为什么", "如何", "怎么", "想一想", "问题是", "why", "how", "question"), 1),
)

_ROLE_LABELS = {
    "assessment": "评价提示",
    "correction": "纠错提醒",
    "definition": "定义说明",
    "derivation": "推导说明",
    "example": "例题或案例",
    "emphasis": "课堂强调",
    "question": "课堂提问",
    "general": "课堂讲解",
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def is_administrative_speech(text: str) -> bool:
    """Recognize logistics/filler without treating it as a teaching addition."""
    compact = re.sub(r"[\s，,。.!！？?、；;]", "", str(text or ""))
    return not compact or bool(
        re.fullmatch(r"(?:嗯|啊|呃|哦|哎|对|好|什么|是的)+", compact)
        or re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", compact)
        or re.fullmatch(r"(?:大家|同学们)?(?:先|可以)?休息(?:一会|两分钟|一下)(?:吧|好)?|(?:好)?下课了|(?:先|开始)?签到|授课老师[：:].*", compact)
    )


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def tokenize(value: str) -> set[str]:
    """Return conservative lexical anchors for cross-language matching."""

    text = str(value or "").lower()
    tokens = {item for item in _ASCII_TOKEN_RE.findall(text) if item not in _STOPWORDS}
    for span in _HAN_RE.findall(text):
        if len(span) <= 4:
            tokens.add(span)
        tokens.update(span[index : index + 2] for index in range(len(span) - 1))
    return {item for item in tokens if len(item) > 1 and item not in _STOPWORDS}


def _context(text: str, match: re.Match[str], radius: int = 42) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return " ".join(text[start:end].split())


def classify_speech_text(text: str) -> dict[str, Any]:
    """Classify the classroom function of a transcript segment.

    The result is a signal, not a teacher claim.  Explicit assessment words
    are retained as evidence for later review; absence of such words never
    implies that a topic will not be assessed.
    """

    source = " ".join(str(text or "").split())
    lower = source.lower()
    scores: Counter[str] = Counter()
    spans: dict[str, list[str]] = {}
    for role, phrases, weight in _ROLE_RULES:
        for phrase in phrases:
            pattern = re.escape(phrase)
            if phrase.isascii():
                pattern = rf"\b{pattern}\b"
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                scores[role] += weight
                spans.setdefault(role, []).append(_context(source, match))
    ranked = [role for role, score in scores.most_common() if score > 0]
    if not ranked:
        primary = "general"
        confidence = "unresolved"
    else:
        primary = ranked[0]
        top = scores[primary]
        confidence = "high" if top >= 5 or len(ranked) >= 3 else "medium" if top >= 2 else "low"
    return {
        "primary_role": primary,
        "roles": ranked,
        "confidence": confidence,
        "evidence_spans": _unique(span for role in ranked for span in spans.get(role, []))[:4],
        "assessment_signal": "explicit" if "assessment" in scores else "none_observed",
    }


def speech_role_label(role: str) -> str:
    return _ROLE_LABELS.get(role, _ROLE_LABELS["general"])


def extract_speech_increment(
    text: str,
    *,
    page_text: str = "",
    page_title: str = "",
) -> dict[str, Any]:
    """Keep the part of a spoken segment that adds learning value.

    A transcript is not automatically an explanation.  This helper compares
    each sentence with the visible page and retains sentences that either
    carry a classroom role (definition, derivation, example, correction,
    emphasis, assessment or question) or introduce anchors absent from the
    page.  It is a conservative signal for the guide layer; it does not
    rewrite or attribute the teacher's words.
    """

    source = str(text or "").strip()
    analysis = classify_speech_text(source)
    page_tokens = tokenize(" ".join(item for item in (page_title, page_text) if item))
    sentences = [" ".join(item.split()) for item in _SENTENCE_SPLIT_RE.split(source) if item.strip()]
    if not sentences and source:
        sentences = [source]
    retained: list[str] = []
    new_anchors: list[str] = []
    sentence_rows: list[dict[str, Any]] = []
    role = str(analysis.get("primary_role") or "general")
    for sentence in sentences:
        tokens = tokenize(sentence)
        novel = sorted(tokens - page_tokens)
        sentence_analysis = classify_speech_text(sentence)
        sentence_role = str(sentence_analysis.get("primary_role") or "general")
        repeated = bool(page_tokens) and (
            re.sub(r"\s+", "", sentence).strip("。.!！?？；;") in re.sub(r"\s+", "", page_title + page_text)
            or (len(tokens) >= 3 and len(tokens & page_tokens) / len(tokens) >= 0.9)
        )
        substantive = (len(tokens) >= 3 and len(sentence) >= 12) or (
            sentence_role == "assessment" and len(tokens) >= 2 and len(sentence) >= 6
        )
        role_is_increment = sentence_role != "general"
        keep = substantive and not repeated and not is_administrative_speech(sentence) and (
            (role_is_increment and (not page_tokens or bool(novel)))
            or (len(novel) >= 3 and len(sentence) >= 20)
        )
        if keep:
            retained.append(sentence)
            new_anchors.extend(novel[:12])
        sentence_rows.append(
            {
                "text": sentence,
                "role": sentence_role,
                "label": speech_role_label(sentence_role),
                "confidence": sentence_analysis.get("confidence", "unresolved"),
                "new_anchors": novel[:12],
                "retained": keep,
                "omission_reason": "" if keep else "页面复述" if repeated else "未观察到足够的教学增量",
            }
        )
    retained_rows = [row for row in sentence_rows if row["retained"]]
    increment_roles = _unique(str(row["role"]) for row in retained_rows)
    return {
        "kind": role,
        "label": speech_role_label(role),
        "text": " ".join(retained),
        "new_anchors": _unique(new_anchors)[:24],
        "roles": increment_roles,
        "is_increment": bool(retained),
        "sentence_count": len(sentences),
        "sentences": sentence_rows,
        "assessment_signal": analysis.get("assessment_signal", "none_observed"),
    }


def _computer_systems_signals(text: str) -> dict[str, Any] | None:
    """Extract domain-specific inspection cues without solving the page."""

    compact = " ".join(str(text or "").split())
    lower = compact.lower()

    def contains_term(term: str) -> bool:
        if any("\u3400" <= char <= "\u9fff" for char in term):
            return term in lower
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", lower))

    instruction_tokens = _unique(row["raw"] for row in _code_candidates(text))
    datapath_labels = [
        ("PC", ("pc", "程序计数器")),
        ("指令存储器", ("instruction memory", "指令存储器", "imem")),
        ("寄存器堆", ("register file", "寄存器堆", "regfile")),
        ("立即数生成", ("immgen", "immediate", "立即数")),
        ("ALU", ("alu",)),
        ("数据存储器", ("data memory", "数据存储器", "dmem")),
        ("写回", ("write back", "writeback", "写回")),
        ("下一条 PC", ("next pc", "nextpc", "下一条 pc")),
    ]
    stages = [label for label, aliases in datapath_labels if any(contains_term(alias) for alias in aliases)]
    field_names = _unique(
        field
        for field in ("opcode", "funct3", "funct7", "rd", "rs1", "rs2", "immediate", "imm", "立即数", "操作码")
        if contains_term(field)
    )
    timing = _unique(
        term
        for term in ("fetch", "decode", "execute", "memory", "write back", "clock", "cycle", "取指", "译码", "执行", "访存", "时钟")
        if contains_term(term)
    )
    binary = _unique(match.group(0) for match in _BINARY_RE.finditer(compact))
    hexadecimal = _unique(match.group(0) for match in _HEX_RE.finditer(compact) if not re.fullmatch(r"[A-Za-z]{2,}", match.group(0)))
    is_cs = bool(instruction_tokens or len(stages) >= 2 or field_names or binary or hexadecimal or contains_term("risc-v") or contains_term("datapath"))
    if not is_cs:
        return None
    if instruction_tokens:
        trace = "读寄存器/立即数 → 执行运算或访存 → 写回目标 → 检查下一条 PC"
    elif len(stages) >= 2:
        trace = "从 PC/输入开始 → 沿数据通路经过部件 → 在控制信号选择的位置写回"
    elif field_names:
        trace = "先按字段切分指令 → 解释每个字段 → 检查寄存器、立即数和控制动作"
    else:
        trace = "先确定位宽和表示规则 → 展开每一位/每一阶段 → 检查范围、进位或时序"
    datapath_trace = []
    if len(stages) >= 2:
        canonical = ["PC", "指令存储器", "寄存器堆", "立即数生成", "ALU", "数据存储器", "写回", "下一条 PC"]
        datapath_trace = [item for item in canonical if item in stages]
    return {
        "domain": "computer-systems",
        "instruction_tokens": instruction_tokens[:20],
        "datapath_stages": stages,
        "instruction_fields": field_names,
        "timing_terms": timing,
        "binary_literals": binary[:20],
        "hex_literals": hexadecimal[:20],
        "recommended_trace": trace,
        "datapath_trace": datapath_trace,
        "needs_domain_review": bool(instruction_tokens or field_names or len(stages) >= 2),
    }


def _code_candidates(source: str) -> list[dict[str, Any]]:
    """Extract only instruction-shaped candidates with plausible operands.

    Opcode names such as ``and`` and ``or`` are ordinary words in lecture
    prose.  A raw regex match is therefore not enough: require the expected
    operand count and register/immediate shapes before exposing a candidate to
    the learner-facing draft.
    """

    def is_register(value: str) -> bool:
        return bool(_RISCV_REGISTER_RE.fullmatch(value.strip()))

    def is_immediate(value: str) -> bool:
        return bool(re.fullmatch(r"-?(?:0x[0-9a-f]+|0b[01]+|\d+)", value.strip(), re.IGNORECASE))

    def is_memory(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"-?(?:0x[0-9a-f]+|\d+)\((?:x(?:0|[1-9]|[12]\d|3[01])|"
                r"r(?:0|[1-9]|[12]\d|3[01])|zero|ra|sp|gp|tp|fp|a[0-7]|"
                r"t[0-6]|s(?:[0-9]|1[01]))\)",
                value.strip(),
                re.IGNORECASE,
            )
        )

    def valid_operands(opcode: str, operands: list[str]) -> bool:
        expected = _RISCV_OPERAND_COUNTS.get(opcode.lower())
        if expected is None or len(operands) != expected:
            return False
        opcode = opcode.lower()
        if opcode in {"lw", "sw", "ld", "sd", "jalr"}:
            return is_register(operands[0]) and is_memory(operands[1])
        if opcode in {"beq", "bne"}:
            return is_register(operands[0]) and is_register(operands[1]) and bool(
                re.fullmatch(r"[A-Za-z_.$][A-Za-z0-9_.$]*|-?(?:0x[0-9a-f]+|0b[01]+|\d+)", operands[2], re.IGNORECASE)
            )
        if opcode in {"jal"}:
            return is_register(operands[0]) and bool(re.fullmatch(r"[A-Za-z_.$][A-Za-z0-9_.$]*|-?(?:0x[0-9a-f]+|0b[01]+|\d+)", operands[1], re.IGNORECASE))
        if opcode in {"lui", "auipc"}:
            return is_register(operands[0]) and is_immediate(operands[1])
        if opcode in {"addi", "muli", "slli", "srli"}:
            return is_register(operands[0]) and is_register(operands[1]) and is_immediate(operands[2])
        return all(is_register(operand) for operand in operands)

    rows: list[dict[str, Any]] = []
    for match in _RISCV_OPCODE_RE.finditer(source):
        opcode = match.group(0)
        expected = _RISCV_OPERAND_COUNTS[opcode.lower()]
        remainder = source[match.end():].split("\n", 1)[0]
        if not re.match(r"[ \t]+", remainder):
            continue
        cursor = len(remainder) - len(remainder.lstrip(" \t"))
        operands = []
        for index in range(expected):
            operand = _RISCV_OPERAND_RE.match(remainder, cursor)
            if not operand:
                break
            operands.append(operand.group(0))
            cursor = operand.end()
            if index < expected - 1:
                separator = re.match(r"(?:[ \t]*,[ \t]*|[ \t]+)", remainder[cursor:])
                if not separator:
                    break
                cursor += separator.end()
        if not valid_operands(opcode, operands):
            continue
        if cursor < len(remainder) and remainder[cursor] not in " \t;#。；，":
            continue  # Do not silently truncate a malformed register/immediate.
        operation, writes, reads = _RISCV_SEMANTICS.get(opcode.lower(), ("指令操作", "待确认", "待确认"))
        semantics = _instruction_effect(opcode.lower(), operands)
        raw = f"{opcode} " + ", ".join(operands)
        rows.append(
            {
                "raw": raw,
                "opcode": opcode,
                "operands": operands,
                "operation": operation,
                "writes": semantics.get("writes", writes),
                "reads": semantics.get("reads", reads),
                **semantics,
            }
        )
    return rows[:24]


def _instruction_effect(opcode: str, operands: list[str]) -> dict[str, Any]:
    """Explain concrete operands without pretending to know runtime values."""
    dest = operands[0]
    result: dict[str, Any] = {"isa_status": "lecture_specific" if opcode == "muli" else "standard_mnemonic",
                              "pc_effect": "若为 32 位指令且正常完成，下一条 PC = 当前 PC + 4。"}
    immediate_ops = {"addi": "+", "muli": "×", "slli": "<<", "srli": ">>（逻辑右移）"}
    register_ops = {"add": "+", "sub": "−", "mul": "×（取低 XLEN 位）", "div": "÷（有符号整数除法）", "and": "按位与", "or": "按位或", "xor": "按位异或"}
    if opcode in immediate_ops or opcode in register_ops:
        left, right = operands[1:]
        operator = immediate_ops.get(opcode) or register_ops[opcode]
        result.update(reads=f"{left}，{'立即数 ' if opcode in immediate_ops else ''}{right}", writes=dest,
                      effect=f"{dest} ← {left} {operator} {right}", caveat="结果按目标寄存器的 XLEN 位宽处理；不能据此假定寄存器初值。")
    elif opcode in {"lw", "ld", "sw", "sd", "jalr"}:
        offset, base = operands[1].split("(", 1)
        base = base.rstrip(")")
        address = f"{base} + {offset}"
        if opcode == "jalr":
            result.update(reads=f"{base}，立即数 {offset}", writes=f"{dest}、PC", effect=f"{dest} ← 旧 PC + 4；PC ← ({address}) & ~1", pc_effect="先用旧寄存器值计算目标地址，再写返回地址；目标地址的最低位清零。")
        else:
            load = opcode in {"lw", "ld"}
            width = 32 if opcode in {"lw", "sw"} else 64
            result.update(reads=f"地址寄存器 {base}，偏移 {offset}" + ("，相应内存内容" if load else f"，数据寄存器 {dest}"),
                          writes=dest if load else f"内存[{address}]",
                          effect=f"{dest} ← 内存[{address}] 的 {width} 位数据" if load else f"内存[{address}] ← {dest} 的低 {width} 位",
                          caveat="lw 在 RV64 中将 32 位数据符号扩展到 XLEN；ld/sd 需要 RV64。地址、数据和字节偏移不能混为一谈。")
    elif opcode in {"beq", "bne"}:
        relation = "=" if opcode == "beq" else "≠"
        result.update(reads=f"{dest}、{operands[1]}", writes="PC", effect=f"比较 {dest} {relation} {operands[1]}，成立则跳到 {operands[2]}", pc_effect="条件成立：PC ← 旧 PC + 分支偏移；否则，32 位指令 PC ← 旧 PC + 4。标签偏移需汇编器解析。")
    elif opcode == "jal":
        result.update(reads="旧 PC 与跳转目标", writes=f"{dest}、PC", effect=f"{dest} ← 旧 PC + 4；跳转至 {operands[1]}", pc_effect="PC ← 旧 PC + 跳转偏移；标签位置需要汇编器解析。")
    elif opcode in {"lui", "auipc"}:
        result.update(reads=("旧 PC，" if opcode == "auipc" else "") + f"立即数 {operands[1]}", writes=dest,
                      effect=f"{dest} ← " + ("旧 PC + " if opcode == "auipc" else "") + f"({operands[1]} << 12)",
                      caveat="按 U 型立即数字段解释；RV64 中还要按规范处理符号扩展。")
    if dest.lower() in {"x0", "zero", "r0"} and opcode not in {"sw", "sd", "beq", "bne"}:
        result["writes"] = str(result["writes"]) + "（零寄存器的写入会被丢弃）"
    if opcode == "muli":
        result["caveat"] = "muli 不是标准 RISC-V 指令；这里只按课件的“乘立即数”记法解释。实际汇编通常先装入常数，再使用 mul（需要 M 扩展）。"
    return result


def _formula_candidates(source: str) -> list[dict[str, Any]]:
    def descriptor(raw: str, lhs: str | None, operator: str | None, rhs: str | None) -> dict[str, Any]:
        if operator in {"=", ":="}:
            kind = "equation_or_assignment"
            operation = "等式/赋值关系"
        elif operator:
            kind = "inequality"
            operation = "条件比较"
        elif raw in {"0/1", "0 / 1"}:
            kind = "binary_symbols"
            operation = "二进制逻辑值"
        elif any(symbol in raw for symbol in ("/", "÷")):
            kind = "division"
            operation = "除法或比例"
        elif any(symbol in raw for symbol in ("^",)):
            kind = "power"
            operation = "幂运算"
        elif any(symbol in raw for symbol in ("*", "×")):
            kind = "product"
            operation = "乘法/位权项"
        elif any(symbol in raw for symbol in ("+", "-")):
            kind = "sum_or_difference"
            operation = "加减运算"
        else:
            kind = "symbol"
            operation = "符号或算子"
        base_hint = None
        if re.search(r"(?:₂|_2|\)\s*2\b|base\s*2\b|N\s*2\b)", raw, re.IGNORECASE):
            base_hint = "二进制候选"
        elif re.search(r"(?:₁₆|_16|\)\s*16\b|base\s*16\b|hex)", raw, re.IGNORECASE):
            base_hint = "十六进制候选"
        elif re.search(r"(?:\)\s*10\b|base\s*10\b|decimal)", raw, re.IGNORECASE):
            base_hint = "十进制候选"
        return {
            "kind": kind,
            "operation": operation,
            "lhs": lhs,
            "operator": operator,
            "rhs": rhs,
            "base_hint": base_hint,
            "needs_symbol_review": True,
        }

    rows: list[dict[str, Any]] = []
    for match in _FORMULA_RE.finditer(source):
        raw = " ".join(match.group(0).split())
        relation = re.search(r"(=|:=|≤|≥|≠|<|>)", raw)
        if relation:
            lhs = raw[: relation.start()].strip()
            operator = relation.group(1)
            rhs = raw[relation.end() :].strip()
        else:
            lhs, operator, rhs = raw, None, None
        rows.append({"raw": raw, **descriptor(raw, lhs, operator, rhs)})
    return rows[:20]


def visual_signals(
    text: str,
    *,
    shape_counts: Mapping[str, int] | None = None,
    image_count: int = 0,
    connector_count: int = 0,
    diagram_nodes: Sequence[str] | None = None,
    diagram_edges: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Describe observable visual/text structure without claiming OCR or vision."""

    source = "\n".join(str(text or "").splitlines()).strip()
    code_candidates = _code_candidates(source)
    code_lines = _unique(line.strip() for line in source.splitlines() if _CODE_RE.search(line))
    code_lines = _unique([*code_lines, *(row["raw"] for row in code_candidates)])
    if not code_lines:
        # PPT XML often flattens line breaks into spaces; retain short code-like
        # fragments so a later model can inspect them as one block.
        code_lines = _unique(match.group(0) for match in _CODE_RE.finditer(source))
    formula_candidates = _unique(match.group(0) for match in _FORMULA_RE.finditer(source))
    formula_relations = _formula_candidates(source)
    arrows = len(_ARROW_RE.findall(source)) + int(connector_count)
    table_hits = len(_TABLE_RE.findall(source))
    domain_signals = _computer_systems_signals(source)
    lower = source.lower()
    diagram_keywords = _unique(
        keyword
        for keyword in (
            "pc", "alu", "register", "寄存器", "memory", "内存", "mux", "数据通路", "datapath",
            "clock", "时钟", "state", "状态", "fsm", "控制信号", "control", "input", "output",
        )
        if keyword in lower
    )
    counts = {str(key): int(value) for key, value in (shape_counts or {}).items()}
    nodes = _unique(diagram_nodes or [])
    edges = _unique(diagram_edges or [])
    if image_count or counts.get("picture", 0):
        image_count = max(image_count, counts.get("picture", 0))

    cues = []
    if code_lines:
        cues.append("代码/指令")
    if formula_candidates:
        cues.append("公式/符号")
    if arrows or diagram_keywords:
        cues.append("流程/连接")
    if table_hits:
        cues.append("表格")
    if not cues and source:
        cues.append("正文")
    if len(cues) > 1:
        kind = "mixed"
    elif code_lines:
        kind = "code"
    elif formula_candidates:
        kind = "formula"
    elif arrows or diagram_keywords:
        kind = "diagram"
    elif table_hits:
        kind = "table"
    elif source:
        kind = "text"
    elif image_count:
        kind = "image"
    else:
        kind = "unknown"

    if not source and image_count:
        summary = "页面主要是图像；文字提取不足，需要人工或视觉模型复核。"
    elif not source:
        summary = "没有提取到页面文字；可能是扫描页或图形页，需要人工或视觉模型复核。"
    elif kind in {"diagram", "mixed"} and (arrows or diagram_keywords):
        edge_hint = f"发现 {len(edges)} 条节点连接候选" if edges else "检测到流程/连接线索"
        summary = f"{edge_hint}；学习时沿箭头确认起点、经过的部件和终点。"
    elif kind in {"code", "mixed"} and code_lines:
        summary = "检测到代码或指令片段；学习时按行追踪输入、状态变化和写回位置。"
    elif kind in {"formula", "mixed"} and formula_candidates:
        summary = "检测到公式或符号关系；学习时核对变量、运算符、左右两侧和适用条件。"
    elif kind == "table":
        summary = "检测到表格结构；学习时先读表头，再比较每列的条件和结果。"
    else:
        summary = "页面以文字为主；先找标题、定义、条件和结论。"

    review_reasons: list[str] = []
    if image_count:
        review_reasons.append("含图片或截图")
    if not source:
        review_reasons.append("没有可提取文字")
    if arrows or diagram_keywords:
        review_reasons.append("连接关系需要视觉确认")
    if formula_candidates:
        review_reasons.append("公式结构需要核对")
    confidence = "high" if source and (code_lines or formula_candidates or arrows or table_hits) else "medium" if source else "unresolved"
    return {
        "kind": kind,
        "summary": summary,
        "code_lines": code_lines[:20],
        "code_candidates": code_candidates,
        "formula_candidates": formula_candidates[:12],
        "formula_relations": formula_relations,
        "diagram_keywords": diagram_keywords,
        "diagram_nodes": nodes[:40],
        "diagram_edges": edges[:40],
        "arrow_count": arrows,
        "table_hits": table_hits,
        "shape_counts": counts,
        "image_count": image_count,
        "confidence": confidence,
        "review_required": bool(review_reasons),
        "review_reasons": review_reasons,
        "domain_signals": domain_signals or {},
    }


def annotate_speech_metadata(metadata: Mapping[str, Any] | None, text: str) -> dict[str, Any]:
    """Merge a speech analysis record without overwriting provider metadata."""

    result = dict(metadata or {})
    result["speech_analysis"] = classify_speech_text(text)
    result["speech_increment"] = extract_speech_increment(text)
    return result


__all__ = [
    "annotate_speech_metadata",
    "classify_speech_text",
    "extract_speech_increment",
    "speech_role_label",
    "tokenize",
    "visual_signals",
]
