"""Exact, bounded positional-number examples; never execute source text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any


DIGITS = "0123456789ABCDEF"
BASE_NAMES = {2: "二进制", 8: "八进制", 10: "十进制", 16: "十六进制"}
SUBSCRIPTS = {2: "₂", 8: "₈", 10: "₁₀", 16: "₁₆"}
_BASE_WORDS = {"binary": 2, "octal": 8, "decimal": 10, "hexadecimal": 16,
               "二进制": 2, "八进制": 8, "十进制": 10, "十六进制": 16}
_WORD = "(?:" + "|".join(rf"\b{word}\b" if word.isascii() else word for word in _BASE_WORDS) + ")"
_TO = r"(?:\bto\b|转换(?:成|为)|转为|转成|转|→)"
_DIRECTION = re.compile(rf"(?P<source>{_WORD}).{{0,100}}?{_TO}\s*(?:the\s+)?(?P<target>{_WORD})", re.I)
_UNSIGNED = r"[0-9A-Fa-f]+(?:\.[0-9A-Fa-f]+)?"
_NUMBER = rf"[+-]?{_UNSIGNED}"
_SUFFIX = r"(?:₁₆|₁₀|₂|₈|_16|_10|_2|_8|16|10|2|8|[BOHD])"
_MARKED = re.compile(
    rf"(?<![A-Za-z0-9_.+\-])(?P<outer_sign>[+-]?)(?:\((?P<parenthesized>{_NUMBER})\)\s*(?P<suffix>{_SUFFIX})"
    rf"|(?P<bare>{_UNSIGNED})(?P<subscript>₁₆|₁₀|₂|₈|_16|_10|_2|_8)"
    rf"|(?P<hex>{_UNSIGNED})H|0x(?P<hex_prefix>{_UNSIGNED})|0b(?P<binary>[01]+(?:\.[01]+)?))(?![A-Za-z0-9_.+\-])",
    re.I,
)
_SUFFIX_BASES = {**{value: key for key, value in SUBSCRIPTS.items()},
                 "_2": 2, "_8": 8, "_10": 10, "_16": 16, "2": 2, "8": 8, "10": 10, "16": 16,
                 "B": 2, "O": 8, "D": 10, "H": 16}
_BARE = re.compile(rf"(?<![A-Za-z0-9_.+\-]){_NUMBER}(?![A-Za-z0-9_.+\-])")
_MARKER_HINT = re.compile(r"[₀-₉]|_\{?(?:16|10|2|8)\}?|0[bBxX]|\)\s*(?:16|10|2|8|[BOHD])(?![A-Za-z0-9_.])", re.I)
# Normalize only full-width ASCII and the mathematical minus. General Unicode
# normalization would erase subscript bases and superscript mathematical powers.
_NOTATION_TRANSLATION = {**{code: chr(code - 0xFEE0) for code in range(0xFF01, 0xFF5F)}, ord("−"): "-"}


def parse_number(digits: str, base: int) -> Fraction:
    if base not in BASE_NAMES or len(digits) > 48 or not re.fullmatch(_NUMBER, digits):
        raise ValueError("数制或数值格式不在当前精确转换范围内。")
    negative = digits.startswith("-")
    integer, _, fractional = digits.lstrip("+-").upper().partition(".")
    if any(DIGITS.index(char) >= base for char in integer + fractional):
        raise ValueError("数字超出原进制允许的范围。")
    value = Fraction(int(integer + fractional, base), base ** len(fractional))
    return -value if negative else value


@dataclass(frozen=True)
class Expansion:
    digits: str
    division_steps: tuple[str, ...]
    fraction_steps: tuple[str, ...]
    recurring: bool = False


def expand(value: Fraction, base: int) -> Expansion:
    """Use exact remainders; parentheses denote a recurring block."""
    if base not in BASE_NAMES:
        raise ValueError("不支持的目标进制。")
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    integer, remainder = divmod(magnitude.numerator, magnitude.denominator)
    whole = []
    divisions = []
    while integer:
        quotient, digit = divmod(integer, base)
        divisions.append(f"{integer} ÷ {base} = {quotient}，余 {digit}（写作 {DIGITS[digit]}）。")
        whole.append(DIGITS[digit])
        integer = quotient
        if len(whole) > 192:
            raise ValueError("转换结果过长，需分步处理。")
    whole_text = "".join(reversed(whole)) or "0"
    fraction = []
    multiplications = []
    seen = {}
    recurring = False
    while remainder:
        if remainder in seen:
            start = seen[remainder]
            fraction.insert(start, "(")
            fraction.append(")")
            multiplications.append(f"余数再次出现；从第 {start + 1} 个小数位起循环，括号内是循环节，不是有限截断。")
            recurring = True
            break
        if len(fraction) >= 64:
            raise ValueError("小数展开超过当前展示范围，不能把截断值当成精确答案。")
        seen[remainder] = len(fraction)
        before = Fraction(remainder, magnitude.denominator)
        digit, remainder = divmod(remainder * base, magnitude.denominator)
        after = Fraction(remainder, magnitude.denominator)
        multiplications.append(f"{before} × {base} = {digit} + {after}；取整数位 {DIGITS[digit]}，继续处理余下的 {after}。")
        fraction.append(DIGITS[digit])
    result = sign + whole_text + ("." + "".join(fraction) if fraction else "")
    return Expansion(result, tuple(divisions), tuple(multiplications), recurring)


@dataclass(frozen=True)
class Conversion:
    digits: str
    source_base: int
    target_base: int
    supplied_answer: str | None = None


def find_conversion(text: str) -> Conversion | None:
    """Require explicit bases/direction and one unambiguous source number."""
    if re.search(r"补码|反码|原码|固定(?:字长|位宽)|two.s complement|fixed.width", text, re.I):
        return None  # Ordinary positional notation is not fixed-width decoding.
    text = re.sub(r"_\{(2|8|10|16)\}", r"_\1", text.translate(_NOTATION_TRANSLATION))
    marked = []
    spans = []
    for match in _MARKED.finditer(text):
        if re.search(r"[+\-–—]\s*(?:\(\s*)?$", text[:match.start()]):
            return None
        digits = match["parenthesized"] or match["bare"] or match["hex"] or match["hex_prefix"] or match["binary"]
        if match["outer_sign"] and digits.startswith(("+", "-")):
            return None  # Do not silently choose one of two signs.
        digits = match["outer_sign"] + digits
        base = 16 if match["hex"] or match["hex_prefix"] else 2 if match["binary"] else _SUFFIX_BASES[(match["suffix"] or match["subscript"]).upper()]
        marked.append((digits.upper(), base, match.start(), match.end()))
        spans.append(match.span())
    residual = text
    for start, end in reversed(spans):
        residual = residual[:start] + " " * (end - start) + residual[end:]
    if _MARKER_HINT.search(residual):
        return None  # An unparsed base literal must not disappear beside a valid one.
    bare = [row for row in _BARE.finditer(residual) if any(char.isdigit() for char in row[0])]
    if marked and bare:
        return None  # A second unmarked number may be another exercise/condition.
    if (re.search(r"[×÷*/^%⁰¹²³⁴⁵⁶⁷⁸⁹]", residual)
            or re.search(r"\b(?:sqrt|log|sin|cos)\s*\(", residual, re.I)):
        return None
    directions = {(row["source"].lower(), row["target"].lower()) for row in _DIRECTION.finditer(" ".join(text.split()))}
    # An explicit equality is also a source task. Preserve a conflicting RHS,
    # but do not resolve contradictory conversion directions by guessing.
    if len(marked) == 2 and re.fullmatch(r"\s*=\s*", text[marked[0][3]:marked[1][2]]):
        left, right = marked
        if re.match(r"\s*[+\-–—×÷*/^%=]", text[right[3]:]):
            return None
        if directions and {(_BASE_WORDS[source], _BASE_WORDS[target]) for source, target in directions} != {(left[1], right[1])}:
            return None
        return Conversion(left[0], left[1], right[1], right[0])
    if re.search(r"[×÷*/^%=]", residual):
        return None
    if len(marked) == 1:
        _, _, start, end = marked[0]
        if (re.search(r"[+\-–—]\s*$", text[:start])
                or re.match(r"\s*[+\-–—×÷*/^%=]", text[end:])):
            return None
    if len(directions) == 1:
        source_word, target_word = directions.pop()
        source_base, target_base = _BASE_WORDS[source_word], _BASE_WORDS[target_word]
    elif not directions and len(marked) == 1:
        target = re.search(rf"{_TO}\s*(?:the\s+)?(?P<target>{_WORD})", text[marked[0][3]:], re.I)
        if not target:
            return None
        source_base, target_base = marked[0][1], _BASE_WORDS[target["target"].lower()]
    else:
        return None
    if source_base == target_base:
        return None
    if marked:
        candidates = {digits for digits, base, _, _ in marked if base == source_base}
        # More than one marked value could describe multiple exercises.
        if len(marked) != 1 or len(candidates) != 1:
            return None
    else:
        if len(bare) != 1:
            return None
        row = bare[0]
        # Unsupported spacing/grouping must not discard an outside minus,
        # a range dash, or an operation and reinterpret the operand alone.
        if (re.search(r"[+\-–—]\s*(?:\(\s*)?$", text[:row.start()])
                or re.search(r"[×÷*/^%=]", text)
                or re.search(r"\b(?:sqrt|log|sin|cos)\s*\(", text, re.I)):
            return None
        candidates = {row[0].upper()}
    if len(candidates) != 1:
        return None
    return Conversion(candidates.pop(), source_base, target_base)


def _literal(digits: str, base: int) -> str:
    return f"({digits}){SUBSCRIPTS[base]}"


def number_example(text: str) -> dict[str, Any] | None:
    problem = find_conversion(text)
    if not problem:
        return None
    try:
        value = parse_number(problem.digits, problem.source_base)
        result = expand(value, problem.target_base)
        supplied = parse_number(problem.supplied_answer, problem.target_base) if problem.supplied_answer else None
        fractional = problem.digits.partition(".")[2]
        change = Fraction(1) if problem.source_base == 10 else Fraction(1, problem.source_base ** len(fractional))
        variant_source = expand(value + change, problem.source_base).digits
        variant_target = expand(value + change, problem.target_base).digits
        decimal = expand(value, 10).digits
        original_value = expand(value, problem.source_base).digits
    except ValueError:
        return None
    source = _literal(problem.digits, problem.source_base)
    answer = _literal(result.digits, problem.target_base)
    unsigned = problem.digits.lstrip("+-")
    integer, _, fraction = unsigned.partition(".")
    terms = [f"{DIGITS.index(char)}×{problem.source_base}^{power}" for char, power in
             [*zip(integer, range(len(integer) - 1, -1, -1)), *zip(fraction, range(-1, -len(fraction) - 1, -1))]]
    steps = [f"按 {BASE_NAMES[problem.source_base]} 读取 {source}：每位数字必须小于 {problem.source_base}；小数点右侧第一位的指数为 -1。",
             f"展开位权：{' + '.join(terms)}。" + ("最前面的负号作用于整个数值。" if value < 0 else "") + f"合计为十进制 {decimal}。"]
    if problem.target_base == 10:
        steps.append(f"反向核对：将十进制 {decimal} 重新表示为{BASE_NAMES[problem.source_base]}，得到 {_literal(original_value, problem.source_base)}，与原数表示同一数值。核对时要保留正负；整数前导零和小数末尾零不改变数值。")
    else:
        steps.append(f"整数部分反复除以 {problem.target_base}，余数逆序读取：" + (" ".join(result.division_steps) or "整数部分为 0。"))
        steps.append(f"小数部分反复乘以 {problem.target_base}，整数位按产生顺序读取：" + (" ".join(result.fraction_steps) or "没有非零小数部分。"))
        steps.append(f"合并得到 {answer}。按目标进制的位权展开，应还原为同一个十进制数值 {decimal}。")
    conflict = supplied is not None and supplied != value
    setup = "【导师补链】同一个数值要换一种进制写法。先用位权算清它表示多少，再生成目标写法，最后反查数值。" + ("小数括号表示循环节，不能把有限前缀写成精确等式。" if result.recurring else "本例保留全部小数位，不做近似。")
    final = f"【导师补链】{source} = {answer}。"
    if conflict:
        stated = _literal(problem.supplied_answer, problem.target_base)
        setup += f"【待确认】材料将结果写为 {stated}，与按位权计算的 {answer} 不一致；需核对原页、进制标记或转写。"
        final = f"【待确认】计算得到 {answer}，材料写作 {stated}；两者存在冲突，尚不能将计算结果当作教师勘误。"
    variant = f"只把原数增加十进制 {change}，原数变成 {_literal(variant_source, problem.source_base)}；换成{BASE_NAMES[problem.target_base]}得到 {_literal(variant_target, problem.target_base)}。"
    return {
        "one_sentence": f"能把 {source} 转换成{BASE_NAMES[problem.target_base]}，并核对例题和变式的数值是否一致。",
        "why": "同一个数可以用不同进制表示。换进制时改变的是数字写法，数值必须保持不变；用位权展开检查，可以发现小数位、分组和抄写错误。",
        "material_explanation": f"材料给出的原数是 {source}，需要换成{BASE_NAMES[problem.target_base]}。原进制决定每一位的位权，目标进制决定答案的数字写法。" + (setup[setup.index("【待确认】"):] if conflict else ""),
        "tutor_bridge": "【导师补链】进制是每一位的计数规则。整数部分从右往左使用 0、1、2…次方，小数部分从左往右使用 -1、-2…次方。换进制保留相同数值，不能把字符串相同误当成数值相同。",
        "prerequisites": ["会用整数次幂和分数表示位权", "区分数字写法与它表示的数值"],
        "step_chain": ["核对原数和原进制", "按位权还原精确数值", "按目标进制逐位转换", "用相同数值反查结果"],
        "question": f"把 {source} 转换成{BASE_NAMES[problem.target_base]}，写出过程并检查数值是否保持不变。",
        "setup": setup, "steps": steps, "answer": final, "variation": variant, "complete": not conflict, "source_conflict": conflict,
        "answer_check": {"value": str(value), "source": problem.digits, "source_base": problem.source_base, "target_base": problem.target_base, "delta": str(change)},
        "misconceptions": [{"wrong": "小数点后的第一位也使用 0 次方，或者整数与小数的余数都倒过来读。", "correct": "第一个小数位使用 -1 次方；整数除法的余数逆序读，小数乘法的整数位顺序读。", "correction": f"将最终答案展开，核对它是否等于十进制 {decimal}。"}],
        "practice": [
            {"kind": "retrieval", "difficulty": "基础", "prompt": f"原数 {source} 的小数点后第一位，位权是多少？若没有小数位，新增一位应使用什么位权？", "answer": f"位权为 1/{problem.source_base}，即 {problem.source_base}^(-1)。", "explanation": "整数末位的指数为 0；小数点每向右移动一位，指数再减 1。"},
            {"kind": "process", "difficulty": "过程", "prompt": f"合上例题，把 {source} 的每一位乘上相应位权，算出精确的十进制数值。", "answer": f"十进制 {decimal}。", "explanation": f"先展开 {' + '.join(terms)}，再处理原数的正负号；整数与小数都必须计入。"},
            {"kind": "transfer", "difficulty": "迁移", "prompt": f"只把原数增加十进制 {change}，换成{BASE_NAMES[problem.target_base]}后是多少？写出新数值，不能照抄原答案。", "answer": _literal(variant_target, problem.target_base), "explanation": variant},
        ],
    }
