"""Soft-constraint weights and the single scoring function shared by every algorithm.

Criteria (all counts, lower is better):
  student_gaps        free slots between two sessions of the same student chain on the same day
  teacher_gaps        same for each teacher
  late                sessions placed on a slot flagged `late`
  tp_split            per lab course: wanted blocks (sessions // 2) minus disjoint consecutive pairs used
  imbalance           per chain: max - min daily load over full days (Mon-Fri by default)
  single_session_day  per chain and day (Saturday included): the chain comes for one session only

The CP-SAT objective (solver.TimetableModel.add_objective) encodes exactly these definitions;
for an optimal solution objective == score().total (tested).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from planner.model import GridConfig, Instance, Solution

CRITERIA = ("student_gaps", "teacher_gaps", "late", "tp_split", "imbalance", "single_session_day")


class Weights(BaseModel):
    model_config = ConfigDict(frozen=True)

    student_gaps: int = Field(default=3, ge=0)
    teacher_gaps: int = Field(default=1, ge=0)
    late: int = Field(default=2, ge=0)
    tp_split: int = Field(default=4, ge=0)
    imbalance: int = Field(default=1, ge=0)
    single_session_day: int = Field(default=2, ge=0)


@dataclass
class Score:
    breakdown: dict[str, int]
    weights: Weights

    @property
    def total(self) -> int:
        return sum(getattr(self.weights, k) * v for k, v in self.breakdown.items())

    def as_dict(self) -> dict:
        return {"total": self.total, "breakdown": self.breakdown, "weights": self.weights.model_dump()}


def disjoint_blocks(grid: GridConfig, slots: list[int]) -> list[tuple[int, int]]:
    """Maximum set of disjoint consecutive pairs among `slots` (left-to-right greedy, optimal on paths)."""
    s = sorted(slots)
    blocks, i = [], 0
    while i < len(s) - 1:
        if (s[i], s[i + 1]) in grid.consecutive_pairs:
            blocks.append((s[i], s[i + 1]))
            i += 2
        else:
            i += 1
    return blocks


def chain_courses(instance: Instance) -> dict[str, list[str]]:
    """Leaf group id -> courses attended by its students (leaf + ancestors)."""
    out = {}
    for chain in instance.student_chains:
        leaf = next(g for g in sorted(chain) if not instance.children[g])
        out[leaf] = [c.id for c in instance.courses if chain & set(c.group_ids)]
    return out


def teacher_courses(instance: Instance) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for c in instance.courses:
        out[c.teacher_id].append(c.id)
    return dict(sorted(out.items()))


def _gaps(grid: GridConfig, occupied: set[int]) -> int:
    total = 0
    for day_slots in grid.slots_by_day:
        used = [i for i, t in enumerate(day_slots) if t in occupied]
        if len(used) >= 2:
            total += (used[-1] - used[0] + 1) - len(used)
    return total


def score(instance: Instance, solution: Solution, weights: Weights | None = None) -> Score:
    weights = weights or Weights()
    grid = instance.grid
    slots_of: dict[str, list[int]] = defaultdict(list)
    for a in solution.assignments:
        slots_of[a.course_id].append(a.slot)

    def occupied(course_ids: list[str]) -> set[int]:
        return {t for cid in course_ids for t in slots_of.get(cid, [])}

    late = set(grid.late_slots)
    b = dict.fromkeys(CRITERIA, 0)
    b["late"] = sum(1 for a in solution.assignments if a.slot in late)
    for c in instance.courses:
        if c.is_lab and c.sessions_per_week >= 2:
            wanted = c.sessions_per_week // 2
            b["tp_split"] += wanted - min(wanted, len(disjoint_blocks(grid, slots_of.get(c.id, []))))
    for cids in teacher_courses(instance).values():
        b["teacher_gaps"] += _gaps(grid, occupied(cids))
    for cids in chain_courses(instance).values():
        occ = occupied(cids)
        b["student_gaps"] += _gaps(grid, occ)
        loads = [sum(1 for t in day if t in occ) for day in grid.slots_by_day]
        b["single_session_day"] += sum(1 for load in loads if load == 1)
        full = [loads[d] for d in grid.full_days]
        if full:
            b["imbalance"] += max(full) - min(full)
    return Score(breakdown=b, weights=weights)
