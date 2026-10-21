"""Read bounded numerical answers by positional weights and geometric series.

Independent of the example generator's integer/remainder conversion method.
This is not a natural-language truth checker or a general symbolic solver.
"""

from __future__ import annotations

import re
from fractions import Fraction


BASES = {"₂": 2, "₈": 8, "₁₀": 10, "₁₆": 16}
LITERAL = re.compile(r"\((?P<digits>[+-]?[0-9A-Fa-f]+(?:\.[0-9A-Fa-f]*(?:\([0-9A-Fa-f]+\))?)?)\)(?P<base>₁₆|₁₀|₂|₈)")


def reference_value(digits: str, base: int) -> Fraction:
    if not isinstance(base, int) or base not in {2, 8, 10, 16} or not isinstance(digits, str) or len(digits) > 256:
        raise ValueError("Unsupported reference number.")
    match = re.fullmatch(r"(?P<sign>[+-]?)(?P<integer>[0-9A-Fa-f]+)(?:\.(?P<fraction>[0-9A-Fa-f]*)(?:\((?P<repeat>[0-9A-Fa-f]+)\))?)?", digits)
    if not match:
        raise ValueError("Malformed reference number.")
    integer, fraction, repeat = match["integer"], match["fraction"] or "", match["repeat"] or ""
    for char in integer + fraction + repeat:
        if int(char, 16) >= base:
            raise ValueError("Reference digit outside base.")
    result = sum(Fraction(int(char, 16)) * Fraction(base) ** index for index, char in enumerate(reversed(integer)))
    result += sum(Fraction(int(char, 16), base ** index) for index, char in enumerate(fraction, 1))
    if repeat:
        result += Fraction(int(repeat, base), base ** len(fraction) * (base ** len(repeat) - 1))
    return -result if match["sign"] == "-" else result


def answer_values(text: str, base: int) -> list[Fraction]:
    return [reference_value(row["digits"], base) for row in LITERAL.finditer(text) if BASES[row["base"]] == base]
