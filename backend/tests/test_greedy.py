import pytest

from planner.generator import generate
from planner.greedy import greedy
from planner.model import Course, Day, GridConfig, Group, Instance, Room, RoomType, Teacher, TimeSlot
from planner.scoring import score
from planner.validate import check_solution


def day(name, n, late_last=False) -> Day:
    slots = []
    for i in range(n):
        s = 8 * 60 + 100 * i
        slots.append(TimeSlot(start=f"{s // 60:02d}:{s % 60:02d}", end=f"{(s + 90) // 60:02d}:{(s + 90) % 60:02d}",
                              late=late_last and i == n - 1))
    return Day(name=name, slots=slots)


def make(courses, days, build=Instance) -> Instance:
    return build(grid=GridConfig(days=days), teachers=[Teacher(id="T1", name="a"), Teacher(id="T2", name="b")],
                 rooms=[Room(id="R1", name="r", capacity=40, type=RoomType.TD),
                        Room(id="L1", name="l", capacity=40, type=RoomType.TP)],
                 groups=[Group(id="G", name="G", size=20), Group(id="H", name="H", size=20)], courses=courses)


def c(cid, teacher="T1", group="G", rtype=RoomType.TD, sessions=1) -> Course:
    return Course(id=cid, subject=cid, teacher_id=teacher, group_ids=[group], room_type=rtype,
                  sessions_per_week=sessions)


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_generated_instances_fully_placed_without_violation(size):
    inst = generate(size, seed=42)
    res = greedy(inst)
    assert res.unplaced == []
    assert check_solution(inst, res.solution) == []


def test_deterministic():
    inst = generate("medium", seed=1)
    assert greedy(inst).solution == greedy(inst).solution


def test_avoids_late_slot():
    inst = make([c("A")], [day("D", 2, late_last=True)])
    assert [a.slot for a in greedy(inst).solution.assignments] == [0]


def test_lab_sessions_made_consecutive():
    inst = make([c("L", rtype=RoomType.TP, sessions=2)], [day("D1", 3), day("D2", 3)])
    slots = sorted(a.slot for a in greedy(inst).solution.assignments)
    assert (slots[0], slots[1]) in inst.grid.consecutive_pairs


def test_respects_teacher_and_room_conflicts():
    # one room, one slot per day, two days: A and B (different teachers/groups) must use different days
    inst = make([c("A"), c("B", teacher="T2", group="H")], [day("D1", 1), day("D2", 1)])
    res = greedy(inst)
    assert check_solution(inst, res.solution) == [] and res.unplaced == []


def test_reports_unplaced_sessions():
    # same teacher, a single slot: the second course cannot be placed (no backtracking needed to see it)
    inst = make([c("A"), c("B", group="H")], [day("D", 1)], build=Instance.model_construct)
    res = greedy(inst)
    assert len(res.unplaced) == 1
    assert any("0 sessions scheduled" in e for e in check_solution(inst, res.solution))


def test_scored_with_shared_function():
    inst = generate("small", seed=42)
    res = greedy(inst)
    s = score(inst, res.solution)
    assert s.total == sum(getattr(s.weights, k) * v for k, v in s.breakdown.items())
