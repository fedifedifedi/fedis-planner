import pytest

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
from planner.replan import Absence, absence_for_days, replan
from planner.solver import solve
from planner.validate import check_solution


def grid(days: int, slots: int) -> GridConfig:
    times = [TimeSlot(start=f"{8 + 2 * i:02d}:00", end=f"{9 + 2 * i:02d}:30") for i in range(slots)]
    return GridConfig(days=[Day(name=f"D{d}", slots=times) for d in range(days)])


def course(cid, teacher, group="G"):
    return Course(id=cid, subject=cid, teacher_id=teacher, group_ids=[group], room_type=RoomType.TD,
                  sessions_per_week=1)


def make(courses, g, groups=None) -> Instance:
    return Instance(grid=g, teachers=[Teacher(id=f"T{i}", name=f"t{i}") for i in range(1, 5)],
                    rooms=[Room(id="R1", name="r1", capacity=40, type=RoomType.TD),
                           Room(id="R2", name="r2", capacity=40, type=RoomType.TD)],
                    groups=groups or [Group(id="G", name="G", size=20), Group(id="H", name="H", size=20)],
                    courses=courses)


def sol(*items) -> Solution:
    return Solution(assignments=[Assignment(course_id=c, session=0, slot=t, room_id=r) for c, t, r in items])


def slot_of(solution: Solution, cid: str) -> int:
    return next(a.slot for a in solution.assignments if a.course_id == cid)


# ------------------------------------------------------------------ hand-checkable


def test_only_affected_session_moves():
    inst = make([course("A", "T1"), course("B", "T2", "H")], grid(2, 2))
    old = sol(("A", 0, "R1"), ("B", 0, "R2"))
    res = replan(inst, old, Absence(teacher_id="T1", slots=[0]))
    assert res.feasible and res.sessions_moved == 1 == res.min_moves
    assert slot_of(res.solution, "B") == 0  # untouched
    assert slot_of(res.solution, "A") != 0
    assert res.rooms_changed == 0
    assert [c.course_id for c in res.changes] == ["A"]
    assert check_solution(inst, res.solution) == []


def test_domino_move():
    # G has A@0 and B@1 on a 2-slot day; T1 absent at 0 -> A must take 1, B must take 0
    inst = make([course("A", "T1"), course("B", "T2")], grid(1, 2))
    res = replan(inst, sol(("A", 0, "R1"), ("B", 1, "R1")), Absence(teacher_id="T1", slots=[0]))
    assert res.feasible and res.min_moves == 1 and res.sessions_moved == 2
    assert slot_of(res.solution, "A") == 1 and slot_of(res.solution, "B") == 0


def test_announced_mid_week_freezes_past_sessions():
    # 2 days x 2 slots (D0: 0,1 | D1: 2,3). Group G: B@0, A@2, C@3; slot 1 free.
    inst = make([course("A", "T1"), course("B", "T2"), course("C", "T3")], grid(2, 2))
    old = sol(("B", 0, "R1"), ("A", 2, "R1"), ("C", 3, "R1"))
    absence = Absence(teacher_id="T1", slots=[2])

    unconstrained = replan(inst, old, absence, announced_at=0)
    assert unconstrained.sessions_moved == 1
    assert slot_of(unconstrained.solution, "A") == 1  # cheapest: use the free past slot

    mid_week = replan(inst, old, absence, announced_at=2)  # D0 already happened
    assert mid_week.feasible and mid_week.frozen_sessions == 1
    assert mid_week.sessions_moved == 2 > unconstrained.sessions_moved  # forced extra move...
    assert slot_of(mid_week.solution, "B") == 0  # ...but no past session moved
    assert all(a.slot >= 2 for a in mid_week.solution.assignments if a.course_id != "B")
    assert all(ch.before_slot >= 2 and ch.after_slot >= 2 for ch in mid_week.changes)
    assert slot_of(mid_week.solution, "A") == 3 and slot_of(mid_week.solution, "C") == 2  # swap on D1
    assert check_solution(inst, mid_week.solution) == []


