"""Fedi's Planner HTTP API (local use only: no auth, no rate limit, no database).

Stateless: every request carries the instance (and the solution when needed) as JSON.
The only limit is the solver time, capped by FEDIS_MAX_TIME_LIMIT (seconds, default 120).

Run: cd backend; .venv\\Scripts\\python.exe -m uvicorn api.main:app --reload
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from planner.explain import Explanation, explain
from planner.export_ics import to_ics
from planner.generator import INFEASIBLE_KINDS, PROFILES, generate, make_infeasible
from planner.greedy import greedy
from planner.model import Instance, Solution
from planner.replan import Absence, ReplanResult, replan
from planner.scoring import Weights, score
from planner.solver import solve

MAX_TIME_LIMIT = float(os.environ.get("FEDIS_MAX_TIME_LIMIT", "120"))
INSTANCES_DIR = Path(__file__).resolve().parent.parent / "instances"

app = FastAPI(title="Fedi's Planner", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])

TimeLimit = Field(default=30.0, gt=0, description=f"seconds, capped at FEDIS_MAX_TIME_LIMIT ({MAX_TIME_LIMIT:g})")


def _limit(seconds: float) -> float:
    return min(seconds, MAX_TIME_LIMIT)


# ------------------------------------------------------------------ requests


class GenerateRequest(BaseModel):
    size: Literal["small", "medium", "large"] = "small"
    seed: int = 42
    tightness: float = Field(default=0.75, gt=0, le=1)
    infeasible: Literal["room_shortage", "teacher_availability"] | None = None


class SolveRequest(BaseModel):
    instance: Instance
    weights: Weights = Field(default_factory=Weights)
    time_limit: float = TimeLimit
    workers: int = Field(default=8, ge=1, le=64)
    random_seed: int = 0
    warm_start: bool = Field(default=True, description="start from the greedy solution (see bench/NOTES.md)")


class InstanceRequest(BaseModel):
    instance: Instance
    weights: Weights = Field(default_factory=Weights)


class ExplainRequest(BaseModel):
    instance: Instance
    check_time_limit: float = Field(default=20.0, gt=0)


class ScoreRequest(BaseModel):
    instance: Instance
    solution: Solution
    weights: Weights = Field(default_factory=Weights)


class ReplanRequest(BaseModel):
    instance: Instance
    solution: Solution
    absence: Absence
    announced_at: int = 0
    weights: Weights = Field(default_factory=Weights)
    time_limit: float = TimeLimit


class BenchmarkRequest(BaseModel):
    instance: Instance
    weights: Weights = Field(default_factory=Weights)
    time_limit: float = TimeLimit


class IcsRequest(BaseModel):
    instance: Instance
    solution: Solution
    week_start: date | None = Field(default=None, description="Monday of the week (default: next Monday)")
    group: str | None = None
    teacher: str | None = None
    room: str | None = None
    weeks: int = Field(default=1, ge=1, le=52)


# ------------------------------------------------------------------ endpoints


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "max_time_limit": MAX_TIME_LIMIT}


@app.get("/instances/samples")
def list_samples() -> list[str]:
    return sorted(p.stem for p in INSTANCES_DIR.glob("*.json"))


@app.get("/instances/samples/{name}")
def get_sample(name: str) -> Instance:
    if name not in list_samples():
        raise HTTPException(404, f"unknown sample {name!r}")
    return Instance.load(INSTANCES_DIR / f"{name}.json")


@app.post("/instances/generate")
def generate_instance(req: GenerateRequest) -> Instance:
    inst = generate(req.size, req.seed, req.tightness)
    if req.infeasible:
        try:
            inst = make_infeasible(inst, req.infeasible, seed=req.seed)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return inst


@app.get("/meta")
def meta() -> dict:
    return {"sizes": sorted(PROFILES), "infeasible_kinds": list(INFEASIBLE_KINDS),
            "default_weights": Weights().model_dump(), "max_time_limit": MAX_TIME_LIMIT}


@app.post("/solve")
def solve_endpoint(req: SolveRequest) -> dict:
    hint = greedy(req.instance, req.weights).solution if req.warm_start else None
    res = solve(req.instance, time_limit=_limit(req.time_limit), workers=req.workers,
                random_seed=req.random_seed, weights=req.weights, hint=hint)
    return {"status": res.status, "feasible": res.feasible, "solution": res.solution, "stats": res.stats}


@app.post("/greedy")
def greedy_endpoint(req: InstanceRequest) -> dict:
    res = greedy(req.instance, req.weights)
    return {"solution": res.solution, "unplaced": [{"course_id": c, "session": s} for c, s in res.unplaced],
            "time": round(res.time, 4), "score": score(req.instance, res.solution, req.weights).as_dict()}


@app.post("/score")
def score_endpoint(req: ScoreRequest) -> dict:
    return score(req.instance, req.solution, req.weights).as_dict()


@app.post("/explain")
def explain_endpoint(req: ExplainRequest) -> Explanation:
    return explain(req.instance, check_time_limit=_limit(req.check_time_limit))


@app.post("/replan")
def replan_endpoint(req: ReplanRequest) -> ReplanResult:
    try:
        return replan(req.instance, req.solution, req.absence, announced_at=req.announced_at,
                      weights=req.weights, time_limit=_limit(req.time_limit))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/benchmark")
def benchmark_endpoint(req: BenchmarkRequest) -> dict:
    """Greedy vs CP-SAT on one instance (quality with the shared score, and time)."""
    g = greedy(req.instance, req.weights)
    cp = solve(req.instance, time_limit=_limit(req.time_limit), weights=req.weights)
    return {
        "greedy": {"time": round(g.time, 4), "unplaced": len(g.unplaced),
                   "score": score(req.instance, g.solution, req.weights).as_dict()},
        "cpsat": {"status": cp.status, "time": cp.stats["solve_time"], "best_bound": cp.stats["best_bound"],
                  "gap": cp.stats["gap"], "score": cp.stats["score"]},
    }


@app.post("/export/ics")
def export_ics(req: IcsRequest) -> Response:
    if sum(x is not None for x in (req.group, req.teacher, req.room)) > 1:
        raise HTTPException(422, "filter by at most one of group, teacher, room")
    for value, known, kind in ((req.group, req.instance.group_by_id, "group"),
                               (req.teacher, req.instance.teacher_by_id, "teacher"),
                               (req.room, req.instance.room_by_id, "room")):
        if value is not None and value not in known:
            raise HTTPException(422, f"unknown {kind} {value!r}")
    today = date.today()
    week_start = req.week_start or today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    body = to_ics(req.instance, req.solution, week_start, group=req.group, teacher=req.teacher, room=req.room,
                  weeks=req.weeks)
    name = req.group or req.teacher or req.room or req.instance.name
    return Response(content=body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.ics"'})
