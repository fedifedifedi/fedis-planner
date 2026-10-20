"""Explain why an instance has no timetable.

1. Quick pre-checks (counting, no solver): weekly room demand per type and capacity threshold.
   Teacher and student-chain volumes are already rejected by Instance validation.
2. Minimal conflicting set: the model is built in explain mode (one assumption literal per
   constraint family and entity, e.g. "availability:T003", "students:L1-G1a"); CP-SAT returns a
   sufficient core (single worker), shrunk by deletion: drop an element, re-solve, keep it out if
   still infeasible. If a check ends UNKNOWN the element is kept and `minimal` is False.
   Background, always enforced: every course gets its sessions (hours) — stated in the message.
"""

from __future__ import annotations

import time

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field

from planner.model import Instance, RoomType
from planner.solver import TimetableModel

ASSUMPTION_NOTE = "en considérant que tous les cours doivent avoir leurs heures (volume horaire toujours imposé)"
ROOM_LABEL = {RoomType.CM: "amphi(s)", RoomType.TD: "salle(s) de TD", RoomType.TP: "labo(s)"}


class Conflict(BaseModel):
    family: str
    entity: str
    message: str
    details: dict = Field(default_factory=dict)


class Explanation(BaseModel):
    feasible: bool
    summary: str
    prechecks: list[Conflict] = Field(default_factory=list)
    core: list[Conflict] = Field(default_factory=list)
    minimal: bool = True
    checks: int = 0
    time: float = 0.0


# ------------------------------------------------------------------ pre-checks


def precheck(instance: Instance) -> list[Conflict]:
    """Weekly room demand per type and threshold k vs rooms(>= k) x slots."""
    n = instance.grid.num_slots
    conflicts = []
    for rtype in RoomType:
        courses = [c for c in instance.courses if c.room_type == rtype]
        for k in sorted({instance.course_size(c) for c in courses}):
            demand = sum(c.sessions_per_week for c in courses if instance.course_size(c) >= k)
            rooms = [r for r in instance.rooms if r.type == rtype and r.capacity >= k]
            if demand > len(rooms) * n:
                conflicts.append(Conflict(
                    family="precheck_rooms", entity=f"{rtype.value}:{k}",
                    message=(f"{demand} séances de {rtype.value} pour {k} étudiants ou plus, mais seulement "
                             f"{len(rooms)} {ROOM_LABEL[rtype]} de {k} places ou plus × {n} créneaux = "
                             f"{len(rooms) * n} places-créneaux"),
                    details={"type": rtype.value, "threshold": k, "sessions": demand, "rooms": len(rooms),
                             "slots": n}))
                break  # larger thresholds of the same type are usually redundant
    return conflicts


# ------------------------------------------------------------------ messages