def test_past_absence_slots_are_ignored():
    inst = make([course("A", "T1"), course("B", "T2", "H")], grid(2, 2))
    old = sol(("A", 0, "R1"), ("B", 3, "R1"))
    res = replan(inst, old, Absence(teacher_id="T1", slots=[0]), announced_at=1)
    assert res.feasible and res.sessions_moved == 0 and res.min_moves == 0


def test_past_room_kept():
    inst = make([course("A", "T1"), course("B", "T2", "H")], grid(2, 2))
    old = sol(("A", 0, "R2"), ("B", 2, "R1"))
    res = replan(inst, old, Absence(teacher_id="T2", slots=[2]), announced_at=1)
    room_a = next(a.room_id for a in res.solution.assignments if a.course_id == "A")
    assert room_a == "R2"


def test_infeasible_replan_explains_with_past():
    # only future slot of G is 3, where T1 (A) becomes absent; everything before is frozen
    inst = make([course("A", "T1"), course("B", "T2"), course("C", "T3")], grid(2, 2))
    old = sol(("B", 0, "R1"), ("C", 1, "R1"), ("A", 3, "R1"))
    res = replan(inst, old, Absence(teacher_id="T1", slots=[3]), announced_at=2)
    # slot 2 is free for G: A can move there -> feasible
    assert res.feasible and slot_of(res.solution, "A") == 2
    res2 = replan(inst, old, Absence(teacher_id="T1", slots=[2, 3]), announced_at=2)
    assert not res2.feasible and res2.explanation is not None
    kinds = {c.family for c in res2.explanation.core}
    assert "past" in kinds and "availability" in kinds


def test_absence_exceeding_volume_reports_validation_message():
    inst = make([course("A", "T1")], grid(1, 2))
    res = replan(inst, sol(("A", 0, "R1")), Absence(teacher_id="T1", slots=[0, 1]))
    assert not res.feasible and "T1" in res.explanation.summary


def test_bad_inputs():
    inst = make([course("A", "T1")], grid(1, 2))
    with pytest.raises(ValueError):
        replan(inst, sol(("A", 0, "R1")), Absence(teacher_id="T9", slots=[0]))
    with pytest.raises(ValueError):
        replan(inst, sol(("A", 0, "R1")), Absence(teacher_id="T1", slots=[0]), announced_at=99)


# ------------------------------------------------------------------ generated instance


@pytest.fixture(scope="module")
def medium():
    inst = generate("medium", seed=42)
    return inst, solve(inst, time_limit=15, random_seed=0).solution


def test_absence_for_days():
    inst = generate("small", seed=42)
    assert absence_for_days(inst, "T001", ["Mardi"]).slots == [5, 6, 7, 8, 9]


def test_medium_teacher_absent_one_day(medium):
    inst, old = medium
    busiest = max(inst.teachers, key=lambda t: sum(c.sessions_per_week for c in inst.courses
                                                   if c.teacher_id == t.id))
    absence = absence_for_days(inst, busiest.id, ["Mardi"])
    res = replan(inst, old, absence, time_limit=20)
    assert res.feasible
    assert check_solution(inst, res.solution) == []
    assert res.min_moves <= res.sessions_moved <= res.min_moves + 5
    taught = {c.id for c in inst.courses if c.teacher_id == busiest.id}
    assert all(a.slot not in absence.slots for a in res.solution.assignments if a.course_id in taught)
    assert res.rooms_changed <= res.sessions_moved + 2
    # applying the changes to the old timetable gives the new one
    new_slots = {(a.course_id, a.slot) for a in res.solution.assignments}
    rebuilt = {(a.course_id, a.slot) for a in old.assignments}
    for ch in res.changes:
        if ch.kind == "moved":
            rebuilt.remove((ch.course_id, ch.before_slot))
            rebuilt.add((ch.course_id, ch.after_slot))
    assert rebuilt == new_slots
