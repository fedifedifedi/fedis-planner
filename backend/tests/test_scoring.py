"""Soft constraints: consecutive rule, scoring function, CP-SAT objective, score == objective."""

import pytest
from pydantic import ValidationError

from planner.generator import generate
from planner.model import (
    Assignment,
    Course,
    Day,
    GridConfig,
    Group,
    Instance,
    Room,
    RoomType,
    Solution,
    Teacher,
    TimeSlot,
)
from planner.scoring import CRITERIA, Weights, disjoint_blocks, score
from planner.solver import solve
from planner.validate import check_solution

ONLY = {k: 0 for k in CRITERIA}


def only(**w) -> Weights:
    return Weights(**{**ONLY, **w})


def day(name, n, late_last=False, start=8, step_min=100) -> Day:
    """n slots of 90 min separated by 10-min breaks (consecutive under the 15-min rule)."""
    slots = []
    for i in range(n):
        s = start * 60 + i * step_min
        e = s + 90
        slots.append(TimeSlot(start=f"{s // 60:02d}:{s % 60:02d}", end=f"{e // 60:02d}:{e % 60:02d}",
                              late=late_last and i == n - 1))
    return Day(name=name, slots=slots)


def make(courses, days, groups=None, teachers=None, rooms=None) -> Instance:
    return Instance(
        grid=GridConfig(days=days),
        teachers=teachers or [Teacher(id=f"T{i}", name=f"t{i}") for i in range(4)],
        rooms=rooms or [Room(id="R1", name="r", capacity=50, type=RoomType.TD),
                        Room(id="R2", name="r2", capacity=50, type=RoomType.TD),
                        Room(id="L1", name="l", capacity=50, type=RoomType.TP)],
        groups=groups or [Group(id="G", name="G", size=20)],
        courses=courses,
    )


def c(cid, teacher="T0", group="G", rtype=RoomType.TD, sessions=1, **kw) -> Course:
    return Course(id=cid, subject=cid, teacher_id=teacher, group_ids=[group], room_type=rtype,
                  sessions_per_week=sessions, **kw)


def slots(res, cid=None) -> list[int]:
    return sorted(a.slot for a in res.solution.assignments if cid is None or a.course_id == cid)


def check_optimal(inst, res, weights):
    assert res.status == "OPTIMAL"
    assert check_solution(inst, res.solution) == []
    assert score(inst, res.solution, weights).total == res.stats["objective"]


# ------------------------------------------------------------------ consecutive rule


def test_default_grid_consecutive_pairs_skip_lunch():
    g = GridConfig()
    assert {(0, 1), (1, 2), (3, 4)} <= g.consecutive_pairs
    assert (2, 3) not in g.consecutive_pairs  # 13:20 -> 14:00 = 40 min lunch
    assert {(25, 26), (26, 27)} <= g.consecutive_pairs
    assert len(g.consecutive_pairs) == 5 * 3 + 2
    assert (4, 5) not in g.consecutive_pairs  # never across days


def test_max_break_is_configurable():
    assert (2, 3) in GridConfig(max_break_minutes=45).consecutive_pairs
    assert GridConfig(max_break_minutes=5).consecutive_pairs == frozenset()


def test_full_days_exclude_short_saturday():
    assert GridConfig().full_days == [0, 1, 2, 3, 4]


def test_disjoint_blocks():
    g = GridConfig()
    assert disjoint_blocks(g, [0, 1, 2]) == [(0, 1)]
    assert disjoint_blocks(g, [1, 2, 3, 4]) == [(1, 2), (3, 4)]
    assert disjoint_blocks(g, [2, 3]) == []  # lunch


def test_weights_reject_negative():
    with pytest.raises(ValidationError):
        Weights(late=-1)


# ------------------------------------------------------------------ scoring by hand


def test_score_breakdown_by_hand():
    days = [day("D1", 4, late_last=True), day("D2", 4, late_last=True), day("Sat", 2)]
    inst = make([c("A", sessions=2, max_sessions_per_day=2), c("B", teacher="T1"),
                 c("L", teacher="T2", rtype=RoomType.TP, sessions=2)], days)
    # D1: A@0, A@2 (gap at 1) ; D2: B@7 (late, single) ; L split across D1@3 (late) and Sat@8
    sol = Solution(assignments=[
        Assignment(course_id="A", session=0, slot=0, room_id="R1"),
        Assignment(course_id="A", session=1, slot=2, room_id="R1"),
        Assignment(course_id="B", session=0, slot=7, room_id="R1"),
        Assignment(course_id="L", session=0, slot=3, room_id="L1"),
        Assignment(course_id="L", session=1, slot=8, room_id="L1"),
    ])
    b = score(inst, sol).breakdown
    assert b["student_gaps"] == 1        # D1: 0 _ 2 3
    assert b["teacher_gaps"] == 1        # T0 on D1: 0 _ 2
    assert b["late"] == 2                # slots 3 and 7
    assert b["tp_split"] == 1            # L not consecutive
    assert b["imbalance"] == 2           # full days D1=3, D2=1
    assert b["single_session_day"] == 2  # D2 and Sat
    w = Weights()
    assert score(inst, sol).total == 3 * 1 + 1 * 1 + 2 * 2 + 4 * 1 + 1 * 2 + 2 * 2


