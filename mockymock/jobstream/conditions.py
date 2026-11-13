"""Whether a JCL step runs: `COND=` and `IF` conditions on return codes.

`cobolparser.jcl` gives each step one `condition` string: the coded
`COND=` (`(4,LE)`, `((4,LT),(8,GT,STEP1))`, `EVEN`, `ONLY`), or else the
enclosing `IF` conditions (`(S1.RC = 0)`, `NOT (...)` in an ELSE, nested
ones joined with ` AND `). A step coding both loses its IF there (still
so in cobol-parser 3.6.0); the job runner refuses such a step, see
`if_blocks`. `step_runs` evaluates either against the return
codes of the steps that ran so far. Anything it cannot read raises
`ConditionError`: the job runner then stops and reports the step as a gap,
since guessing would run (or skip) steps the real job would not.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable

#: Return code standing for an abended step.
ABEND = None


class ConditionError(Exception):
    """The condition cannot be evaluated exactly."""


class _StepBypassed(ConditionError):
    """The step a test names was bypassed: it has no return code."""


class _Ambiguous(ConditionError):
    """The step name a test uses matches several steps."""


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


_IF_CARD_RE = re.compile(
    r"^//[A-Z0-9@#$]*\s+(?P<verb>IF|ENDIF)(?:\s|\(|$)", re.IGNORECASE
)


def if_blocks(text: str) -> list[tuple[int, int]]:
    """The (IF line, ENDIF line) of every IF/THEN/ELSE/ENDIF construct in a
    JCL deck or procedure member, 1-based. An IF with no ENDIF runs to the
    end of the text."""
    blocks: list[tuple[int, int]] = []
    open_ifs: list[int] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if line.startswith("//*"):
            continue
        match = _IF_CARD_RE.match(line)
        if match is None:
            continue
        if match.group("verb").upper() == "IF":
            open_ifs.append(number)
        elif open_ifs:
            blocks.append((open_ifs.pop(), number))
    blocks.extend((start, len(lines) + 1) for start in open_ifs)
    return blocks


def inside(blocks: Iterable[tuple[int, int]], line: int) -> bool:
    return any(start < line < end for start, end in blocks)


def is_cond_parameter(condition: str) -> bool:
    text = condition.strip().upper()
    return text in ("EVEN", "ONLY") or bool(
        re.match(r"^\(*\s*(?:\d|(?:EVEN|ONLY)\s*,)", text)
    )


def _matches(names: Iterable[str], name: str) -> list[str]:
    return [
        key for key in names if key.endswith("." + name) or key.split(".")[-1] == name
    ]


def _step_rc(
    rcs: dict[str, int | None],
    step: str,
    bypassed: Collection[str] = (),
    current: str | None = None,
) -> int | None:
    """The RC of the earlier step `step` names. `current` is the step being
    decided (`INVOCATION.PROCSTEP` inside a procedure): there an unqualified
    name means the step of that same procedure invocation, as on z/OS --
    not a job-level step of the same name, nor the same step of another
    call of the procedure."""
    name = step.upper()
    if current and "." in current and "." not in name:
        own = f"{current.upper().rpartition('.')[0]}.{name}"
        if own in rcs:
            return rcs[own]
        if own in bypassed:
            raise _StepBypassed(f"step {step} was bypassed")
    if name in rcs:
        return rcs[name]
    matches = _matches(rcs, name)
    if len(matches) == 1:
        return rcs[matches[0]]
    if name in bypassed or len(_matches(bypassed, name)) == 1:
        raise _StepBypassed(f"step {step} was bypassed")
    if len(matches) > 1:
        raise _Ambiguous(f"step name {step} is ambiguous: {', '.join(sorted(matches))}")
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


_FLAG_LAST_RE = re.compile(r"^\((?P<tests>.*\))\s*,\s*(?P<flag>EVEN|ONLY)\s*\)$")
_FLAG_FIRST_RE = re.compile(r"^\(\s*(?P<flag>EVEN|ONLY)\s*,\s*(?P<tests>\(.*)\)$")


def _tests_and_flag(text: str) -> tuple[str, str | None]:
    """Split `COND=` into its test list and its EVEN / ONLY flag.

    `((4,LT,S1),EVEN)` and `(EVEN,(4,LT,S1))` hold the tests inside the
    outer parentheses (#436); a list of several tests keeps its own."""
    if text in ("EVEN", "ONLY"):
        return "", text
    for pattern in (_FLAG_LAST_RE, _FLAG_FIRST_RE):
        match = pattern.match(text)
        if match:
            tests = match.group("tests").strip()
            if re.search(r"\)\s*,\s*\(", tests):
                tests = f"({tests})"
            return tests, match.group("flag")
    return text, None


def cond_bypasses(
    condition: str,
    rcs: dict[str, int | None],
    abended: bool,
    bypassed: Collection[str] = (),
    step: str | None = None,
) -> bool:
    """Whether `COND=` bypasses the step: any test `(code,op[,step])` with
    `code op RC` true bypasses it. `EVEN` runs it even after an abend,
    `ONLY` only after one; without either an abend bypasses every later
    step. A test on a step that was bypassed is ignored, as on z/OS."""
    text = condition.strip().upper()
    tests_text, flag = _tests_and_flag(text)
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
            try:
                rc = _step_rc(rcs, match.group("step"), bypassed, step)
            except _StepBypassed:
                continue
            if rc is not None and op(code, rc):
                return True
        else:
            for rc in rcs.values():
                if rc is not None and op(code, rc):
                    return True
    return False


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<lp>\()|(?P<rp>\))|(?P<op>>=|<=|¬=|\^=|=|>|<|\bGT\b|\bGE\b|\bEQ\b|\bLT\b|\bLE\b|\bNE\b)"
    r"|(?P<bool>\||¬)|(?P<word>[A-Z0-9@#$.]+|&))",
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
    def __init__(
        self,
        tokens: list[str],
        rcs: dict[str, int | None],
        abended: bool,
        step: str | None = None,
        bypassed: Collection[str] = (),
    ):
        self.tokens = tokens
        self.index = 0
        self.rcs = rcs
        self.abended = abended
        self.step = step
        self.bypassed = bypassed

    def rc_of(self, name: str) -> int | None:
        # `bypassed` stops the lookup at a bypassed step of the procedure's
        # own invocation (`_StepBypassed`, a ConditionError): without it an
        # unqualified name falls through to a job-level step or another call
        # of the procedure that happens to share the name.
        return _step_rc(self.rcs, name, self.bypassed, current=self.step)

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

    def truth(self, name: str, value: bool) -> bool:
        """`value`, or its comparison with an explicit `= TRUE` / `= FALSE`
        (`EQ` too), which IBM's IF syntax allows after `ABEND`,
        `stepname.ABEND` and `stepname.RUN`."""
        if self.peek() not in ("=", "EQ"):
            if self.peek() in _OPS:
                raise ConditionError(
                    f"{name} can only be compared with = TRUE or = FALSE"
                )
            return value
        self.take()
        word = self.take()
        if word not in ("TRUE", "FALSE"):
            raise ConditionError(f"expected TRUE or FALSE after {name} =, got {word!r}")
        return value == (word == "TRUE")

    def abend_code(self, name: str) -> bool:
        """`ABENDCC = Sxxx` / `stepname.ABENDCC = Uxxxx`. The run does not keep
        the abend code, so the test is decided only when the step (or, bare,
        every step) did not abend: then it is false."""
        op = self.take()
        if op not in _OPS:
            raise ConditionError(f"expected an operator after {name}, got {op!r}")
        self.take()  # the code
        if name == "ABENDCC":
            abended = self.abended
        else:
            abended = self.rc_of(name[: -len(".ABENDCC")]) is ABEND
        if abended or op not in ("=", "EQ"):
            raise ConditionError(
                f"cannot evaluate {name}: the run does not record abend codes"
            )
        return False

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
                return self.truth(name, self.abended)
            return self.truth(name, self.rc_of(name[: -len(".ABEND")]) is ABEND)
        if name == "ABENDCC" or name.endswith(".ABENDCC"):
            return self.abend_code(name)
        if name.endswith(".RUN"):
            step = name[: -len(".RUN")]
            try:
                self.rc_of(step)
            except _Ambiguous:
                raise
            except ConditionError:  # bypassed, or never reached
                executed = False
            else:
                executed = True
            return self.truth(name, executed)
        if name == "RC" or name.endswith(".RC"):
            if name == "RC":
                ran = [rc for rc in self.rcs.values() if rc is not None]
                rc = max(ran) if ran else 0
            else:
                found = self.rc_of(name[: -len(".RC")])
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


