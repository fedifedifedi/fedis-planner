"""Solution quality with the weighted objective on the three school sizes.

Usage: python -m bench.objective [--seeds 1 2 3] [--time-limit 60] [--workers 8] [--random-seed 0]
"""

from __future__ import annotations

import argparse

from planner.generator import PROFILES, generate
from planner.scoring import CRITERIA
from planner.solver import solve
from planner.validate import check_solution

COLUMNS = ["instance", "status", "objective", "best_bound", "gap", "solve_time", "room_time", "same_room",
           *CRITERIA, "violations"]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    p.add_argument("--time-limit", type=float, default=60.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--random-seed", type=int, default=0)
    args = p.parse_args(argv)

    print(f"CP-SAT weighted objective | workers={args.workers} random_seed={args.random_seed} "
          f"time_limit={args.time_limit}s | default weights\n")
    print("| " + " | ".join(COLUMNS) + " |")
    print("|" + "---|" * len(COLUMNS))
    for size in PROFILES:
        for seed in args.seeds:
            inst = generate(size, seed)
            res = solve(inst, time_limit=args.time_limit, workers=args.workers, random_seed=args.random_seed)
            s = res.stats
            row = {"instance": inst.name, **s,
                   "gap": f"{s['gap']:.1%}" if s["gap"] is not None else None,
                   "same_room": f"{s['same_room_blocks']}/{s['tp_blocks']}" if res.feasible else None,
                   "violations": len(check_solution(inst, res.solution)) if res.feasible else None}
            if res.feasible:
                row.update(s["score"]["breakdown"])
            print("| " + " | ".join("-" if row.get(c) is None else str(row[c]) for c in COLUMNS) + " |",
                  flush=True)


if __name__ == "__main__":
    main()
