"""Issue #318: an unreadable item (a LOCAL-STORAGE field whose storage
cobc has not bound yet) no longer fails the whole Variables / evaluate
response, a NULL `.data` reads as unavailable, and an EXTERNAL item's
pointer shows its text."""

from __future__ import annotations

from mockymock.debug.gdb_session import GdbCommandError, ResultRecord
from mockymock.debug.variable_map import UNREADABLE_VALUE, read_variable
from tests.unit.test_adapter import (
    _fake_launch_session,
    _request,
    _run_adapter_capturing_session,
)
from tests.unit.test_variable_map import _done, _FakeSession


def test_null_data_pointer_is_unreadable_not_an_error() -> None:
    expr = "f_14"
    session = _FakeSession(
        {
            f"-data-evaluate-expression (int)({expr}).attr->type": _done("33"),
            f"-data-evaluate-expression (int)({expr}).attr->digits": _done("0"),
            f"-data-evaluate-expression (int)({expr}).attr->scale": _done("0"),
            f"-data-evaluate-expression (int)({expr}).attr->flags": _done("0"),
            f"-data-evaluate-expression ({expr}).size": _done("5"),
            f"-data-evaluate-expression (long)({expr}).data": _done("0"),
            f"-data-evaluate-expression {expr}": _done("{...}"),
        }
    )
    value = read_variable(session, "LS-NAME", expr)
    assert value.decoded == UNREADABLE_VALUE


def test_external_pointer_shows_its_text() -> None:
    session = _FakeSession(
        {
            "-data-evaluate-expression (int)(b_9).attr->type": ResultRecord(
                "error", {"msg": "There is no member named attr."}
            ),
            "-data-evaluate-expression b_9": _done('0x55555557c420 "ZZZZZ"'),
        }
    )
    value = read_variable(session, "WS-EXT", "b_9")
    assert value.decoded == "ZZZZZ"


def _launch_with_a_failing_item(arguments: dict):
    session = _fake_launch_session(arguments)
    session.variable_table = {"LS-COUNT": "f_14", **session.variable_table}
    original = session.gdb

    class _Gdb:
        def __getattr__(self, attr):
            return getattr(original, attr)

        def send(self, command: str):
            if "f_14" in command:
                raise GdbCommandError("-data-read-memory-bytes 0 5 produced no memory")
            return original.send(command)

    session.gdb = _Gdb()
    return session


def test_one_unreadable_item_does_not_fail_the_variables_response() -> None:
    messages, _ = _run_adapter_capturing_session(
        [
            _request(1, "launch", {}),
            _request(2, "variables", {"variablesReference": 1}),
            _request(3, "evaluate", {"expression": "LS-COUNT", "context": "hover"}),
        ],
        launch=_launch_with_a_failing_item,
    )
    variables_response, evaluate_response = messages[-2], messages[-1]
    assert variables_response["success"] is True
    rows = {v["name"]: v["value"] for v in variables_response["body"]["variables"]}
    assert rows["LS-COUNT"] == UNREADABLE_VALUE
    assert "WS-CUSTOMER-ID" in rows
    assert evaluate_response["success"] is True
    assert evaluate_response["body"]["result"] == UNREADABLE_VALUE
