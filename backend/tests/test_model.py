import pytest
from pydantic import ValidationError

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


def make_instance(**overrides) -> Instance:
    data = dict(
        name="tiny",
        teachers=[Teacher(id="T1", name="Alice"), Teacher(id="T2", name="Bob")],
        rooms=[
            Room(id="A1", name="Amphi", capacity=100, type=RoomType.CM),
            Room(id="S1", name="Salle TD", capacity=40, type=RoomType.TD),
            Room(id="L1", name="Labo", capacity=20, type=RoomType.TP),
        ],
        groups=[
            Group(id="G1", name="G1", size=30),
            Group(id="G1a", name="G1a", size=15, parent="G1"),
            Group(id="G1b", name="G1b", size=15, parent="G1"),
            Group(id="G2", name="G2", size=30),
        ],
        courses=[
            Course(id="C1", subject="Maths", teacher_id="T1", group_ids=["G1", "G2"], room_type=RoomType.CM,
                   sessions_per_week=2),
            Course(id="C2", subject="Algo TP", teacher_id="T2", group_ids=["G1a"], room_type=RoomType.TP,
                   sessions_per_week=2),
        ],
    )
    data.update(overrides)
    return Instance(**data)


# ------------------------------------------------------------------ grid


def test_default_grid_layout():
    grid = GridConfig()
    assert [d.name for d in grid.days] == ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
    assert grid.num_slots == 5 * 5 + 3
    assert [s.label for s in grid.days[0].slots] == [
        "08:30-10:00", "10:10-11:40", "11:50-13:20", "14:00-15:30", "15:40-17:10",
    ]
    assert len(grid.days[5].slots) == 3


def test_default_late_slots_only_last_weekday_slot():
    grid = GridConfig()
    late = grid.late_slots
    assert len(late) == 5  # none on Saturday
    assert all(grid.slots[t].slot.label == "15:40-17:10" for t in late)
    assert all(grid.slots[t].day_name != "Samedi" for t in late)


def test_global_slot_indices():
    grid = GridConfig()
    assert grid.slots_by_day[0] == [0, 1, 2, 3, 4]
    assert grid.slots_by_day[5] == [25, 26, 27]
    assert grid.describe(5) == "Mardi 08:30-10:00"


def test_custom_grid():
    grid = GridConfig(days=[
        Day(name="Mon", slots=[TimeSlot(start="09:00", end="11:00"), TimeSlot(start="13:00", end="15:00", late=True)]),
        Day(name="Tue", slots=[TimeSlot(start="09:00", end="11:00")]),
    ])
    assert grid.num_slots == 3
    assert grid.late_slots == [1]


def test_grid_from_json_config():
    grid = GridConfig.model_validate({"days": [{"name": "D", "slots": [{"start": "08:00", "end": "09:30"}]}]})
    assert grid.num_slots == 1 and grid.late_slots == []


@pytest.mark.parametrize("start,end", [("8:30", "10:00"), ("10:00", "09:00"), ("25:00", "26:00")])
def test_invalid_slot(start, end):
    with pytest.raises(ValidationError):
        TimeSlot(start=start, end=end)


def test_overlapping_slots_rejected():
    with pytest.raises(ValidationError, match="overlap"):
        Day(name="X", slots=[TimeSlot(start="08:00", end="10:00"), TimeSlot(start="09:30", end="11:00")])


# ------------------------------------------------------------------ course defaults


def test_max_sessions_per_day_defaults():
    td = Course(id="c", subject="s", teacher_id="t", group_ids=["g"], room_type=RoomType.TD, sessions_per_week=1)
    tp = Course(id="c", subject="s", teacher_id="t", group_ids=["g"], room_type=RoomType.TP, sessions_per_week=1)
    explicit = Course(id="c", subject="s", teacher_id="t", group_ids=["g"], room_type=RoomType.TP,
                      sessions_per_week=1, max_sessions_per_day=3)
    assert td.max_sessions_per_day == 1
    assert tp.max_sessions_per_day == 2 and tp.is_lab
    assert explicit.max_sessions_per_day == 3


def test_sessions_must_fit_with_daily_cap():
    grid = GridConfig(days=[Day(name="D1", slots=[TimeSlot(start="08:00", end="09:00"),
                                                  TimeSlot(start="09:00", end="10:00")])] * 2)
    course = Course(id="C", subject="s", teacher_id="T1", group_ids=["G2"], room_type=RoomType.TD,
                    sessions_per_week=3)  # max 1/day * 2 days = 2
    with pytest.raises(ValidationError, match="cannot fit"):
        make_instance(grid=grid, courses=[course])


# ------------------------------------------------------------------ groups / subgroups


