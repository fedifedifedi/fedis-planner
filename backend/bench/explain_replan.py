"""Timing of conflict explanation and replanning on the three school sizes.

Usage: python -m bench.explain_replan [--seed 42] [--time-limit 30]
"""

from __future__ import annotations

import argparse
import time

from planner.explain import explain
from planner.generator import INFEASIBLE_KINDS, PROFILES, generate, make_infeasible
from planner.replan import absence_for_days, replan
from planner.solver import solve


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--time-limit", type=float, default=30.0)
    args = p.parse_args(argv)

    print("## Explanation (single worker, linearization_level=2)\n")
    print("| instance | minimal | core | checks | time (s) |\n|---|---|---|---|---|")
    for kind in INFEASIBLE_KINDS:
        for size in PROFILES:
            e = explain(make_infeasible(generate(size, args.seed), kind))
            core = ", ".join(f"{c.family}:{c.entity}" for c in e.core)
            print(f"| {size}-{kind} | {e.minimal} | {core} | {e.checks} | {e.time} |", flush=True)

    print("\n## Replanning: busiest teacher absent on Tuesday (8 workers)\n")
    print("| instance | announced_at | min_moves | moved | rooms_changed | frozen | score before -> after "
          "| moves phase | time (s) |\n|---|---|---|---|---|---|---|---|---|")
    for size in PROFILES:
        inst = generate(size, args.seed)
        old = solve(inst, time_limit=args.time_limit, random_seed=0).solution
        busiest = max(inst.teachers, key=lambda t: sum(c.sessions_per_week for c in inst.courses
                                                       if c.teacher_id == t.id))
        absence = absence_for_days(inst, busiest.id, ["Mardi"])
        for announced in (0, absence.slots[0]):  # start of week, or announced on Tuesday morning
            start = time.perf_counter()
            r = replan(inst, old, absence, announced_at=announced, time_limit=args.time_limit)
            elapsed = round(time.perf_counter() - start, 2)
            if not r.feasible:
                print(f"| {inst.name} | {announced} | {r.min_moves} | infeasible | | | | | {elapsed} |")
                continue
            print(f"| {inst.name} | {announced} | {r.min_moves} | {r.sessions_moved} | {r.rooms_changed} | "
                  f"{r.frozen_sessions} | {r.score_before} -> {r.score_after} | {r.stats['phase_moves']['status']} "
                  f"| {elapsed} |", flush=True)


if __name__ == "__main__":
    main()
