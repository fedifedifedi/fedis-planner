from functools import partial

import pytest

from planner import solver
from planner.generator import INFEASIBLE_KINDS, generate, make_infeasible
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
from planner.solver import TimetableModel
from planner.validate import check_solution

# hard constraints only: these tests check feasibility, not the objective
solve = partial(solver.solve, optimize=False)


def grid(days: int = 1, slots: int = 2) -> GridConfig:
    times = [TimeSlot(start=f"{8 + 2 * i:02d}:00", end=f"{9 + 2 * i:02d}:30") for i in range(slots)]
    return GridConfig(days=[Day(name=f"D{d}", slots=times) for d in range(days)])


def course(cid, teacher, groups, rtype=RoomType.TD, sessions=1, **kw) -> Course:
    return Course(id=cid, subject=cid, teacher_id=teacher, group_ids=groups, room_type=rtype,
                  sessions_per_week=sessions, **kw)


def inst(courses, *, g=None, teachers=None, rooms=None, groups=None, validate=True) -> Instance:
    # validate=False skips model checks (volume checks would already reject some cases),
    # so the solver constraint itself is tested
    build = Instance if validate else Instance.model_construct
    return build(
        grid=g or grid(),
        teachers=teachers or [Teacher(id="T1", name="a"), Teacher(id="T2", name="b")],
        rooms=rooms or [Room(id="R1", name="r1", capacity=40, type=RoomType.TD),
                        Room(id="R2", name="r2", capacity=40, type=RoomType.TD)],
        groups=groups or [Group(id="G1", name="G1", size=30), Group(id="G2", name="G2", size=30)],
        courses=courses,
    )


def slots_of(res, cid) -> list[int]:
    return sorted(a.slot for a in res.solution.assignments if a.course_id == cid)


def assert_valid(instance, res):
    assert res.feasible, res.status
    assert check_solution(instance, res.solution) == []


# ------------------------------------------------------------------ hand-checkable cases


def test_teacher_cannot_teach_two_courses_at_once():
    i = inst([course("A", "T1", ["G1"]), course("B", "T1", ["G2"])])
    res = solve(i)
    assert_valid(i, res)
    assert slots_of(res, "A") != slots_of(res, "B")


def test_teacher_double_booking_infeasible_with_single_slot():
    i = inst([course("A", "T1", ["G1"]), course("B", "T1", ["G2"])], g=grid(slots=1), validate=False)
    assert solve(i).status == "INFEASIBLE"


def test_room_double_booking_infeasible_with_single_room():
    rooms = [Room(id="R1", name="r1", capacity=40, type=RoomType.TD)]
    i = inst([course("A", "T1", ["G1"]), course("B", "T2", ["G2"])], g=grid(slots=1), rooms=rooms)
    assert solve(i).status == "INFEASIBLE"


def test_two_rooms_allow_parallel_courses():
    i = inst([course("A", "T1", ["G1"]), course("B", "T2", ["G2"])], g=grid(slots=1))
    res = solve(i)
    assert_valid(i, res)
    assert {a.room_id for a in res.solution.assignments} == {"R1", "R2"}


def test_capacity_restricts_rooms():
    rooms = [Room(id="SMALL", name="s", capacity=20, type=RoomType.TD),
             Room(id="BIG", name="b", capacity=40, type=RoomType.TD)]
    i = inst([course("A", "T1", ["G1"])], rooms=rooms)  # 30 students
    res = solve(i)
    assert_valid(i, res)
    assert res.solution.assignments[0].room_id == "BIG"


def test_room_type_respected():
    rooms = [Room(id="TD", name="td", capacity=40, type=RoomType.TD),
             Room(id="LAB", name="lab", capacity=40, type=RoomType.TP)]
    i = inst([course("A", "T1", ["G1"], rtype=RoomType.TP)], rooms=rooms)
    res = solve(i)
    assert_valid(i, res)
    assert res.solution.assignments[0].room_id == "LAB"


def test_teacher_availability_respected():
    teachers = [Teacher(id="T1", name="a", unavailable=[0]), Teacher(id="T2", name="b")]
    i = inst([course("A", "T1", ["G1"])], teachers=teachers)
    res = solve(i)
    assert_valid(i, res)
    assert slots_of(res, "A") == [1]


def test_sessions_per_week_and_max_per_day():
    # 2 sessions, max 1/day, 2 days x 2 slots -> one session each day
    i = inst([course("A", "T1", ["G1"], sessions=2)], g=grid(days=2, slots=2))
    res = solve(i)
    assert_valid(i, res)
    s = slots_of(res, "A")
    assert len(s) == 2 and s[0] < 2 <= s[1]
    assert [a.session for a in sorted(res.solution.assignments, key=lambda a: a.slot)] == [0, 1]


