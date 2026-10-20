import pytest
from fastapi.testclient import TestClient

from api import main
from api.main import app
from planner.generator import generate, make_infeasible
from planner.model import Instance, Solution
from planner.validate import check_solution

client = TestClient(app)


@pytest.fixture(scope="module")
def small() -> dict:
    return generate("small", seed=42).model_dump(mode="json")


@pytest.fixture(scope="module")
def solved(small) -> dict:
    r = client.post("/solve", json={"instance": small, "time_limit": 5})
    assert r.status_code == 200
    return r.json()


def test_health_and_meta():
    assert client.get("/health").json()["status"] == "ok"
    meta = client.get("/meta").json()
    assert meta["sizes"] == ["large", "medium", "small"] and meta["default_weights"]["tp_split"] == 4


def test_samples():
    assert client.get("/instances/samples").json() == ["large", "medium", "small"]
    inst = Instance.model_validate(client.get("/instances/samples/small").json())
    assert inst.name == "small-s42"
    assert client.get("/instances/samples/nope").status_code == 404


def test_generate():
    r = client.post("/instances/generate", json={"size": "medium", "seed": 3})
    assert Instance.model_validate(r.json()).name == "medium-s3"
    r = client.post("/instances/generate", json={"size": "small", "infeasible": "teacher_availability"})
    assert r.json()["name"].endswith("teacher_availability")
    assert client.post("/instances/generate", json={"size": "huge"}).status_code == 422


def test_invalid_instance_rejected(small):
    bad = {**small, "groups": [{**small["groups"][1], "parent": "NOPE"}, *small["groups"][2:]]}
    r = client.post("/solve", json={"instance": bad})
    assert r.status_code == 422 and "unknown" in r.text


def test_solve(small, solved):
    assert solved["feasible"] and solved["status"] in ("OPTIMAL", "FEASIBLE")
    sol = Solution.model_validate(solved["solution"])
    assert check_solution(Instance.model_validate(small), sol) == []
    assert solved["stats"]["score"]["total"] >= 0 and solved["stats"]["time_limit"] == 5


def test_solve_with_custom_weights_and_warm_start(small):
    r = client.post("/solve", json={"instance": small, "time_limit": 3, "warm_start": True,
                                    "weights": {"late": 0, "imbalance": 0}})
    body = r.json()
    assert body["feasible"] and body["stats"]["score"]["weights"]["late"] == 0


def test_time_limit_is_capped(small, monkeypatch):
    monkeypatch.setattr(main, "MAX_TIME_LIMIT", 2.0)
    r = client.post("/solve", json={"instance": small, "time_limit": 999})
    assert r.json()["stats"]["time_limit"] == 2.0


def test_greedy_and_score(small, solved):
    g = client.post("/greedy", json={"instance": small}).json()
    assert g["unplaced"] == [] and g["score"]["total"] > 0
    s = client.post("/score", json={"instance": small, "solution": solved["solution"]}).json()
    assert s["total"] == solved["stats"]["score"]["total"]


def test_explain():
    inst = make_infeasible(generate("small", seed=42), "teacher_availability").model_dump(mode="json")
    e = client.post("/explain", json={"instance": inst}).json()
    assert e["feasible"] is False and len(e["core"]) == 3 and e["minimal"]
    assert "tous les cours doivent avoir leurs heures" in e["summary"]


def test_replan(small, solved):
    teacher = small["courses"][0]["teacher_id"]
    r = client.post("/replan", json={"instance": small, "solution": solved["solution"],
                                     "absence": {"teacher_id": teacher, "slots": [5, 6, 7, 8, 9]},
                                     "announced_at": 5, "time_limit": 5})
    body = r.json()
    assert body["feasible"] and body["sessions_moved"] >= body["min_moves"]
    bad = client.post("/replan", json={"instance": small, "solution": solved["solution"],
                                       "absence": {"teacher_id": "NOPE", "slots": [0]}})
    assert bad.status_code == 422


def test_benchmark(small):
    b = client.post("/benchmark", json={"instance": small, "time_limit": 3}).json()
    assert b["greedy"]["unplaced"] == 0 and b["cpsat"]["score"]["total"] <= b["greedy"]["score"]["total"]


def test_export_ics(small, solved):
    r = client.post("/export/ics", json={"instance": small, "solution": solved["solution"], "group": "L1-G1a",
                                         "week_start": "2026-10-26"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert 'filename="L1-G1a.ics"' in r.headers["content-disposition"]
    assert r.text.startswith("BEGIN:VCALENDAR")
    days = {line[8:16] for line in r.text.split("\r\n") if line.startswith("DTSTART:")}
    assert days and days <= {f"202610{d}" for d in range(26, 32)}  # Mon 26 -> Sat 31 Oct
    assert client.post("/export/ics", json={"instance": small, "solution": solved["solution"],
                                            "group": "L1-G1a", "teacher": "T001"}).status_code == 422
    assert client.post("/export/ics", json={"instance": small, "solution": solved["solution"],
                                            "room": "NOPE"}).status_code == 422
