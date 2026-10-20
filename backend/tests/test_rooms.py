"""Threshold decomposition: agreement with rooms='full', Hall cases, assumption guard, phase 2."""

from functools import partial

import pytest

from planner import solver
from planner.generator import INFEASIBLE_KINDS, generate, make_infeasible
from planner.model import Course, Day, GridConfig, Group, Instance, Room, RoomType, Teacher, TimeSlot
from planner.rooms import assign_rooms, threshold_violations
from planner.solver import TimetableModel
from planner.validate import check_solution

# hard constraints only: these tests check feasibility, not the objective
solve = partial(solver.solve, optimize=False)


def one_slot_grid(slots: int = 1) -> GridConfig:
    """90-min slots separated by 10-min breaks (consecutive under the default 15-min rule)."""
    times = []
    for i in range(slots):
        s = 8 * 60 + 100 * i
        times.append(TimeSlot(start=f"{s // 60:02d}:{s % 60:02d}", end=f"{(s + 90) // 60:02d}:{(s + 90) % 60:02d}"))
    return GridConfig(days=[Day(name="D", slots=times)])


def tiny(courses, rooms, groups, slots=1, validate=True) -> Instance:
    build = Instance if validate else Instance.model_construct
    return build(grid=one_slot_grid(slots), teachers=[Teacher(id=f"T{i}", name=f"t{i}") for i in range(4)],
                 rooms=rooms, groups=groups, courses=courses)


def td(cid, teacher, group, rtype=RoomType.TD, sessions=1):
    return Course(id=cid, subject=cid, teacher_id=teacher, group_ids=[group], room_type=rtype,
                  sessions_per_week=sessions)


# ------------------------------------------------------------------ agreement with rooms="full"


def agreement_cases():
    cases = [("small", generate("small", seed=42)), ("medium", generate("medium", seed=42))]
    for size in ("small", "medium"):
        for kind in INFEASIBLE_KINDS:
            cases.append((f"{size}-{kind}", make_infeasible(generate(size, seed=42), kind)))
    for seed in range(1, 6):  # tight rooms: the room constraints actually bind
        cases.append((f"tight-s{seed}", generate("small", seed=seed, tightness=1.0)))
    return cases


@pytest.mark.parametrize("name,instance", agreement_cases(), ids=[n for n, _ in agreement_cases()])
def test_threshold_and_full_agree(name, instance):
    threshold = solve(instance, rooms="threshold", time_limit=120, random_seed=0)
    full = solve(instance, rooms="full", time_limit=120, random_seed=0)
    assert threshold.stats["rooms_mode"] == "threshold" and full.stats["rooms_mode"] == "full"
    assert threshold.status == full.status
    if threshold.feasible:
        # rooms assigned by phase 2 -> full hard-constraint check
        assert check_solution(instance, threshold.solution) == []
        assert check_solution(instance, full.solution) == []


def test_threshold_model_is_much_smaller():
    inst = generate("medium", seed=42)
    t, f = TimetableModel(inst, rooms="threshold").stats(), TimetableModel(inst, rooms="full").stats()
    assert t["y_vars"] == 0 and f["y_vars"] > 0
    assert t["variables"] * 3 < f["variables"]


# ------------------------------------------------------------------ Hall cases (hand-checkable)

ROOMS_20_40 = [Room(id="S20", name="s", capacity=20, type=RoomType.TD),
               Room(id="S40", name="b", capacity=40, type=RoomType.TD)]


def test_two_big_groups_one_big_room_infeasible():
    # sizes 30, 30; rooms 20, 40 -> only one room fits 30 students: threshold k=30 gives 2 > 1
    groups = [Group(id="A", name="A", size=30), Group(id="B", name="B", size=30)]
    inst = tiny([td("CA", "T0", "A"), td("CB", "T1", "B")], ROOMS_20_40, groups)
    for mode in ("threshold", "full"):
        assert solve(inst, rooms=mode).status == "INFEASIBLE"


