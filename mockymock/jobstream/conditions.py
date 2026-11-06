"""Whether a JCL step runs: `COND=` and `IF` conditions on return codes.

`cobolparser.jcl` gives each step one `condition` string: the coded
`COND=` (`(4,LE)`, `((4,LT),(8,GT,STEP1))`, `EVEN`, `ONLY`), or else the
enclosing `IF` conditions (`(S1.RC = 0)`, `NOT (...)` in an ELSE, nested
ones joined with ` AND `). `step_runs` evaluates either against the return
codes of the steps that ran so far. Anything it cannot read raises
`ConditionError`: the job runner then stops and reports the step as a gap,
since guessing would run (or skip) steps the real job would not.
"""

from __future__ import annotations

import re

#: Return code standing for an abended step.
ABEND = None


class ConditionError(Exception):
    """The condition cannot be evaluated exactly."""


_COND_TEST_RE = re.compile(
    r"^\(?\s*(?P<code>\d{1,4})\s*,\s*(?P<op>GT|GE|EQ|LT|LE|NE)\s*"
    r"(?:,\s*(?P<step>[A-Z0-9@#$.]+))?\s*\)?$",
    re.IGNORECASE,
)
_OPS = {
    "GT": lambda a, b: a > b,
    "GE": lambda a, b: a >= b,
    "EQ": lambda a, b: a == b,
    "LT": lambda a, b: a < b,
    "LE": lambda a, b: a <= b,
    "NE": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "=": lambda a, b: a == b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "^=": lambda a, b: a != b,
    "¬=": lambda a, b: a != b,
}


def is_cond_parameter(condition: str) -> bool:
    text = condition.strip().upper()
    return text in ("EVEN", "ONLY") or bool(re.match(r"^\(*\s*\d", text))


def _step_rc(rcs: dict[str, int | None], step: str) -> int | None:
    name = step.upper()
    if name in rcs:
        return rcs[name]
    matches = [
        rc
        for key, rc in rcs.items()
        if key.endswith("." + name) or key.split(".")[-1] == name
    ]
    if len(matches) == 1:
        return matches[0]
    raise ConditionError(f"no earlier step named {step} ran")


def _split_tests(text: str) -> list[str]:
    inner = text.strip()
    if inner.startswith("((") and inner.endswith("))"):
        inner = inner[1:-1]
        return [
            part if part.startswith("(") else f"({part}"
            for part in re.split(r"\)\s*,\s*\(", inner)
        ]
    return [inner]


def cond_bypasses(condition: str, rcs: dict[str, int | None], abended: bool) -> bool:
    """Whether `COND=` bypasses the step: any test `(code,op[,step])` with
    `code op RC` true bypasses it. `EVEN` runs it even after an abend,
    `ONLY` only after one; without either an abend bypasses every later
    step."""
    text = condition.strip().upper()
    parts = [p.strip() for p in re.split(r",(?=\s*(?:EVEN|ONLY)\b)", text)]
    tests_text = parts[0]
    flag = parts[1] if len(parts) > 1 else None
    if tests_text in ("EVEN", "ONLY"):
        flag, tests_text = tests_text, ""
    if flag == "ONLY" and not abended:
        return True
    if abended and flag is None:
        return True
    for test in _split_tests(tests_text) if tests_text else []:
        test = test.strip()
        if test.endswith(")") and test.count(")") > test.count("("):
            test = test[:-1]
        match = _COND_TEST_RE.match(test)
        if match is None:
            raise ConditionError(f"COND test {test!r} is not (code,op[,step])")
        code = int(match.group("code"))
        op = _OPS[match.group("op").upper()]
        if match.group("step"):
            rc = _step_rc(rcs, match.group("step"))
            if rc is not None and op(code, rc):
                return True
        else:
            for rc in rcs.values():
                if rc is not None and op(code, rc):
                    return True
    return False


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<lp>\()|(?P<rp>\))|(?P<op>>=|<=|¬=|\^=|=|>|<|\bGT\b|\bGE\b|\bEQ\b|\bLT\b|\bLE\b|\bNE\b)"
    r"|(?P<word>[A-Z0-9@#$.]+|&))",
    re.IGNORECASE,
)


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None or match.end() == position:
            if text[position:].strip() == "":
                break
            raise ConditionError(f"cannot read IF condition {text!r}")
        tokens.append(match.group(0).strip().upper())
        position = match.end()
    return [t for t in tokens if t]


class _IfParser:
    def __init__(self, tokens: list[str], rcs: dict[str, int | None], abended: bool):
        self.tokens = tokens
        self.index = 0
        self.rcs = rcs
        self.abended = abended

    def peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> str:
        token = self.peek()
        if token is None:
            raise ConditionError("IF condition ends early")
        self.index += 1
        return token

    def parse(self) -> bool:
        value = self.or_expr()
        if self.peek() is not None:
            raise ConditionError(f"unexpected {self.peek()!r} in IF condition")
        return value

    def or_expr(self) -> bool:
        value = self.and_expr()
        while self.peek() in ("OR", "|"):
            self.take()
            right = self.and_expr()
            value = value or right
        return value

    def and_expr(self) -> bool:
        value = self.not_expr()
        while self.peek() in ("AND", "&"):
            self.take()
            right = self.not_expr()
            value = value and right
        return value

    def not_expr(self) -> bool:
        if self.peek() in ("NOT", "¬"):
            self.take()
            return not self.not_expr()
        return self.atom()

    def atom(self) -> bool:
        token = self.take()
        if token == "(":
            value = self.or_expr()
            if self.take() != ")":
                raise ConditionError("unbalanced parentheses in IF condition")
            return value
        name = token
        if name.endswith(".ABEND") or name == "ABEND":
            if name == "ABEND":
                return self.abended
            return _step_rc(self.rcs, name[: -len(".ABEND")]) is ABEND
        if name.endswith(".RUN"):
            step = name[: -len(".RUN")]
            try:
                _step_rc(self.rcs, step)
            except ConditionError:
                return False
            return True
        if name == "RC" or name.endswith(".RC"):
            if name == "RC":
                ran = [rc for rc in self.rcs.values() if rc is not None]
                rc = max(ran) if ran else 0
            else:
                found = _step_rc(self.rcs, name[: -len(".RC")])
                if found is None:
                    raise ConditionError(f"{name} of an abended step")
                rc = found
            op = self.take()
            if op not in _OPS:
                raise ConditionError(f"expected an operator after {name}, got {op!r}")
            number = self.take()
            if not number.isdigit():
                raise ConditionError(f"expected a number after {name} {op}")
            return _OPS[op](rc, int(number))
        raise ConditionError(f"cannot evaluate {name!r} in an IF condition")


def if_true(condition: str, rcs: dict[str, int | None], abended: bool) -> bool:
    return _IfParser(_tokens(condition), rcs, abended).parse()


def step_runs(condition: str | None, rcs: dict[str, int | None], abended: bool) -> bool:
    """Whether a step with `condition` runs, given `rcs` (step name -> RC,
    None for an abend) of the steps that ran before it.

    Raises:
        ConditionError: The condition cannot be evaluated exactly.
    """
    if not condition or not condition.strip():
        return not abended
    if is_cond_parameter(condition):
        return not cond_bypasses(condition, rcs, abended)
    if abended and "ABEND" not in condition.upper():
        return False
    return if_true(condition, rcs, abended)
