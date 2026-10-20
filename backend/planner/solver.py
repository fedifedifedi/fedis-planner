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
from planner.scoring import CRITERIA, Weights, chain_courses, score, teacher_courses

DEFAULT_TIME_LIMIT = 60.0
DEFAULT_WORKERS = 8

RoomsMode = Literal["threshold", "full"]


# Families that can be switched off by an assumption literal in explain mode. "hours" (every course gets
# its sessions) and "room_link" stay always enforced: they are the background of every explanation.
EXPLAINABLE = frozenset({"availability", "teacher", "students", "room_capacity", "max_per_day", "room", "past"})


class TimetableModel:
    def __init__(self, instance: Instance, rooms: RoomsMode = "threshold", explain: bool = False) -> None:
        """explain=True: teacher unavailability becomes constraints (x == 0) instead of missing variables,
        and every EXPLAINABLE family is enforced by one assumption literal (see planner/explain.py)."""
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
        self.explain = explain
        self.literals: dict[str, cp_model.IntVar] = {}
        self.model = cp_model.CpModel()
        self.x: dict[tuple[str, int], cp_model.IntVar] = {}
        self.y: dict[tuple[str, int, str], cp_model.IntVar] = {}
        self.constraints: dict[str, list[cp_model.Constraint]] = defaultdict(list)
        self.terms: dict[str, cp_model.LinearExprT] = {}
        self.weights: Weights | None = None
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
                if t not in blocked or self.explain:
                    self.x[c.id, t] = self.model.new_bool_var(f"x[{c.id},{t}]")
                if t in blocked and self.explain:
                    self.add(f"availability:{c.teacher_id}", self.model.add(self.x[c.id, t] == 0))

    def add(self, family: str, constraint: cp_model.Constraint) -> cp_model.Constraint:
        self.constraints[family].append(constraint)
        if self.explain and family.split(":")[0] in EXPLAINABLE:
            if family not in self.literals:
                self.literals[family] = self.model.new_bool_var(f"assume[{family}]")
            constraint.only_enforce_if(self.literals[family])
        return constraint

    def _at_most_one(self, family: str, vars_: list[cp_model.IntVar]) -> None:
        # enforcement literals are only guaranteed on linear constraints: use sum <= 1 in explain mode
        ct = self.model.add(sum(vars_) <= 1) if self.explain else self.model.add_at_most_one(vars_)
        self.add(family, ct)

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
                    self._at_most_one(f"teacher:{tid}", vars_)

        for chain in inst.student_chains:
            leaf = next(g for g in sorted(chain) if not inst.children[g])
            cids = [c.id for c in inst.courses if chain & set(c.group_ids)]
            for t in range(n):
                vars_ = [self.x[cid, t] for cid in cids if (cid, t) in self.x]
                if len(vars_) > 1:
                    self._at_most_one(f"students:{leaf}", vars_)

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
                self._at_most_one(f"room:{r}", vars_)

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
                family = f"room_capacity:{rtype.value}:{k}"
                for t in range(inst.grid.num_slots):
                    vars_ = [self.x[cid, t] for cid in cids if (cid, t) in self.x]
                    if len(vars_) > cap:
                        self.add(family, m.add(sum(vars_) <= cap))
                # explain mode only — implied weekly count: hours are always enforced, so the weekly number
                # of sessions is the constant D. If D > cap x slots the family contradicts itself; stating it
                # as an always-false constraint lets presolve reject the literal at once (single-worker
                # search needed for cores did not prove it: medium instance UNKNOWN after 20 s).
                demand = sum(inst.course_by_id[cid].sessions_per_week for cid in cids)
                if self.explain and demand > cap * inst.grid.num_slots:
                    self.add(family, m.add_bool_or([m.new_constant(0)]))

    def freeze_before(self, solution: Solution, announced_at: int) -> None:
        """Slots before `announced_at` are in the past: keep exactly the sessions held there, nothing else."""
        held = {(a.course_id, a.slot) for a in solution.assignments if a.slot < announced_at}
        missing = [k for k in held if k not in self.x]
        if missing:
            raise ValueError(f"past sessions on unavailable slots (invalid previous timetable): {missing}")
        for (cid, t), x in self.x.items():
            if t < announced_at:
                self.add("past", self.model.add(x == int((cid, t) in held)))

    # ------------------------------------------------------------------ objective

    def _occ(self, course_ids: list[str], t: int) -> list[cp_model.IntVar]:
        return [self.x[cid, t] for cid in course_ids if (cid, t) in self.x]

    def _gap_vars(self, course_ids: list[str]) -> list[cp_model.IntVar]:
        """Gap indicators of one entity (chain or teacher). occ(t) = sum of x, <= 1 by hard constraints.
        pre/post are only bounded from below: minimisation makes them exact ORs."""
        m, gaps = self.model, []
        for day_slots in self.instance.grid.slots_by_day:
            occ = [sum(v) if (v := self._occ(course_ids, t)) else 0 for t in day_slots]
            possible = [i for i, t in enumerate(day_slots) if self._occ(course_ids, t)]
            if len(possible) < 2:
                continue
            k = len(day_slots)
            pre = [m.new_bool_var("") for _ in range(k)]
            post = [m.new_bool_var("") for _ in range(k)]
            for i in range(k):
                if i in possible:
                    m.add(pre[i] >= occ[i])
                    m.add(post[i] >= occ[i])
                if i > 0:
                    m.add(pre[i] >= pre[i - 1])
                if i < k - 1:
                    m.add(post[i] >= post[i + 1])
            for i in range(1, k - 1):
                if possible[0] < i < possible[-1]:
                    g = m.new_bool_var("")
                    m.add(g >= pre[i - 1] + post[i + 1] - occ[i] - 1)
                    gaps.append(g)
        return gaps

    def add_objective(self, weights: Weights) -> None:
        """Weighted soft constraints, same definitions as scoring.score()."""
        inst, m, grid = self.instance, self.model, self.instance.grid
        terms: dict[str, list] = {k: [] for k in CRITERIA}

        terms["late"] = [self.x[c.id, t] for c in inst.courses for t in grid.late_slots if (c.id, t) in self.x]

        for c in inst.courses:
            if not (c.is_lab and c.sessions_per_week >= 2):
                continue
            wanted = c.sessions_per_week // 2
            pairs = {(a, b): m.new_bool_var("") for a, b in sorted(grid.consecutive_pairs)
                     if (c.id, a) in self.x and (c.id, b) in self.x}
            for t in self.course_slots(c.id):
                touching = [v for (a, b), v in pairs.items() if t in (a, b)]
                if touching:
                    m.add(sum(touching) <= self.x[c.id, t])  # each session in at most one block
            if pairs:
                m.add(sum(pairs.values()) <= wanted)
            terms["tp_split"].append(wanted - sum(pairs.values()))

        if weights.teacher_gaps:
            for cids in teacher_courses(inst).values():
                terms["teacher_gaps"] += self._gap_vars(cids)

        for cids in chain_courses(inst).values():
            if weights.student_gaps:
                terms["student_gaps"] += self._gap_vars(cids)
            loads = [sum(v for t in day for v in self._occ(cids, t)) for day in grid.slots_by_day]
            if weights.single_session_day:
                for day in grid.slots_by_day:
                    occ = {t: sum(v) for t in day if (v := self._occ(cids, t))}
                    if not occ:
                        continue
                    one = m.new_bool_var("")
                    for t, o in occ.items():  # one >= 1 iff exactly one occupied slot that day
                        m.add(one >= o - sum(other for s, other in occ.items() if s != t))
                    terms["single_session_day"].append(one)
            if weights.imbalance and len(grid.full_days) >= 2:
                hi = m.new_int_var(0, grid.num_slots, "")
                lo = m.new_int_var(0, grid.num_slots, "")
                for d in grid.full_days:
                    m.add(hi >= loads[d])
                    m.add(lo <= loads[d])
                # No ceil(L/n) - floor(L/n) cut here: tried and measured useless, the full-day load L
                # moves with Saturday sessions so some placement nearly always makes L divisible by n.
                terms["imbalance"].append(hi - lo)

        self.terms = {k: sum(v) for k, v in terms.items()}
        self.weights = weights
        m.minimize(sum(getattr(weights, k) * expr for k, expr in self.terms.items()))

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
               workers: int = DEFAULT_WORKERS, random_seed: int = 0,
               previous_rooms: dict[tuple[str, int], str] | None = None,
               frozen_rooms: set[tuple[str, int]] | None = None) -> SolveResult:
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
            rooms = assign_rooms(tm.instance, tm.chosen_slots(solver), workers=workers, random_seed=random_seed,
                                 previous=previous_rooms, frozen=frozen_rooms)
            solution = rooms.solution
            room_stats = {"room_time": round(rooms.time, 3), "tp_blocks": rooms.tp_blocks,
                          "same_room_blocks": rooms.same_room_blocks}

    objective = bound = gap = None
    score_info = None
    if solution is not None and tm.model.has_objective():
        objective, bound = solver.objective_value, solver.best_objective_bound
        gap = abs(objective - bound) / max(1.0, abs(objective))
        # true score of the returned timetable (auxiliary vars may be loose if not OPTIMAL: score <= objective)
        score_info = score(tm.instance, solution, tm.weights).as_dict()
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
        "score": score_info,
    }
    return SolveResult(status=name, solution=solution, stats=stats)


def solve(instance: Instance, time_limit: float = DEFAULT_TIME_LIMIT, workers: int = DEFAULT_WORKERS,
          random_seed: int = 0, rooms: RoomsMode = "threshold", weights: Weights | None = None,
          optimize: bool = True) -> SolveResult:
    """Build and solve the timetable. optimize=False: hard constraints only (feasibility)."""
    tm = TimetableModel(instance, rooms=rooms)
    if optimize:
        tm.add_objective(weights or Weights())
    return run_solver(tm, time_limit=time_limit, workers=workers, random_seed=random_seed)
