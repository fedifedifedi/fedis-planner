from datetime import date

from planner.export_ics import _fold, related_course_ids, to_ics
from planner.generator import generate
from planner.greedy import greedy

MONDAY = date(2026, 10, 26)


def test_related_courses_of_a_group_include_ancestors_and_descendants():
    inst = generate("small", seed=42)
    sub = related_course_ids(inst, group="L1-G1a")
    grp = related_course_ids(inst, group="L1-G1")
    assert {c.id for c in inst.courses if c.group_ids == ["L1"]} <= sub  # promo CM
    assert not any("G1b" in cid for cid in sub)  # sibling subgroup excluded
    assert any("TP-G1a" in cid for cid in grp) and any("TP-G1b" in cid for cid in grp)


def test_ics_structure_and_dates():
    inst = generate("small", seed=42)
    sol = greedy(inst).solution
    ics = to_ics(inst, sol, MONDAY)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == len(sol.assignments) == ics.count("END:VEVENT")
    first = min(sol.assignments, key=lambda a: a.slot)
    ref = inst.grid.slots[first.slot]
    expected_day = f"202610{26 + ref.day:02d}"
    assert f"DTSTART:{expected_day}T{ref.slot.start.replace(':', '')}00" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_ics_filters():
    inst = generate("small", seed=42)
    sol = greedy(inst).solution
    teacher = inst.teachers[0].id
    n_teacher = sum(1 for a in sol.assignments if inst.course_by_id[a.course_id].teacher_id == teacher)
    assert to_ics(inst, sol, MONDAY, teacher=teacher).count("BEGIN:VEVENT") == n_teacher
    room = sol.assignments[0].room_id
    n_room = sum(1 for a in sol.assignments if a.room_id == room)
    assert to_ics(inst, sol, MONDAY, room=room).count("BEGIN:VEVENT") == n_room


def test_recurrence_and_escaping():
    inst = generate("small", seed=42)
    sol = greedy(inst).solution
    assert "RRULE:FREQ=WEEKLY;COUNT=12" in to_ics(inst, sol, MONDAY, weeks=12)
    data = inst.model_dump()
    data["courses"][0]["subject"] = "Maths; algèbre, suite"
    tricky = type(inst).model_validate(data)
    unfolded = to_ics(tricky, sol, MONDAY).replace("\r\n ", "")
    assert "SUMMARY:Maths\\; algèbre\\, suite (CM)" in unfolded


def test_fold_long_lines():
    folded = _fold("DESCRIPTION:" + "é" * 80)
    parts = folded.split("\r\n")
    assert len(parts) > 1 and all(len(p.encode()) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
