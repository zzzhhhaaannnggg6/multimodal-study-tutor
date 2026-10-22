"""Bounded, ordinary binary addition/subtraction with visible column work.

This is not fixed-width machine arithmetic or a two's-complement decoder.
Ambiguous extra numbers, signed encodings and unsupported operations abstain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_TRANSLATION = {**{code: chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)}, ord("−"): "-"}
_TOKEN = r"(?:\([01]{1,17}\)(?:₂|_2|2|[bB])?|0[bB][01]{1,17}|[01]{1,17}(?:₂|_2)?)"
_LITERAL = re.compile(rf"(?<![A-Za-z0-9_.])(?P<token>{_TOKEN})(?![A-Za-z0-9_.])")
_EXPRESSION = re.compile(rf"(?<![A-Za-z0-9_.])(?P<left>{_TOKEN})\s*(?P<op>[+-])\s*(?P<right>{_TOKEN})(?:\s*=\s*(?P<answer>{_TOKEN}))?(?![A-Za-z0-9_.])")
_UNSUPPORTED = re.compile(
    r"补码|反码|原码|有符号|位宽|字长|截断|溢出|two.s complement|\bsigned\b|fixed.width|\boverflow\b|\bmod\b"
    r"|carry[ -]?in|borrow[ -]?in|\bcin\b|\bbin\b|进位输入|借位输入|初始进位|初始借位"
    r"|十进制|八进制|十六进制|\bdecimal\b|\boctal\b|\bhexadecimal\b|转换|\bconvert\b", re.I)


def _digits(token: str) -> str:
    if token.lower().startswith("0b"):
        return token[2:]
    if token.startswith("("):
        return token[1:token.index(")")]
    return re.sub(r"(?:₂|_2)$", "", token)


@dataclass(frozen=True)
class BinaryProblem:
    left: str
    right: str
    operator: str
    supplied: str | None = None


def find_binary_problem(text: str) -> BinaryProblem | None:
    text = text.translate(_TRANSLATION)
    if _UNSUPPORTED.search(text):
        return None
    literals = list(_LITERAL.finditer(text))
    binary_context = bool(re.search(r"二进制|\bbinary\b", text, re.I))
    if not binary_context and not (len(literals) >= 2 and all(re.search(r"₂|_2|\)[2bB]$|^0[bB]", row["token"]) for row in literals)):
        return None
    expressions = list(_EXPRESSION.finditer(text))
    residual = text
    add = bool(re.search(r"加法|相加|求和|\baddition\b|\badd\b", text, re.I))
    subtract = bool(re.search(r"减法|相减|被减数|减数|\bsubtraction\b|\bminuend\b|\bsubtrahend\b", text, re.I))
    if add and subtract:
        return None
    if len(expressions) == 1:
        match = expressions[0]
        if len(literals) != (3 if match["answer"] else 2):
            return None
        problem = BinaryProblem(_digits(match["left"]), _digits(match["right"]), match["op"], _digits(match["answer"]) if match["answer"] else None)
        if (add and problem.operator != "+") or (subtract and problem.operator != "-"):
            return None
        residual = text[:match.start()] + " " * (match.end() - match.start()) + text[match.end():]
    elif not expressions and len(literals) == 2 and (add or subtract):
        left, right = (_digits(row["token"]) for row in literals)
        if subtract and re.search(r"minuend|subtrahend|被减数|减数", text, re.I):
            minuend = re.search(rf"(?:minuend|被减数)\s*[:：]?\s*({_TOKEN})(?![A-Za-z0-9_.])", text, re.I)
            subtrahend = re.search(rf"(?:subtrahend|(?<!被)减数)\s*[:：]?\s*({_TOKEN})(?![A-Za-z0-9_.])", text, re.I)
            if not minuend or not subtrahend:
                return None
            left, right = _digits(minuend[1]), _digits(subtrahend[1])
        problem = BinaryProblem(left, right, "+" if add else "-")
        for row in reversed(literals):
            residual = residual[:row.start()] + " " * (row.end() - row.start()) + residual[row.end():]
    else:
        return None
    # Do not quietly solve only one part of an equation or an unknown operand.
    if re.search(r"[\d₀-₉+*/^=<>−–—-]|\b[a-zA-Z]\b", residual):
        return None
    if max(len(problem.left), len(problem.right)) > 16:
        return None
    if problem.operator == "-" and int(problem.left, 2) < int(problem.right, 2):
        return None  # An unsigned negative result needs an explicit convention.
    return problem


def binary_columns(problem: BinaryProblem) -> tuple[str, list[dict[str, int]]]:
    """Generate by local carry/borrow recurrence, not whole-number arithmetic."""
    width = max(len(problem.left), len(problem.right))
    left, right = problem.left.zfill(width), problem.right.zfill(width)
    incoming, bits, columns = 0, [], []
    for index, (a, b) in enumerate(zip(reversed(left), reversed(right))):
        a, b = int(a), int(b)
        total = a + b + incoming if problem.operator == "+" else a - b - incoming
        bit, outgoing = (total % 2, total // 2) if problem.operator == "+" else (total % 2, int(total < 0))
        columns.append({"index": index, "a": a, "b": b, "incoming": incoming, "total": total, "bit": bit, "outgoing": outgoing})
        bits.append(str(bit))
        incoming = outgoing
    if problem.operator == "+" and incoming:
        bits.append("1")
    return "".join(reversed(bits)), columns


def _column_text(column: dict[str, int], operator: str, *, explain: bool = True) -> str:
    c = column
    name = "进位" if operator == "+" else "借位"
    operation = "+" if operator == "+" else "-"
    text = (f"第 {c['index']} 位（位权 2^{c['index']}）：{c['a']} {operation} {c['b']} {operation} {name} {c['incoming']} = {c['total']}；"
            f"本位写 {c['bit']}，向左{name} {c['outgoing']}。")
    if explain and operator == "-" and c["outgoing"]:
        text += f"差为负，向高一位借来的 1 相当于本列的 2，所以 {c['total']}+2={c['bit']}。"
    elif explain and operator == "+" and c["outgoing"]:
        text += f"{c['total']} = {c['bit']} + 2×{c['outgoing']}，高出来的一个 2 传给左列。"
    return text


def _column_trace(columns: list[dict[str, int]], operator: str) -> list[str]:
    lines, explained = [], False
    for column in columns:
        lines.append(_column_text(column, operator, explain=not explained))
        explained = explained or bool(column["outgoing"])
    return lines


def binary_example(text: str) -> dict[str, Any] | None:
    problem = find_binary_problem(text)
    if problem is None:
        return None
    result, columns = binary_columns(problem)
    a, b = int(problem.left, 2), int(problem.right, 2)
    value = int(result, 2)
    name = "加法" if problem.operator == "+" else "减法"
    carry = "进位" if problem.operator == "+" else "借位"
    width = max(len(problem.left), len(problem.right))
    variant = BinaryProblem(format(a + 1, "b").zfill(len(problem.left)), problem.right, problem.operator)
    variant_result, variant_columns = binary_columns(variant)
    chosen = next((c for c in columns if c["outgoing"] and c["incoming"]), next((c for c in columns if c["outgoing"]), columns[0]))
    literal = lambda digits: f"({digits})₂"
    expression = f"{literal(problem.left)} {problem.operator} {literal(problem.right)}"
    variant_expression = f"{literal(variant.left)} {problem.operator} {literal(variant.right)}"
    conflict = problem.supplied is not None and int(problem.supplied, 2) != value
    steps = [f"把 {problem.left.zfill(width)} 与 {problem.right.zfill(width)} 的最低位对齐，不足的高位补 0。最右边是第 0 位，初始{carry}为 0。"]
    steps.extend(_column_trace(columns, problem.operator))
    if problem.operator == "+" and columns[-1]["outgoing"]:
        steps.append(f"最高原位仍向左进位 1，把它放在新的最高位；结果是 {literal(result)}，不能把最左侧的 1 丢掉。")
    steps.append(f"从最高位向最低位读取结果 {literal(result)}。独立换成十进制核对：{a} {problem.operator} {b} = {value}。")
    setup = f"【导师补链】按普通无符号整数的二进制{name}计算，保留全部结果位；这不是固定字长的截断或补码运算。初始{carry}为 0。"
    final = f"【导师补链】结果为 {literal(result)}，十进制 {value}。"
    if conflict:
        setup += f"【待确认】材料写作 {literal(problem.supplied)}，与逐列计算的 {literal(result)} 不一致，需要核对原页。"
        final = f"【待确认】计算得到 {literal(result)}，材料写作 {literal(problem.supplied)}；保留双方，尚不能当作教师勘误。"
    process_prompt = f"仍计算 {expression}。第 {chosen['index']} 位读到 {chosen['a']} 和 {chosen['b']}，来自右侧的{carry}是 {chosen['incoming']}。补出本位和向左{carry}。"
    process_answer = f"本位={chosen['bit']}；{carry}={chosen['outgoing']}。"
    retrieval_prompt = "一列相加得到十进制 2，应写哪个本位、向左进位多少？" if problem.operator == "+" else "向左侧高一位借来的 1，在当前位相当于多少？"
    retrieval_answer = "本位=0；进位=1。" if problem.operator == "+" else "相当于当前位的 2。"
    variant_explanation = "\n".join(_column_trace(variant_columns, problem.operator))
    return {
        "one_sentence": f"能逐位计算 {expression}，说明每次{carry}，并独立重算改变一个数后的结果。",
        "why": f"只记住二进制{name}的结果，换一组数就容易出错。逐位记录本位和{carry}，才能解释位之间怎样相互影响，也能看出漏掉最高进位或忘记借位会错在哪里。",
        "material_explanation": f"材料给出 {expression}。先按二进制读取原数，保留前导零；{name}从最右列开始。{carry}来自右侧已经算完的一列，不能把所有列当成彼此独立。" + (setup[setup.index("【待确认】"):] if conflict else ""),
        "tutor_bridge": "【导师补链】相邻二进制位的位权相差 2 倍。加法一列凑够 2，就把一个单位传给左列；减法不够减时，从左列借来的一个单位相当于本列的 2。写在本列的只能是 0 或 1。" + (
            "加法中，右列传来的进位要加进本列，然后重新拆成本位和新的进位。" if problem.operator == "+" else
            "减法中，右列传来的借位表示它已经向本列借走了 1，所以本列要再减 1；本列仍不够减时，才向左借 1，在本列加 2。"),
        "prerequisites": ["知道二进制每位只能写 0 或 1", "理解右起各位的位权是 1、2、4、8…"],
        "step_chain": [f"对齐最低位并确定初始{carry}", f"从右向左算出本位和传向左侧的{carry}", "保留完整结果并用十进制反查"],
        "question": f"计算 {expression}，逐列写出本位和{carry}，并用十进制检查。",
        "setup": setup, "steps": steps, "answer": final,
        "variation": f"只把第一个数增加 1，改算 {variant_expression}。完整结果为 {literal(variant_result)}；不能照抄原题的{carry}链。",
        "complete": not conflict, "source_conflict": conflict,
        "answer_check": {"kind": "binary-arithmetic", "left": problem.left, "right": problem.right, "operator": problem.operator, "value": value,
                         "columns": columns, "variant_left": variant.left, "variant_result": variant_result},
        "misconceptions": [{"wrong": "每列只看两个原始位，不管右边传来的进位或借位。", "correct": f"本列还要计入右侧传来的{carry}；它会改变本位和下一次{carry}。", "correction": _column_text(chosen, problem.operator)},
                           ({"wrong": "加法最高位产生进位，就直接丢掉。", "correct": "普通整数运算保留最高进位；固定字长是否截断，要另看题目条件。", "correction": "先问题目要求完整整数还是给定位宽的存储结果，不能把这两种问题混在一起。"} if problem.operator == "+" else
                            {"wrong": "向高一位借 1，只让当前列加 1；右列传来的借位也应该加上。", "correct": "向左借 1 要在当前列加 2；右列已经借走的 1，要从当前列减去。", "correction": "分清两笔借账：右列向本列借走的要减，向左列新借来的按本列位权折成 2。"})],
        "practice": [
            {"kind": "retrieval", "difficulty": "基础", "prompt": retrieval_prompt, "answer": retrieval_answer, "explanation": "相邻位权相差 2 倍，所以当前列的 2 对应左列的 1；这也是二进制进位和借位的依据。"},
            {"kind": "process", "difficulty": "过程", "prompt": process_prompt, "answer": process_answer, "explanation": _column_text(chosen, problem.operator)},
            {"kind": "transfer", "difficulty": "迁移", "prompt": f"只把第一个数增加 1，改算 {variant_expression}，其他规则不变。请独立写出完整结果。", "answer": literal(variant_result), "explanation": variant_explanation + f"\n从高位读回得到 {literal(variant_result)}；十进制核对结果为 {value + 1}。"},
        ],
    }


__all__ = ["BinaryProblem", "find_binary_problem", "binary_columns", "binary_example"]