def test_lab_can_take_two_sessions_same_day():
    rooms = [Room(id="LAB", name="lab", capacity=40, type=RoomType.TP)]
    i = inst([course("A", "T1", ["G1"], rtype=RoomType.TP, sessions=2)], g=grid(days=1, slots=2), rooms=rooms)
    res = solve(i)
    assert_valid(i, res)
    assert slots_of(res, "A") == [0, 1]


SUBGROUPS = [
    Group(id="G1", name="G1", size=30),
    Group(id="G1a", name="G1a", size=15, parent="G1"),
    Group(id="G1b", name="G1b", size=15, parent="G1"),
]


def test_parent_and_subgroup_never_overlap():
    i = inst([course("P", "T1", ["G1"]), course("S", "T2", ["G1a"])], g=grid(slots=1), groups=SUBGROUPS,
             validate=False)
    assert solve(i).status == "INFEASIBLE"
    i2 = inst([course("P", "T1", ["G1"]), course("S", "T2", ["G1a"])], g=grid(slots=2), groups=SUBGROUPS)
    res = solve(i2)
    assert_valid(i2, res)
    assert slots_of(res, "P") != slots_of(res, "S")


def test_sibling_subgroups_may_run_in_parallel():
    i = inst([course("A", "T1", ["G1a"]), course("B", "T2", ["G1b"])], g=grid(slots=1), groups=SUBGROUPS)
    res = solve(i)
    assert_valid(i, res)
    assert slots_of(res, "A") == slots_of(res, "B") == [0]


def test_shared_cm_blocks_every_group():
    rooms = [Room(id="AMPHI", name="a", capacity=100, type=RoomType.CM),
             Room(id="R1", name="r1", capacity=40, type=RoomType.TD)]
    courses = [course("CM", "T1", ["G1", "G2"], rtype=RoomType.CM), course("TD", "T2", ["G2"])]
    i = inst(courses, g=grid(slots=1), rooms=rooms, validate=False)
    assert solve(i).status == "INFEASIBLE"


def test_unavailable_slots_create_no_variables():
    teachers = [Teacher(id="T1", name="a", unavailable=[0]), Teacher(id="T2", name="b")]
    tm = TimetableModel(inst([course("A", "T1", ["G1"])], teachers=teachers))
    assert ("A", 0) not in tm.x and ("A", 1) in tm.x


def test_stats_and_random_seed():
    i = inst([course("A", "T1", ["G1"]), course("B", "T1", ["G2"])])
    res = solve(i, time_limit=5, workers=2, random_seed=3)
    s = res.stats
    assert s["status"] == res.status == "OPTIMAL"
    assert s["workers"] == 2 and s["random_seed"] == 3 and s["time_limit"] == 5
    assert s["variables"] > 0 and s["constraints"] > 0
    assert s["objective"] is None and s["best_bound"] is None and s["gap"] is None  # no objective yet


# ------------------------------------------------------------------ validator


def test_validator_flags_violations():
    i = inst([course("A", "T1", ["G1"]), course("B", "T1", ["G2"])])
    bad = Solution(assignments=[Assignment(course_id="A", session=0, slot=0, room_id="R1"),
                                Assignment(course_id="B", session=0, slot=0, room_id="R1")])
    errors = check_solution(i, bad)
    assert any("teacher T1 double-booked" in e for e in errors)
    assert any("room R1 double-booked" in e for e in errors)
    missing = check_solution(i, Solution(assignments=bad.assignments[:1]))
    assert any("0 sessions scheduled" in e for e in missing)


def test_validator_flags_parent_subgroup_overlap():
    i = inst([course("P", "T1", ["G1"]), course("S", "T2", ["G1a"])], groups=SUBGROUPS)
    bad = Solution(assignments=[Assignment(course_id="P", session=0, slot=0, room_id="R1"),
                                Assignment(course_id="S", session=0, slot=0, room_id="R2")])
    assert any("students of G1a" in e for e in check_solution(i, bad))


# ------------------------------------------------------------------ generated instances


@pytest.mark.parametrize("size", ["small", "medium"])
def test_generated_instances_are_solved_without_violation(size):
    i = generate(size, seed=42)
    res = solve(i, time_limit=60, random_seed=0)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert_valid(i, res)


@pytest.mark.parametrize("kind", INFEASIBLE_KINDS)
def test_infeasible_variants_detected(kind):
    res = solve(make_infeasible(generate("small", seed=42), kind), time_limit=30)
    assert res.status == "INFEASIBLE" and res.solution is None
