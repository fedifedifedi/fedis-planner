import pytest

from planner.explain import ASSUMPTION_NOTE, _check, explain, precheck
from planner.generator import generate, make_infeasible
from planner.model import Course, Day, GridConfig, Group, Instance, Room, RoomType, Teacher, TimeSlot
from planner.solver import TimetableModel


def grid(slots: int, days: int = 1) -> GridConfig:
    times = [TimeSlot(start=f"{8 + 2 * i:02d}:00", end=f"{9 + 2 * i:02d}:30") for i in range(slots)]
    return GridConfig(days=[Day(name=f"D{d}", slots=times) for d in range(days)])


def course(cid, teacher, group, sessions=1, **kw):
    return Course(id=cid, subject=cid, teacher_id=teacher, group_ids=[group], room_type=RoomType.TD,
                  sessions_per_week=sessions, **kw)


def raw(courses, g, groups=None) -> Instance:
    """Skip model validation (its volume checks would already reject these cases)."""
    return Instance.model_construct(
        name="raw", grid=g, teachers=[Teacher(id="T1", name="Alice Martin"), Teacher(id="T2", name="Bob Roux")],
        rooms=[Room(id="R1", name="r1", capacity=40, type=RoomType.TD),
               Room(id="R2", name="r2", capacity=40, type=RoomType.TD)],
        groups=groups or [Group(id="G1", name="G1", size=20), Group(id="G2", name="G2", size=20)],
        courses=courses)


def families(expl) -> set[str]:
    return {f"{c.family}:{c.entity}" for c in expl.core}


def assert_minimal(instance, fams: set[str]):
    """The set is infeasible, and dropping any single element makes it feasible."""
    tm = TimetableModel(instance, explain=True)
    assert _check(tm, sorted(fams), 30)[0] == "INFEASIBLE"
    for f in fams:
        status, _ = _check(tm, sorted(fams - {f}), 30)
        assert status in ("OPTIMAL", "FEASIBLE"), f"{f} is not needed"


# ------------------------------------------------------------------ hand-checkable cases


def test_teacher_collision():
    inst = raw([course("A", "T1", "G1"), course("B", "T1", "G2")], grid(1))
    e = explain(inst)
    assert not e.feasible and e.minimal
    assert families(e) == {"teacher:T1"}
    assert "Alice Martin ne peut donner qu'un cours à la fois" in e.core[0].message


def test_parent_subgroup_conflict():
    groups = [Group(id="G1", name="G1", size=30), Group(id="G1a", name="G1a", size=15, parent="G1")]
    inst = raw([course("P", "T1", "G1"), course("S", "T2", "G1a")], grid(1), groups=groups)
    e = explain(inst)
    assert families(e) == {"students:G1a"}
    assert "(avec G1)" in e.core[0].message


def test_max_per_day_conflict():
    inst = raw([course("A", "T1", "G1", sessions=2)], grid(2))  # max 1/day, a single day
    e = explain(inst)
    assert families(e) == {"max_per_day:A"}


def test_feasible_instance_has_no_conflict():
    e = explain(generate("small", seed=42))
    assert e.feasible and e.core == [] and e.prechecks == []


# ------------------------------------------------------------------ generated infeasible variants


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_teacher_availability_minimal_set(size):
    inst = make_infeasible(generate(size, seed=42), "teacher_availability")
    e = explain(inst)
    assert not e.feasible and e.minimal and e.prechecks == []  # invisible to counting
    fams = families(e)
    assert {"availability:V001", "availability:V002"} < fams and len(fams) == 3
    (students,) = fams - {"availability:V001", "availability:V002"}
    leaf = students.split(":")[1]
    chain = {leaf, *inst.ancestors(leaf)}
    cm = next(c for c in inst.courses if c.teacher_id == "V001")
    td = next(c for c in inst.courses if c.teacher_id == "V002")
    assert set(cm.group_ids) <= chain and set(td.group_ids) <= chain
    assert ASSUMPTION_NOTE in e.summary and "tous les cours doivent avoir leurs heures" in e.summary
    assert any("Hélène Vacataire-Morin n'est disponible que sur" in c.message for c in e.core)
    if size == "small":
        assert_minimal(inst, fams)


def test_room_shortage_precheck_and_core():
    inst = make_infeasible(generate("medium", seed=42), "room_shortage")
    pre = precheck(inst)
    assert pre and pre[0].details["type"] == "TP"
    assert "labo(s)" in pre[0].message
    e = explain(inst)
    assert not e.feasible and e.prechecks
    assert any(c.family == "room_capacity" and c.entity.startswith("TP:") for c in e.core)


def test_room_shortage_core_is_minimal():
    inst = make_infeasible(generate("small", seed=42), "room_shortage")
    e = explain(inst)
    assert e.minimal
    assert_minimal(inst, families(e))


def test_explain_mode_keeps_hours_as_background():
    tm = TimetableModel(generate("small", seed=42), explain=True)
    kinds = {f.split(":")[0] for f in tm.literals}
    assert "hours" not in kinds and {"teacher", "students", "availability"} <= kinds
