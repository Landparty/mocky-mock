"""#444: round-trip partners are decided as groups and never loop."""

from __future__ import annotations

from mockymock.dsl.real_file_suite import RealFilePlan, _round_trip_files


def _plan(name, reads, writes, partners, round_trip=False):
    plan = RealFilePlan(
        name,
        {name},
        reads=reads,
        writes=writes,
        first_create=10 if round_trip else None,
        first_open_read=20 if round_trip else None,
    )
    plan.partners = set(partners)
    return plan


def test_group_with_an_input_file_stays_mocked_and_terminates():
    work = _plan("WORK", True, True, {"PRT"}, round_trip=True)
    prt = _plan("PRT", False, True, {"WORK", "INF"})
    inf = _plan("INF", True, False, {"PRT"})
    assert _round_trip_files([work, prt, inf]) == []


def test_output_only_partner_joins_the_round_trip():
    work = _plan("WORK", True, True, {"PRT"}, round_trip=True)
    prt = _plan("PRT", False, True, {"WORK"})
    inf = _plan("INF", True, False, set())
    assert [p.file for p in _round_trip_files([work, prt, inf])] == ["PRT", "WORK"]


def test_unrelated_round_trip_groups_are_independent():
    a = _plan("A", True, True, set(), round_trip=True)
    b = _plan("B", True, True, {"IN"}, round_trip=True)
    inp = _plan("IN", True, False, {"B"})
    assert [p.file for p in _round_trip_files([a, b, inp])] == ["A"]