def test_small_and_big_group_share_slot():
    groups = [Group(id="A", name="A", size=15), Group(id="B", name="B", size=30)]
    inst = tiny([td("CA", "T0", "A"), td("CB", "T1", "B")], ROOMS_20_40, groups)
    res = solve(inst, rooms="threshold")
    assert res.feasible and check_solution(inst, res.solution) == []
    rooms = {a.course_id: a.room_id for a in res.solution.assignments}
    assert rooms == {"CA": "S20", "CB": "S40"}


def test_redundant_thresholds_are_dropped():
    # sizes 10 and 15 both fit every room -> one non-dominated threshold (k=10, 2 rooms)
    groups = [Group(id="A", name="A", size=10), Group(id="B", name="B", size=15),
              Group(id="C", name="C", size=12)]
    inst = tiny([td("CA", "T0", "A"), td("CB", "T1", "B"), td("CC", "T2", "C")], ROOMS_20_40, groups,
                slots=2)
    tm = TimetableModel(inst, rooms="threshold")
    assert [f for f in tm.constraints if f.startswith("room_capacity")] == ["room_capacity:TD:10"]


# ------------------------------------------------------------------ assumption guard (H1, H2)


class RoomWithUnavailability(Room):
    unavailable: list[int] = []


def test_room_unavailability_falls_back_to_full():
    rooms = [RoomWithUnavailability(id="S40", name="b", capacity=40, type=RoomType.TD, unavailable=[0])]
    inst = tiny([td("CA", "T0", "A")], rooms, [Group(id="A", name="A", size=10)], validate=False)
    assert any("(H2)" in r for r in threshold_violations(inst))
    with pytest.warns(RuntimeWarning, match="rooms='full'"):
        tm = TimetableModel(inst, rooms="threshold")
    assert tm.rooms_mode == "full"


def test_cross_type_rooms_fall_back_to_full(monkeypatch):
    rooms = [Room(id="S40", name="b", capacity=40, type=RoomType.TD),
             Room(id="L1", name="lab", capacity=40, type=RoomType.TP)]
    inst = tiny([td("CA", "T0", "A")], rooms, [Group(id="A", name="A", size=10)])
    # simulate a future rule letting TD courses use labs
    monkeypatch.setattr(Instance, "compatible_rooms", lambda self, c: list(self.rooms))
    assert any("(H1)" in r for r in threshold_violations(inst))
    with pytest.warns(RuntimeWarning):
        res = solve(inst, rooms="threshold")
    assert res.stats["rooms_mode"] == "full"


def test_generated_instances_satisfy_assumptions():
    for size in ("small", "medium", "large"):
        assert threshold_violations(generate(size, seed=42)) == []


def test_invalid_rooms_mode():
    with pytest.raises(ValueError):
        TimetableModel(generate("small"), rooms="nope")


# ------------------------------------------------------------------ phase 2: room assignment


def test_consecutive_tp_block_keeps_same_room():
    labs = [Room(id=f"L{i}", name=f"lab{i}", capacity=20, type=RoomType.TP) for i in range(3)]
    groups = [Group(id="A", name="A", size=15), Group(id="B", name="B", size=15)]
    courses = [td("TA", "T0", "A", RoomType.TP, sessions=2), td("TB", "T1", "B", RoomType.TP, sessions=2)]
    inst = tiny(courses, labs, groups, slots=2)
    res = assign_rooms(inst, {"TA": [0, 1], "TB": [0, 1]})
    assert res.tp_blocks == 2 and res.same_room_blocks == 2
    for cid in ("TA", "TB"):
        assert len({a.room_id for a in res.solution.assignments if a.course_id == cid}) == 1
    assert check_solution(inst, res.solution) == []


def test_room_stats_reported_in_threshold_mode():
    res = solve(generate("small", seed=42), rooms="threshold")
    s = res.stats
    assert s["room_time"] is not None and s["tp_blocks"] is not None
    assert 0 <= s["same_room_blocks"] <= s["tp_blocks"]
    full = solve(generate("small", seed=42), rooms="full")
    assert full.stats["room_time"] is None
