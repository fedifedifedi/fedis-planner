"""CP-SAT timetabling model: hard constraints.

Variables
  x[c, t]    = 1 if course c has a session at slot t (sessions of a course are interchangeable,
               numbered chronologically afterwards). Not created when the teacher is unavailable.

Room handling (`rooms` parameter)
  "threshold" (default) — slots only; rooms are covered by nested-capacity threshold constraints
               (exact under two assumptions, see planner/rooms.py) and assigned afterwards by
               rooms.assign_rooms. Falls back to "full" with a warning if an assumption is violated.
  "full"     — y[c, t, r] = 1 if that session takes place in room r (compatible rooms only; when a
               course has a single compatible room, y is x itself). Kept for agreement tests and
               benchmarks.

Every constraint is recorded under a family tag so later steps can extend the model
(objective, assumption literals for conflict explanation, replanning).
"""

from __future__ import annotations

import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from ortools.sat.python import cp_model

from planner.model import Assignment, Instance, RoomType, Solution
from planner.rooms import assign_rooms, threshold_violations

DEFAULT_TIME_LIMIT = 60.0
DEFAULT_WORKERS = 8

RoomsMode = Literal["threshold", "full"]


class TimetableModel:
    def __init__(self, instance: Instance, rooms: RoomsMode = "threshold") -> None:
        start = time.perf_counter()
        if rooms not in ("threshold", "full"):
            raise ValueError(f"rooms must be 'threshold' or 'full', got {rooms!r}")
        if rooms == "threshold":
            reasons = threshold_violations(instance)
            if reasons:
                warnings.warn("threshold decomposition not exact for this instance, using rooms='full': "
                              + "; ".join(reasons), RuntimeWarning, stacklevel=2)
                rooms = "full"
        self.instance = instance
        self.rooms_mode: RoomsMode = rooms
        self.model = cp_model.CpModel()
        self.x: dict[tuple[str, int], cp_model.IntVar] = {}
        self.y: dict[tuple[str, int, str], cp_model.IntVar] = {}
        self.constraints: dict[str, list[cp_model.Constraint]] = defaultdict(list)
        self._build_variables()
        self._add_hard_constraints()
        if rooms == "full":
            self._add_room_variables()
        else:
            self._add_room_thresholds()
        self.build_time = time.perf_counter() - start

    # ------------------------------------------------------------------ build

    def _build_variables(self) -> None:
        inst = self.instance
        for c in inst.courses:
            blocked = set(inst.teacher_by_id[c.teacher_id].unavailable)
            for t in range(inst.grid.num_slots):
                if t not in blocked:
                    self.x[c.id, t] = self.model.new_bool_var(f"x[{c.id},{t}]")

    def add(self, family: str, constraint: cp_model.Constraint) -> cp_model.Constraint:
        self.constraints[family].append(constraint)
        return constraint

    def course_slots(self, course_id: str) -> list[int]:
        return [t for t in range(self.instance.grid.num_slots) if (course_id, t) in self.x]

    def _add_hard_constraints(self) -> None:
        inst, m = self.instance, self.model
        n = inst.grid.num_slots

        for c in inst.courses:
            slots = self.course_slots(c.id)
            self.add(f"hours:{c.id}", m.add(sum(self.x[c.id, t] for t in slots) == c.sessions_per_week))
            for day_slots in inst.grid.slots_by_day:
                in_day = [self.x[c.id, t] for t in day_slots if (c.id, t) in self.x]
                if len(in_day) > c.max_sessions_per_day:
                    self.add(f"max_per_day:{c.id}", m.add(sum(in_day) <= c.max_sessions_per_day))

        by_teacher: dict[str, list[str]] = defaultdict(list)
        for c in inst.courses:
            by_teacher[c.teacher_id].append(c.id)
        for tid, cids in sorted(by_teacher.items()):
            for t in range(n):
                vars_ = [self.x[cid, t] for cid in cids if (cid, t) in self.x]
                if len(vars_) > 1:
                    self.add(f"teacher:{tid}", m.add_at_most_one(vars_))

        for chain in inst.student_chains:
            leaf = next(g for g in sorted(chain) if not inst.children[g])
            cids = [c.id for c in inst.courses if chain & set(c.group_ids)]
            for t in range(n):
                vars_ = [self.x[cid, t] for cid in cids if (cid, t) in self.x]
                if len(vars_) > 1:
                    self.add(f"students:{leaf}", m.add_at_most_one(vars_))

    def _add_room_variables(self) -> None:
        """rooms='full': explicit room variables y[c,t,r]."""
        inst, m = self.instance, self.model
        by_room_slot: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
        for c in inst.courses:
            rooms = [r.id for r in inst.compatible_rooms(c)]
            for t in self.course_slots(c.id):
                x = self.x[c.id, t]
                if len(rooms) == 1:
                    self.y[c.id, t, rooms[0]] = x
                    by_room_slot[rooms[0], t].append(x)
                    continue
                vars_ = []
                for r in rooms:
                    y = m.new_bool_var(f"y[{c.id},{t},{r}]")
                    self.y[c.id, t, r] = y
                    by_room_slot[r, t].append(y)
                    vars_.append(y)
                self.add(f"room_link:{c.id}", m.add(sum(vars_) == x))
        for (r, _t), vars_ in by_room_slot.items():
            if len(vars_) > 1:
                self.add(f"room:{r}", m.add_at_most_one(vars_))

    def _add_room_thresholds(self) -> None:
        """rooms='threshold': per slot, type and capacity threshold k,
        #sessions with >= k students <= #rooms with capacity >= k (exact under H1+H2, see rooms.py)."""
        inst, m = self.instance, self.model
        for rtype in RoomType:
            courses = [c for c in inst.courses if c.room_type == rtype]
            if not courses:
                continue
            capacities = sorted((r.capacity for r in inst.rooms if r.type == rtype), reverse=True)
            sizes = {c.id: inst.course_size(c) for c in courses}
            # keep only non-dominated thresholds: for k1 < k2 with the same room count, k1 implies k2
            thresholds: list[tuple[int, int]] = []
            for k in sorted(set(sizes.values())):
                cap = sum(1 for capa in capacities if capa >= k)
                if not thresholds or cap < thresholds[-1][1]:
                    thresholds.append((k, cap))
            for k, cap in thresholds:
                cids = [c.id for c in courses if sizes[c.id] >= k]
                for t in range(inst.grid.num_slots):
                    vars_ = [self.x[cid, t] for cid in cids if (cid, t) in self.x]
                    if len(vars_) > cap:
                        self.add(f"room_capacity:{rtype.value}:{k}", m.add(sum(vars_) <= cap))

    # ------------------------------------------------------------------ solve

    def stats(self) -> dict[str, int | str]:
        proto = self.model.proto
        return {
            "rooms_mode": self.rooms_mode,
            "x_vars": len(self.x),
            "y_vars": sum(1 for k, v in self.y.items() if v is not self.x.get(k[:2])),
            "variables": len(proto.variables),
            "constraints": len(proto.constraints),
        }

    def chosen_slots(self, solver: cp_model.CpSolver) -> dict[str, list[int]]:
        return {c.id: [t for t in self.course_slots(c.id) if solver.boolean_value(self.x[c.id, t])]
                for c in self.instance.courses}

    def extract_full(self, solver: cp_model.CpSolver) -> Solution:
        assignments = []
        for c in self.instance.courses:
            for session, t in enumerate(self.chosen_slots(solver)[c.id]):
                room = next(r.id for r in self.instance.compatible_rooms(c)
                            if (c.id, t, r.id) in self.y and solver.boolean_value(self.y[c.id, t, r.id]))
                assignments.append(Assignment(course_id=c.id, session=session, slot=t, room_id=room))
        return Solution(assignments=assignments)


