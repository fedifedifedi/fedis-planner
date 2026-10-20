"""Measure CP-SAT model size and solve time (hard constraints only) on the three school sizes.

Usage: python -m bench.model_size [--rooms both|threshold|full] [--seeds 1 2 3] [--time-limit 120]
                                  [--workers 8] [--random-seed 0]
"""

from __future__ import annotations

import argparse

from planner.generator import INFEASIBLE_KINDS, PROFILES, generate, make_infeasible
from planner.solver import TimetableModel, run_solver
from planner.validate import check_solution

COLUMNS = ["instance", "rooms_mode", "status", "sessions", "x_vars", "y_vars", "variables", "constraints",
           "build_time", "solve_time", "room_time", "same_room", "violations"]


def measure(instance, rooms: str, time_limit: float, workers: int, random_seed: int) -> dict:
    tm = TimetableModel(instance, rooms=rooms)
    res = run_solver(tm, time_limit=time_limit, workers=workers, random_seed=random_seed)
    violations = len(check_solution(instance, res.solution)) if res.solution else "-"
    same = f"{res.stats['same_room_blocks']}/{res.stats['tp_blocks']}" if res.stats["tp_blocks"] is not None else "-"
    return {"instance": instance.name, "sessions": sum(c.sessions_per_week for c in instance.courses),
            **res.stats, "same_room": same, "violations": violations}


def print_row(row: dict) -> None:
    print("| " + " | ".join("-" if row.get(c) is None else str(row[c]) for c in COLUMNS) + " |", flush=True)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rooms", choices=["both", "threshold", "full"], default="both")
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    p.add_argument("--time-limit", type=float, default=120.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--random-seed", type=int, default=0)
    args = p.parse_args(argv)
    modes = ["threshold", "full"] if args.rooms == "both" else [args.rooms]

    print(f"CP-SAT hard constraints | workers={args.workers} random_seed={args.random_seed} "
          f"time_limit={args.time_limit}s\n")
    print("| " + " | ".join(COLUMNS) + " |")
    print("|" + "---|" * len(COLUMNS))
    for size in PROFILES:
        for seed in args.seeds:
            inst = generate(size, seed)
            for mode in modes:
                print_row(measure(inst, mode, args.time_limit, args.workers, args.random_seed))
    for kind in INFEASIBLE_KINDS:
        for size in PROFILES:
            base = generate(size, args.seeds[0])
            try:
                inst = make_infeasible(base, kind)
            except ValueError as exc:  # e.g. lab demand fits in a single lab: no shortage possible
                print(f"| {base.name}-{kind} | n/a ({exc}) |" + " |" * (len(COLUMNS) - 2), flush=True)
                continue
            for mode in modes:
                print_row(measure(inst, mode, args.time_limit, args.workers, args.random_seed))


if __name__ == "__main__":
    main()
