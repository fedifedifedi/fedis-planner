"""Room handling for the nested-capacity threshold decomposition.

Phase 1 (solver.py, rooms="threshold") decides slots only. For each slot t, room type T and
capacity threshold k it enforces

    #{sessions of type T at t with >= k students} <= #{rooms of type T with capacity >= k}

Why this is exact — two assumptions (checked by `threshold_violations`):
  (H1) a course only uses rooms of its exact type (no TD course in a lab, ...);
  (H2) no room has its own unavailability (a room is free at every slot).
Under (H1)+(H2), at a fixed slot and type, the compatible-room sets {r : cap(r) >= size(c)} are
nested (totally ordered by inclusion). By Hall's theorem a distinct room exists for every
session iff every subset S of sessions has |S| <= |union of compatible sets|; with nested sets
the union is the set of the smallest session of S, so it suffices to check the subsets
"all sessions with >= k students", i.e. the threshold constraints above. Feasible slot
assignments and the slot-level optimum are therefore unchanged.
If (H1) or (H2) is violated, sets are no longer nested (or differ per slot) and the threshold
condition becomes necessary only: the solver falls back to rooms="full".

Phase 2 (`assign_rooms`) gives each scheduled session a room with a small CP-SAT model (always
feasible by Hall) and maximises the number of consecutive TP blocks kept in the same room.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from planner.model import Assignment, Instance, Solution


def threshold_violations(instance: Instance) -> list[str]:
    """Reasons why the threshold decomposition would not be exact (empty = safe)."""
    reasons: list[str] = []
    for room in instance.rooms:
        if getattr(room, "unavailable", None):  # (H2) — the model has no such field today
            reasons.append(f"room {room.id} has its own unavailability (H2)")
    for c in instance.courses:
        other = [r.id for r in instance.compatible_rooms(c) if r.type != c.room_type]
        if other:  # (H1)
            reasons.append(f"course {c.id} may use rooms of another type: {other} (H1)")
    return reasons


def tp_blocks(instance: Instance, slots_by_course: dict[str, list[int]]) -> list[tuple[str, int, int]]:
    """Consecutive (same day, adjacent position) session pairs of lab courses."""
    grid = instance.grid
    blocks = []
    for c in instance.courses:
        if not c.is_lab:
            continue
        slots = sorted(slots_by_course.get(c.id, []))
        for a, b in zip(slots, slots[1:]):
            ra, rb = grid.slots[a], grid.slots[b]
            if ra.day == rb.day and rb.position == ra.position + 1:
                blocks.append((c.id, a, b))
    return blocks


@dataclass
class RoomAssignmentResult:
    solution: Solution
    tp_blocks: int
    same_room_blocks: int
    time: float


def assign_rooms(instance: Instance, slots_by_course: dict[str, list[int]],
                 time_limit: float = 10.0, workers: int = 8, random_seed: int = 0) -> RoomAssignmentResult:
    """Phase 2: rooms for fixed slots, maximising consecutive TP blocks kept in the same room."""
    start = time.perf_counter()
    m = cp_model.CpModel()
    z: dict[tuple[str, int, str], cp_model.IntVar] = {}
    by_room_slot: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
    for c in instance.courses:
        rooms = [r.id for r in instance.compatible_rooms(c)]
        for t in slots_by_course.get(c.id, []):
            vars_ = []
            for r in rooms:
                v = m.new_bool_var(f"z[{c.id},{t},{r}]")
                z[c.id, t, r] = v
                by_room_slot[r, t].append(v)
                vars_.append(v)
            m.add_exactly_one(vars_)
    for vars_ in by_room_slot.values():
        if len(vars_) > 1:
            m.add_at_most_one(vars_)

    blocks = tp_blocks(instance, slots_by_course)
    same = []
    for cid, a, b in blocks:
        for r in [r.id for r in instance.compatible_rooms(instance.course_by_id[cid])]:
            s = m.new_bool_var(f"same[{cid},{a},{r}]")
            m.add_implication(s, z[cid, a, r])
            m.add_implication(s, z[cid, b, r])
            same.append(s)
    if same:
        m.maximize(sum(same))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = random_seed
    status = solver.solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # cannot happen when phase 1 enforced the threshold constraints under (H1)+(H2)
        raise RuntimeError(f"room assignment failed: {solver.status_name(status)}")

    assignments = []
    for c in instance.courses:
        for session, t in enumerate(sorted(slots_by_course.get(c.id, []))):
            room = next(r.id for r in instance.compatible_rooms(c) if solver.boolean_value(z[c.id, t, r.id]))
            assignments.append(Assignment(course_id=c.id, session=session, slot=t, room_id=room))
    kept = sum(1 for s in same if solver.boolean_value(s))
    return RoomAssignmentResult(solution=Solution(assignments=assignments), tp_blocks=len(blocks),
                                same_room_blocks=kept, time=time.perf_counter() - start)
