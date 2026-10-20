"""Greedy baseline: place sessions one by one, most constrained course first, no backtracking.

For each session the feasible slots are those where the teacher is available and free, no student
chain of the course is busy, the daily cap is respected and a compatible room is free (best fit:
smallest sufficient room). Among them, the slot with the lowest *local* increase of the weighted
score is chosen (late slot, gaps and day loads of the affected chains/teacher, TP adjacency).
Sessions that cannot be placed are reported as unplaced.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from planner.model import Assignment, Instance, Solution
from planner.scoring import Weights, chain_courses


@dataclass
class GreedyResult:
    solution: Solution
    unplaced: list[tuple[str, int]] = field(default_factory=list)  # (course_id, session)
    time: float = 0.0


def _gaps(positions: list[int]) -> int:
    return (positions[-1] - positions[0] + 1 - len(positions)) if len(positions) >= 2 else 0


def greedy(instance: Instance, weights: Weights | None = None) -> GreedyResult:
    start = time.perf_counter()
    w = weights or Weights()
    inst, grid = instance, instance.grid
    n = grid.num_slots
    late = set(grid.late_slots)
    day_of = [ref.day for ref in grid.slots]
    pos_of = [ref.position for ref in grid.slots]

    chains_of_course: dict[str, list[str]] = defaultdict(list)
    for leaf, cids in chain_courses(inst).items():
        for cid in cids:
            chains_of_course[cid].append(leaf)

    teacher_busy: dict[str, set[int]] = defaultdict(set)
    chain_busy: dict[str, set[int]] = defaultdict(set)
    room_busy: dict[str, set[int]] = defaultdict(set)
    course_slots: dict[str, list[int]] = defaultdict(list)
    room_at: dict[tuple[str, int], str] = {}

    def options(c) -> list[int]:
        blocked = set(inst.teacher_by_id[c.teacher_id].unavailable)
        return [t for t in range(n) if t not in blocked]

    rooms_of = {c.id: sorted(inst.compatible_rooms(c), key=lambda r: (r.capacity, r.id)) for c in inst.courses}
    # most constrained first: fewest candidate (slot, room) pairs per session, then biggest courses
    order = sorted(inst.courses, key=lambda c: (len(options(c)) * len(rooms_of[c.id]) / c.sessions_per_week,
                                                -inst.course_size(c), c.id))

    def day_positions(busy: set[int], d: int, extra: int | None = None) -> list[int]:
        ps = sorted(pos_of[t] for t in busy if day_of[t] == d)
        if extra is not None:
            ps = sorted(ps + [pos_of[extra]])
        return ps

    def local_cost(c, t: int) -> float:
        d = day_of[t]
        cost = w.late * (t in late)
        tb = teacher_busy[c.teacher_id]
        cost += w.teacher_gaps * (_gaps(day_positions(tb, d, t)) - _gaps(day_positions(tb, d)))
        for leaf in chains_of_course[c.id]:
            cb = chain_busy[leaf]
            before, after = day_positions(cb, d), day_positions(cb, d, t)
            cost += w.student_gaps * (_gaps(after) - _gaps(before))
            cost += w.single_session_day * ((len(after) == 1) - (len(before) == 1))
            if d in grid.full_days:
                loads = [sum(1 for s in cb if day_of[s] == fd) for fd in grid.full_days]
                new = [load + (fd == d) for load, fd in zip(loads, grid.full_days)]
                cost += w.imbalance * ((max(new) - min(new)) - (max(loads) - min(loads)))
        if c.is_lab and any((min(s, t), max(s, t)) in grid.consecutive_pairs for s in course_slots[c.id]):
            cost -= w.tp_split
        return cost

    assignments: list[Assignment] = []
    unplaced: list[tuple[str, int]] = []
    for c in order:
        chains = chains_of_course[c.id]
        for session in range(c.sessions_per_week):
            best = None
            for t in options(c):
                if t in teacher_busy[c.teacher_id] or any(t in chain_busy[g] for g in chains):
                    continue
                if t in course_slots[c.id]:
                    continue
                if sum(1 for s in course_slots[c.id] if day_of[s] == day_of[t]) >= c.max_sessions_per_day:
                    continue
                room = next((r for r in rooms_of[c.id] if t not in room_busy[r.id]), None)
                if room is None:
                    continue
                key = (local_cost(c, t), t)
                if best is None or key < best[0]:
                    best = (key, t, room)
            if best is None:
                unplaced.append((c.id, session))
                continue
            _, t, room = best
            teacher_busy[c.teacher_id].add(t)
            for g in chains:
                chain_busy[g].add(t)
            room_busy[room.id].add(t)
            course_slots[c.id].append(t)
            room_at[c.id, t] = room.id

    for c in inst.courses:  # chronological session numbering, like the solver
        for session, t in enumerate(sorted(course_slots[c.id])):
            assignments.append(Assignment(course_id=c.id, session=session, slot=t, room_id=room_at[c.id, t]))
    return GreedyResult(solution=Solution(assignments=assignments), unplaced=unplaced,
                        time=time.perf_counter() - start)
