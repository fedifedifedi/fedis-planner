"""Solver-independent check of a solution against every hard constraint."""

from __future__ import annotations

from collections import Counter, defaultdict

from planner.model import Instance, Solution


def check_solution(instance: Instance, solution: Solution) -> list[str]:
    """Return human-readable violations (empty list = valid timetable)."""
    inst, grid = instance, instance.grid
    errors: list[str] = []
    by_course = defaultdict(list)

    for a in solution.assignments:
        c = inst.course_by_id.get(a.course_id)
        room = inst.room_by_id.get(a.room_id)
        if c is None:
            errors.append(f"unknown course {a.course_id}")
            continue
        if room is None:
            errors.append(f"{a.course_id}: unknown room {a.room_id}")
            continue
        if not 0 <= a.slot < grid.num_slots:
            errors.append(f"{a.course_id}: slot {a.slot} outside grid")
            continue
        by_course[c.id].append(a)
        if room.type != c.room_type:
            errors.append(f"{c.id}: room {room.id} is {room.type.value}, needs {c.room_type.value}")
        if room.capacity < inst.course_size(c):
            errors.append(f"{c.id}: room {room.id} capacity {room.capacity} < {inst.course_size(c)} students")
        if a.slot in inst.teacher_by_id[c.teacher_id].unavailable:
            errors.append(f"{c.id}: teacher {c.teacher_id} unavailable at {grid.describe(a.slot)}")

    for c in inst.courses:
        items = by_course.get(c.id, [])
        if len(items) != c.sessions_per_week:
            errors.append(f"{c.id}: {len(items)} sessions scheduled, {c.sessions_per_week} required")
        if sorted(a.session for a in items) != list(range(len(items))):
            errors.append(f"{c.id}: session numbers must be 0..{len(items) - 1}")
        slots = Counter(a.slot for a in items)
        errors += [f"{c.id}: two sessions at {grid.describe(t)}" for t, k in slots.items() if k > 1]
        per_day = Counter(grid.slots[a.slot].day for a in items)
        errors += [f"{c.id}: {k} sessions on {grid.days[d].name} (max {c.max_sessions_per_day})"
                   for d, k in per_day.items() if k > c.max_sessions_per_day]

    def clashes(kind: str, key_of) -> None:
        seen: dict[tuple, str] = {}
        for a in solution.assignments:
            if a.course_id not in inst.course_by_id or a.room_id not in inst.room_by_id:
                continue
            for key in key_of(inst.course_by_id[a.course_id], a):
                k = (key, a.slot)
                if k in seen and seen[k] != a.course_id:
                    errors.append(f"{kind} {key} double-booked at {grid.describe(a.slot)}: "
                                  f"{seen[k]} and {a.course_id}")
                seen.setdefault(k, a.course_id)

    clashes("teacher", lambda c, a: [c.teacher_id])
    clashes("room", lambda c, a: [a.room_id])
    chain_names = [(min(ch, key=lambda g: (len(inst.children[g]) > 0, g)), ch) for ch in inst.student_chains]
    clashes("students of", lambda c, a: [leaf for leaf, ch in chain_names if ch & set(c.group_ids)])
    return errors