@dataclass
class SolveResult:
    status: str  # exact CP-SAT status: OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN, MODEL_INVALID
    solution: Solution | None
    stats: dict[str, float | int | str | None] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.solution is not None


def run_solver(tm: TimetableModel, time_limit: float = DEFAULT_TIME_LIMIT,
               workers: int = DEFAULT_WORKERS, random_seed: int = 0) -> SolveResult:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = random_seed
    start = time.perf_counter()
    status = solver.solve(tm.model)
    solve_time = time.perf_counter() - start

    name = solver.status_name(status)
    solution = None
    room_stats: dict[str, float | int | None] = {"room_time": None, "tp_blocks": None, "same_room_blocks": None}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if tm.rooms_mode == "full":
            solution = tm.extract_full(solver)
        else:
            rooms = assign_rooms(tm.instance, tm.chosen_slots(solver), workers=workers, random_seed=random_seed)
            solution = rooms.solution
            room_stats = {"room_time": round(rooms.time, 3), "tp_blocks": rooms.tp_blocks,
                          "same_room_blocks": rooms.same_room_blocks}

    objective = bound = gap = None
    if solution is not None and tm.model.has_objective():
        objective, bound = solver.objective_value, solver.best_objective_bound
        gap = abs(objective - bound) / max(1.0, abs(objective))
    stats = {
        "status": name,
        **tm.stats(),
        "workers": workers,
        "random_seed": random_seed,
        "time_limit": time_limit,
        "build_time": round(tm.build_time, 3),
        "solve_time": round(solve_time, 3),
        **room_stats,
        "objective": objective,
        "best_bound": bound,
        "gap": gap,
    }
    return SolveResult(status=name, solution=solution, stats=stats)


def solve(instance: Instance, time_limit: float = DEFAULT_TIME_LIMIT, workers: int = DEFAULT_WORKERS,
          random_seed: int = 0, rooms: RoomsMode = "threshold") -> SolveResult:
    """Find a timetable satisfying every hard constraint (no objective yet)."""
    return run_solver(TimetableModel(instance, rooms=rooms), time_limit=time_limit, workers=workers,
                      random_seed=random_seed)