# ------------------------------------------------------------------ objective by hand (one criterion each)


def test_late_slot_avoided():
    inst = make([c("A")], [day("D", 2, late_last=True)])
    res = solve(inst, weights=only(late=1))
    check_optimal(inst, res, only(late=1))
    assert slots(res) == [0]


def test_student_gap_avoided():
    inst = make([c("A"), c("B", teacher="T1")], [day("D", 3)])
    res = solve(inst, weights=only(student_gaps=1))
    check_optimal(inst, res, only(student_gaps=1))
    assert slots(res) in ([0, 1], [1, 2])


def test_teacher_gap_avoided():
    inst = make([c("A", group="G"), c("B", group="H")], [day("D", 3)],
                groups=[Group(id="G", name="G", size=20), Group(id="H", name="H", size=20)])
    res = solve(inst, weights=only(teacher_gaps=1))
    check_optimal(inst, res, only(teacher_gaps=1))
    assert slots(res) in ([0, 1], [1, 2])


def test_tp_sessions_made_consecutive_not_across_lunch():
    lunch_day = Day(name="D", slots=[TimeSlot(start="10:00", end="11:30"), TimeSlot(start="11:40", end="13:10"),
                                     TimeSlot(start="14:00", end="15:30")])
    inst = make([c("L", rtype=RoomType.TP, sessions=2)], [lunch_day, lunch_day])
    res = solve(inst, weights=only(tp_split=1))
    check_optimal(inst, res, only(tp_split=1))
    a, b = slots(res, "L")
    assert (a, b) in inst.grid.consecutive_pairs and (a, b) not in {(1, 2), (4, 5)}


def test_unavoidable_tp_split_counted():
    lunch_day = Day(name="D", slots=[TimeSlot(start="10:00", end="11:30"), TimeSlot(start="14:00", end="15:30")])
    inst = make([c("L", rtype=RoomType.TP, sessions=2)], [lunch_day])
    res = solve(inst, weights=only(tp_split=1))
    check_optimal(inst, res, only(tp_split=1))
    assert res.stats["objective"] == 1


def test_days_balanced():
    inst = make([c("A"), c("B", teacher="T1")], [day("D1", 2), day("D2", 2)])
    res = solve(inst, weights=only(imbalance=1))
    check_optimal(inst, res, only(imbalance=1))
    s = slots(res)
    assert s[0] < 2 <= s[1]  # one session per day


def test_single_session_day_avoided_saturday_included():
    # 2 sessions: grouping them on one day avoids two single-session days (Saturday counts too)
    inst = make([c("A"), c("B", teacher="T1")], [day("Mon", 1), day("Sat", 2)])
    res = solve(inst, weights=only(single_session_day=1))
    check_optimal(inst, res, only(single_session_day=1))
    assert slots(res) == [1, 2]


def test_weights_trade_off():
    """Balance vs single-session day pull in opposite directions; the heavier one wins."""
    inst = make([c("A"), c("B", teacher="T1")], [day("D1", 2), day("D2", 2)])
    spread = solve(inst, weights=only(imbalance=3, single_session_day=1))
    grouped = solve(inst, weights=only(imbalance=1, single_session_day=3))
    s1, s2 = slots(spread), slots(grouped)
    assert s1[0] < 2 <= s1[1]
    assert s2 in ([0, 1], [2, 3])


def test_optimize_false_has_no_objective():
    res = solve(make([c("A")], [day("D", 2)]), optimize=False)
    assert res.stats["objective"] is None and res.stats["score"] is None


# ------------------------------------------------------------------ generated instances


def test_score_matches_objective_on_generated_instance():
    inst = generate("small", seed=42)
    res = solve(inst, time_limit=10, random_seed=0)
    assert res.feasible and check_solution(inst, res.solution) == []
    total = score(inst, res.solution).total
    assert res.stats["score"]["total"] == total
    assert total <= res.stats["objective"]  # equal when auxiliaries are tight (always for OPTIMAL)
    assert res.stats["best_bound"] <= total
    assert 0 <= res.stats["gap"] <= 1
