"""Benchmark: greedy vs CP-SAT (cold start) vs CP-SAT warm-started from the greedy solution.

Quality = scoring.score() (same function for every algorithm) + unplaced sessions.
For CP-SAT: time to first solution and time to beat the greedy score (from a solution callback).

Usage: python -m bench.compare [--seeds 1 2 3] [--tight-seeds 1] [--time-limit 60] [--workers 8]
"""

from __future__ import annotations

import argparse
import time

from ortools.sat.python import cp_model

from planner.generator import PROFILES, generate
from planner.greedy import greedy
from planner.scoring import score
from planner.solver import solve
from planner.validate import check_solution


class Progress(cp_model.CpSolverSolutionCallback):
    def __init__(self, target: float) -> None:
        super().__init__()
        self.start = time.perf_counter()
        self.target = target
        self.first: float | None = None
        self.beat: float | None = None

    def on_solution_callback(self) -> None:
        now = time.perf_counter() - self.start
        if self.first is None:
            self.first = now
        if self.beat is None and self.objective_value < self.target:  # objective >= true score
            self.beat = now


def fmt(x, digits=2):
    return "-" if x is None else (f"{x:.{digits}f}" if isinstance(x, float) else str(x))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    p.add_argument("--tight-seeds", type=int, nargs="*", default=[1])
    p.add_argument("--time-limit", type=float, default=60.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--random-seed", type=int, default=0)
    args = p.parse_args(argv)

    cases = [(generate(size, seed), "0.75") for size in PROFILES for seed in args.seeds]
    cases += [(generate(size, seed, tightness=1.0), "1.00") for size in PROFILES for seed in args.tight_seeds]

    print(f"Greedy vs CP-SAT | workers={args.workers} random_seed={args.random_seed} "
          f"time_limit={args.time_limit}s | default weights\n")
    print("| instance | tightness | greedy score | greedy unplaced | greedy time (s) "
          "| CP-SAT status | CP-SAT score | bound | first sol (s) | beats greedy at (s) "
          "| hinted status | hinted score | hinted first (s) | violations |")
    print("|" + "---|" * 14)
    for inst, tight in cases:
        g = greedy(inst)
        g_score = score(inst, g.solution).total
        cold_cb = Progress(g_score)
        cold = solve(inst, time_limit=args.time_limit, workers=args.workers, random_seed=args.random_seed,
                     callback=cold_cb)
        warm_cb = Progress(g_score)
        warm = solve(inst, time_limit=args.time_limit, workers=args.workers, random_seed=args.random_seed,
                     hint=g.solution, callback=warm_cb)
        viol = [len(check_solution(inst, r.solution)) if r.feasible else "-" for r in (cold, warm)]
        g_viol = len([e for e in check_solution(inst, g.solution) if "sessions scheduled" not in e])
        print(f"| {inst.name} | {tight} | {g_score} | {len(g.unplaced)} | {g.time:.3f} "
              f"| {cold.status} | {fmt(cold.stats['score']['total'] if cold.feasible else None)} "
              f"| {fmt(cold.stats['best_bound'], 0)} | {fmt(cold_cb.first)} | {fmt(cold_cb.beat)} "
              f"| {warm.status} | {fmt(warm.stats['score']['total'] if warm.feasible else None)} "
              f"| {fmt(warm_cb.first)} | greedy {g_viol} / cold {viol[0]} / hinted {viol[1]} |", flush=True)


if __name__ == "__main__":
    main()