def _is_abend_test(token: str) -> bool:
    return token in ("ABEND", "ABENDCC") or token.endswith((".ABEND", ".ABENDCC"))


def if_true(
    condition: str,
    rcs: dict[str, int | None],
    abended: bool,
    step: str | None = None,
    bypassed: Collection[str] = (),
) -> bool:
    return _IfParser(_tokens(condition), rcs, abended, step, bypassed).parse()


def step_runs(
    condition: str | None,
    rcs: dict[str, int | None],
    abended: bool,
    *,
    bypassed: Collection[str] = (),
    step: str | None = None,
) -> bool:
    """Whether a step with `condition` runs, given `rcs` (step name -> RC,
    None for an abend) of the steps that ran before it. `step` is the name
    of the step being decided (`INVOCATION.PROCSTEP` for a procedure step),
    which an unqualified step name in its condition is resolved against.

    Raises:
        ConditionError: The condition cannot be evaluated exactly.
    """
    if not condition or not condition.strip():
        return not abended
    if is_cond_parameter(condition):
        return not cond_bypasses(condition, rcs, abended, bypassed, step)
    tokens = _tokens(condition)
    # After an abend only an IF that tests ABEND (or an abend code,
    # ABENDCC) runs its steps. A token test, not a substring one: a step
    # named e.g. ABENDCHK is not a test.
    if abended and not any(_is_abend_test(t) for t in tokens):
        return False
    return _IfParser(tokens, rcs, abended, step, bypassed).parse()