def describe(instance: Instance, family: str) -> Conflict:
    kind, _, rest = family.partition(":")
    grid = instance.grid
    if kind == "availability":
        t = instance.teacher_by_id[rest]
        free = [s for s in range(grid.num_slots) if s not in set(t.unavailable)]
        load = sum(c.sessions_per_week for c in instance.courses if c.teacher_id == rest)
        where = ", ".join(grid.describe(s) for s in free) if len(free) <= 6 else f"{len(free)} créneaux"
        return Conflict(family=kind, entity=rest,
                        message=f"{t.name} n'est disponible que sur {where} ({load} séance(s) à donner)",
                        details={"available_slots": free, "sessions": load})
    if kind == "teacher":
        t = instance.teacher_by_id[rest]
        courses = [c.id for c in instance.courses if c.teacher_id == rest]
        return Conflict(family=kind, entity=rest, message=f"{t.name} ne peut donner qu'un cours à la fois",
                        details={"courses": courses})
    if kind == "students":
        others = instance.ancestors(rest)
        with_ = f" (avec {', '.join(others)})" if others else ""
        return Conflict(family=kind, entity=rest,
                        message=f"Les étudiants de {rest}{with_} ne peuvent suivre qu'un cours à la fois",
                        details={"groups": [rest, *others]})
    if kind == "room_capacity":
        rtype, k = RoomType(rest.split(":")[0]), int(rest.split(":")[1])
        rooms = [r.id for r in instance.rooms if r.type == rtype and r.capacity >= k]
        return Conflict(family=kind, entity=rest,
                        message=f"Au plus {len(rooms)} {ROOM_LABEL[rtype]} de {k} places ou plus par créneau",
                        details={"type": rtype.value, "threshold": k, "rooms": rooms})
    if kind == "max_per_day":
        c = instance.course_by_id[rest]
        return Conflict(family=kind, entity=rest,
                        message=f"Le cours {c.subject} ({c.id}) : au plus {c.max_sessions_per_day} séance(s) par jour",
                        details={"max_sessions_per_day": c.max_sessions_per_day,
                                 "sessions_per_week": c.sessions_per_week})
    if kind == "room":
        r = instance.room_by_id[rest]
        return Conflict(family=kind, entity=rest, message=f"La salle {r.name} n'accueille qu'un cours à la fois")
    return Conflict(family=kind, entity=rest, message=family)


# ------------------------------------------------------------------ minimal core


def _check(tm: TimetableModel, families: list[str], time_limit: float) -> tuple[str, list[str]]:
    """Solve with the given families assumed true. Returns (status, core families if infeasible)."""
    tm.model.clear_assumptions()
    tm.model.add_assumptions([tm.literals[f] for f in families])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 1  # required for sufficient_assumptions_for_infeasibility
    # full LP relaxation: counting conflicts (sum of fixed hours vs capacity) are found by the LP,
    # not by propagation (measured: room shortage UNKNOWN after 20 s at the default level, 0.15 s here)
    solver.parameters.linearization_level = 2
    status = solver.solve(tm.model)
    name = solver.status_name(status)
    if status != cp_model.INFEASIBLE:
        return name, []
    by_index = {tm.literals[f].index: f for f in families}
    return name, [by_index[i] for i in solver.sufficient_assumptions_for_infeasibility() if i in by_index]


def explain(instance: Instance, check_time_limit: float = 20.0) -> Explanation:
    start = time.perf_counter()
    pre = precheck(instance)
    tm = TimetableModel(instance, explain=True)
    families = sorted(tm.literals)

    status, core = _check(tm, families, check_time_limit)
    checks = 1
    if status in ("OPTIMAL", "FEASIBLE"):
        return Explanation(feasible=True, summary="Un emploi du temps existe : aucun conflit.", prechecks=pre,
                           checks=checks, time=round(time.perf_counter() - start, 3))
    if status != "INFEASIBLE":
        return Explanation(feasible=False, minimal=False, prechecks=pre, checks=checks,
                           summary=f"Impossible de conclure dans le temps imparti (statut {status}).",
                           time=round(time.perf_counter() - start, 3))

    current = list(core) if core else families
    minimal = True
    for fam in list(current):
        if fam not in current:
            continue  # already removed by a smaller core returned earlier
        trial = [f for f in current if f != fam]
        status, smaller = _check(tm, trial, check_time_limit)
        checks += 1
        if status == "INFEASIBLE":
            current = [f for f in trial if f in set(smaller)] if smaller else trial
        elif status not in ("OPTIMAL", "FEASIBLE"):
            minimal = False  # undecided: keep fam, cannot claim minimality

    conflicts = [describe(instance, f) for f in current]
    summary = (f"Aucun emploi du temps possible : ces {len(conflicts)} contraintes sont incompatibles entre elles, "
               f"{ASSUMPTION_NOTE}.")
    return Explanation(feasible=False, summary=summary, prechecks=pre, core=conflicts, minimal=minimal,
                       checks=checks, time=round(time.perf_counter() - start, 3))
