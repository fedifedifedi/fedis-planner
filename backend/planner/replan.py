"""Replanning after a disruption (teacher absence) while changing as few sessions as possible.

- The absent slots (from `announced_at` on) are added to the teacher's unavailability.
- Slots before `announced_at` are in the past: their sessions are frozen (slot and room), and
  nothing can be moved into them.
- Phase A minimises the number of moved sessions: sum over previous future sessions (c, t) of
  (1 - x[c, t]) (sessions of a course are interchangeable, so a session "moves" when its old slot
  is no longer used). Phase B fixes that number and minimises the weighted score.
- Rooms: phase 2 keeps the previous room of every session that kept its slot when possible.
- Infeasible: returns the minimal conflicting set (explain.py), past sessions included.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field, ValidationError

from planner.explain import Explanation, explain
from planner.model import Instance, Solution
from planner.scoring import Weights, score
from planner.solver import DEFAULT_WORKERS, TimetableModel, run_solver


class Absence(BaseModel):
    teacher_id: str
    slots: list[int] = Field(min_length=1)


def absence_for_days(instance: Instance, teacher_id: str, days: list[int | str]) -> Absence:
    """Absence over whole days, given by index or name (e.g. ["Mardi"])."""
    names = [d.name for d in instance.grid.days]
    idx = [d if isinstance(d, int) else names.index(d) for d in days]
    return Absence(teacher_id=teacher_id, slots=[t for d in idx for t in instance.grid.slots_by_day[d]])


class Change(BaseModel):
    course_id: str
    kind: str  # "moved" (new slot) or "room" (same slot, other room)
    before_slot: int
    before_room: str
    after_slot: int
    after_room: str
    before: str
    after: str


class ReplanResult(BaseModel):
    status: str
    feasible: bool
    solution: Solution | None = None
    changes: list[Change] = Field(default_factory=list)
    sessions_moved: int | None = None
    rooms_changed: int | None = None
    min_moves: int = 0  # lower bound: sessions of the absent teacher during the (future) absence
    frozen_sessions: int = 0
    score_before: int | None = None
    score_after: int | None = None
    stats: dict = Field(default_factory=dict)
    explanation: Explanation | None = None


def diff(instance: Instance, old: Solution, new: Solution) -> list[Change]:
    grid = instance.grid
    old_by, new_by = defaultdict(dict), defaultdict(dict)
    for a in old.assignments:
        old_by[a.course_id][a.slot] = a.room_id
    for a in new.assignments:
        new_by[a.course_id][a.slot] = a.room_id
    changes = []
    for c in instance.courses:
        os, ns = old_by[c.id], new_by[c.id]
        removed = sorted(t for t in os if t not in ns)
        added = sorted(t for t in ns if t not in os)
        for t0, t1 in zip(removed, added):
            changes.append(Change(course_id=c.id, kind="moved", before_slot=t0, before_room=os[t0], after_slot=t1,
                                  after_room=ns[t1], before=f"{grid.describe(t0)} ({os[t0]})",
                                  after=f"{grid.describe(t1)} ({ns[t1]})"))
        for t in sorted(set(os) & set(ns)):
            if os[t] != ns[t]:
                changes.append(Change(course_id=c.id, kind="room", before_slot=t, before_room=os[t], after_slot=t,
                                      after_room=ns[t], before=f"{grid.describe(t)} ({os[t]})",
                                      after=f"{grid.describe(t)} ({ns[t]})"))
    return changes


def _phase_stats(res) -> dict:
    return {k: res.stats.get(k) for k in ("status", "objective", "best_bound", "gap", "solve_time")}


def replan(instance: Instance, solution: Solution, absence: Absence, announced_at: int = 0,
           weights: Weights | None = None, time_limit: float = 30.0, workers: int = DEFAULT_WORKERS,
           random_seed: int = 0, optimize_quality: bool = True) -> ReplanResult:
    weights = weights or Weights()
    n = instance.grid.num_slots
    if absence.teacher_id not in instance.teacher_by_id:
        raise ValueError(f"unknown teacher {absence.teacher_id!r}")
    if not 0 <= announced_at <= n:
        raise ValueError(f"announced_at must be in 0..{n}")

    future_absent = sorted({t for t in absence.slots if announced_at <= t < n})  # past absences: already held
    data = instance.model_dump()
    for t in data["teachers"]:
        if t["id"] == absence.teacher_id:
            t["unavailable"] = sorted(set(t["unavailable"]) | set(future_absent))
    taught = {c.id for c in instance.courses if c.teacher_id == absence.teacher_id}
    min_moves = sum(1 for a in solution.assignments if a.course_id in taught and a.slot in set(future_absent))
    frozen = {(a.course_id, a.slot) for a in solution.assignments if a.slot < announced_at}
    base = dict(min_moves=min_moves, frozen_sessions=len(frozen),
                score_before=score(instance, solution, weights).total)
    try:
        new_instance = Instance.model_validate(data)
    except ValidationError as exc:  # e.g. the teacher no longer has enough free slots
        msg = exc.errors()[0]["msg"].removeprefix("Value error, ")
        return ReplanResult(status="INFEASIBLE", feasible=False, **base, explanation=Explanation(
            feasible=False, summary=f"Replanification impossible (contrôle de volume) : {msg}"))

    old_rooms = {(a.course_id, a.slot): a.room_id for a in solution.assignments}
    future_old = [(a.course_id, a.slot) for a in solution.assignments if a.slot >= announced_at]

    def build(hint: set[tuple[str, int]]):
        tm = TimetableModel(new_instance)
        tm.freeze_before(solution, announced_at)
        moved = sum((1 - tm.x[k]) if k in tm.x else 1 for k in future_old)
        for k, x in tm.x.items():
            tm.model.add_hint(x, int(k in hint))
        return tm, moved

    run = dict(time_limit=time_limit, workers=workers, random_seed=random_seed,
               previous_rooms=old_rooms, frozen_rooms=frozen)

    tm, moved = build(set(old_rooms))
    tm.model.minimize(moved)
    res = run_solver(tm, **run)
    stats = {"phase_moves": _phase_stats(res), "rooms_mode": res.stats["rooms_mode"]}
    if not res.feasible:
        explanation = explain(new_instance, past=(solution, announced_at)) if res.status == "INFEASIBLE" else None
        return ReplanResult(status=res.status, feasible=False, **base, stats=stats, explanation=explanation)

    best = sum(1 for ch in diff(instance, solution, res.solution) if ch.kind == "moved")
    if optimize_quality:
        tm2, moved2 = build({(a.course_id, a.slot) for a in res.solution.assignments})
        tm2.model.add(moved2 <= best)
        tm2.add_objective(weights)
        res2 = run_solver(tm2, **run)
        stats["phase_quality"] = _phase_stats(res2)
        if res2.feasible:
            res = res2

    changes = diff(instance, solution, res.solution)
    return ReplanResult(
        status=stats["phase_moves"]["status"], feasible=True, solution=res.solution, changes=changes,
        sessions_moved=sum(1 for ch in changes if ch.kind == "moved"),
        rooms_changed=sum(1 for ch in changes if ch.kind == "room"),
        score_after=score(new_instance, res.solution, weights).total, stats=stats, **base)