def test_valid_instance_and_lookups():
    inst = make_instance()
    assert inst.ancestors("G1a") == ["G1"]
    assert sorted(inst.children["G1"]) == ["G1a", "G1b"]
    assert inst.course_size(inst.course_by_id["C1"]) == 60
    assert [r.id for r in inst.compatible_rooms(inst.course_by_id["C1"])] == ["A1"]


def test_student_chains_link_parent_and_subgroups():
    chains = set(make_instance().student_chains)
    assert chains == {frozenset({"G1a", "G1"}), frozenset({"G1b", "G1"}), frozenset({"G2"})}


def test_multi_level_chain():
    groups = [
        Group(id="P", name="Promo", size=60),
        Group(id="G1", name="G1", size=30, parent="P"),
        Group(id="G1a", name="G1a", size=15, parent="G1"),
    ]
    inst = make_instance(groups=groups, courses=[])
    assert inst.ancestors("G1a") == ["G1", "P"]
    assert inst.student_chains == [frozenset({"G1a", "G1", "P"})]


def test_group_cycle_rejected():
    groups = [Group(id="A", name="A", size=10, parent="B"), Group(id="B", name="B", size=10, parent="A")]
    with pytest.raises(ValidationError, match="cycle"):
        make_instance(groups=groups, courses=[])


def test_self_parent_rejected():
    with pytest.raises(ValidationError, match="cycle"):
        make_instance(groups=[Group(id="A", name="A", size=10, parent="A")], courses=[])


def test_subgroup_larger_than_parent_rejected():
    groups = [Group(id="G1", name="G1", size=20), Group(id="G1a", name="G1a", size=25, parent="G1")]
    with pytest.raises(ValidationError, match="exceeds parent"):
        make_instance(groups=groups, courses=[])


def test_unknown_parent_rejected():
    with pytest.raises(ValidationError, match="unknown parent"):
        make_instance(groups=[Group(id="G1a", name="G1a", size=10, parent="G9")], courses=[])


def test_course_with_group_and_its_subgroup_rejected():
    course = Course(id="C", subject="s", teacher_id="T1", group_ids=["G1", "G1a"], room_type=RoomType.CM,
                    sessions_per_week=1)
    with pytest.raises(ValidationError, match="ancestor"):
        make_instance(courses=[course])


def test_chain_load_counts_parent_courses():
    # G1a students follow G1's 15 sessions + their own 14 = 29 > 28 slots
    courses = [
        Course(id="P", subject="s", teacher_id="T1", group_ids=["G1"], room_type=RoomType.TD,
               sessions_per_week=6, max_sessions_per_day=5),
        Course(id="Q", subject="s", teacher_id="T2", group_ids=["G1"], room_type=RoomType.TD,
               sessions_per_week=9, max_sessions_per_day=5),
        Course(id="S", subject="s", teacher_id="T2", group_ids=["G1a"], room_type=RoomType.TP,
               sessions_per_week=14, max_sessions_per_day=5),
    ]
    with pytest.raises(ValidationError, match="G1a"):
        make_instance(courses=courses)


# ------------------------------------------------------------------ references / loads


def test_duplicate_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate teacher"):
        make_instance(teachers=[Teacher(id="T1", name="a"), Teacher(id="T1", name="b"), Teacher(id="T2", name="c")])


def test_unknown_teacher_rejected():
    course = Course(id="C", subject="s", teacher_id="T9", group_ids=["G2"], room_type=RoomType.TD,
                    sessions_per_week=1)
    with pytest.raises(ValidationError, match="unknown teacher"):
        make_instance(courses=[course])


def test_no_compatible_room_rejected():
    course = Course(id="C", subject="s", teacher_id="T1", group_ids=["G1"], room_type=RoomType.TP,
                    sessions_per_week=1)  # 30 students, lab capacity 20
    with pytest.raises(ValidationError, match="no TP room"):
        make_instance(courses=[course])


def test_unavailable_slot_out_of_range():
    with pytest.raises(ValidationError, match="outside grid"):
        make_instance(teachers=[Teacher(id="T1", name="a", unavailable=[99]), Teacher(id="T2", name="b")])


def test_teacher_overload_rejected():
    teachers = [Teacher(id="T1", name="a", unavailable=list(range(27))), Teacher(id="T2", name="b")]
    with pytest.raises(ValidationError, match="only 1 available"):
        make_instance(teachers=teachers)


# ------------------------------------------------------------------ persistence


def test_instance_json_roundtrip(tmp_path):
    inst = make_instance()
    path = tmp_path / "inst.json"
    inst.save(path)
    loaded = Instance.load(path)
    assert loaded == inst
    assert loaded.student_chains == inst.student_chains


def test_solution_json_roundtrip(tmp_path):
    sol = Solution(assignments=[Assignment(course_id="C1", session=0, slot=3, room_id="A1")])
    path = tmp_path / "sol.json"
    sol.save(path)
    assert Solution.load(path) == sol
