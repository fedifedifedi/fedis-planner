import random

import pytest

from planner.generator import PROFILES, generate, main, make_infeasible
from planner.model import Instance, RoomType

SIZES = sorted(PROFILES)


@pytest.fixture(scope="module", params=SIZES)
def instance(request) -> Instance:
    return generate(request.param, seed=42)


# ------------------------------------------------------------------ reproducibility


@pytest.mark.parametrize("size", SIZES)
def test_same_seed_same_instance(size):
    assert generate(size, seed=7).model_dump_json() == generate(size, seed=7).model_dump_json()


def test_different_seeds_differ():
    assert generate("small", seed=1).model_dump_json() != generate("small", seed=2).model_dump_json()


def test_global_random_state_is_ignored():
    random.seed(0)
    a = generate("small", seed=3).model_dump_json()
    random.seed(12345)
    random.random()
    b = generate("small", seed=3).model_dump_json()
    assert a == b


def test_generation_does_not_touch_global_random_state():
    random.seed(99)
    expected = random.random()
    random.seed(99)
    generate("medium", seed=5)
    assert random.random() == expected


# ------------------------------------------------------------------ structure


@pytest.mark.parametrize("size,groups,min_t,max_t", [
    ("small", 10, 6, 20),
    ("medium", 39, 25, 70),
    ("large", 95, 60, 150),
])
def test_sizes(size, groups, min_t, max_t):
    inst = generate(size, seed=42)
    assert len(inst.groups) == groups
    assert min_t <= len(inst.teachers) <= max_t


def test_three_level_hierarchy(instance):
    promos = [g for g in instance.groups if g.parent is None]
    assert len(promos) == len(PROFILES[instance.name.split("-")[0]].levels)
    for chain in instance.student_chains:
        assert len(chain) == 3  # subgroup -> group -> promo


def test_course_kinds_target_right_level(instance):
    for c in instance.courses:
        (gid,) = c.group_ids
        depth = len(instance.ancestors(gid))
        assert depth == {RoomType.CM: 0, RoomType.TD: 1, RoomType.TP: 2}[c.room_type]
        if c.room_type == RoomType.TP:
            assert c.sessions_per_week == 2 and c.max_sessions_per_day == 2


def test_student_load_around_target(instance):
    n = instance.grid.num_slots
    for chain in instance.student_chains:
        load = sum(c.sessions_per_week for c in instance.courses if chain & set(c.group_ids))
        assert 14 <= load <= 20 <= 0.75 * n


def test_teachers_within_capacity(instance):
    for t in instance.teachers:
        load = sum(c.sessions_per_week for c in instance.courses if c.teacher_id == t.id)
        assert 1 <= load <= 10
        assert load <= instance.grid.num_slots - len(t.unavailable)


def test_part_time_teachers_present():
    inst = generate("large", seed=42)
    full_days_off = [t for t in inst.teachers if len(t.unavailable) >= 8]  # 2 days off
    half_day_off = [t for t in inst.teachers if 0 < len(t.unavailable) <= 3]
    assert full_days_off and half_day_off


def test_room_occupancy_below_tightness(instance):
    n = instance.grid.num_slots
    for rtype in RoomType:
        demand = sum(c.sessions_per_week for c in instance.courses if c.room_type == rtype)
        rooms = [r for r in instance.rooms if r.type == rtype]
        assert demand <= 0.75 * n * len(rooms)


def test_tighter_instance_has_fewer_rooms():
    assert len(generate("medium", seed=1, tightness=0.95).rooms) < len(generate("medium", seed=1).rooms)


def test_realistic_names(instance):
    names = [t.name for t in instance.teachers]
    assert len(set(names)) == len(names)
    assert all(" " in n and not n[0].isdigit() for n in names)
    assert any("Algorithmique" in c.subject or "Bases de données" in c.subject or "IA" in c.subject
               or "Intelligence" in c.subject for c in instance.courses)


def test_unknown_size():
    with pytest.raises(ValueError):
        generate("huge")


# ------------------------------------------------------------------ infeasible variants


@pytest.mark.parametrize("size", SIZES)
def test_room_shortage_detectable_by_counting(size):
    inst = make_infeasible(generate(size, seed=42), "room_shortage")  # passes model validation
    n = inst.grid.num_slots
    demand = sum(c.sessions_per_week for c in inst.courses if c.room_type == RoomType.TP)
    labs = [r for r in inst.rooms if r.type == RoomType.TP]
    assert demand > n * len(labs)


@pytest.mark.parametrize("size", SIZES)
def test_teacher_availability_passes_volume_checks(size):
    """The conflict must be invisible to counting: Instance validation (incl. volume checks) passes."""
    inst = make_infeasible(generate(size, seed=42), "teacher_availability")
    inst._validate_loads()  # explicit: teacher and student-chain volume checks raise nothing
    n = inst.grid.num_slots
    v1, v2 = inst.teacher_by_id["V001"], inst.teacher_by_id["V002"]
    # each adjunct: exactly 1 session and exactly 1 available slot -> per-teacher counts are fine
    for v in (v1, v2):
        assert sum(c.sessions_per_week for c in inst.courses if c.teacher_id == v.id) == 1
        assert n - len(v.unavailable) == 1
    assert set(v1.unavailable) == set(v2.unavailable)  # ... but it is the same slot
    # and both sessions involve students of a common chain (promo CM + TD of one of its groups)
    (g1,) = next(c for c in inst.courses if c.teacher_id == "V001").group_ids
    (g2,) = next(c for c in inst.courses if c.teacher_id == "V002").group_ids
    assert any(g1 in chain and g2 in chain for chain in inst.student_chains)


def test_unknown_infeasible_kind():
    with pytest.raises(ValueError):
        make_infeasible(generate("small"), "nope")


# ------------------------------------------------------------------ CLI


def test_cli_writes_loadable_instance(tmp_path, capsys):
    out = tmp_path / "x.json"
    main(["--size", "small", "--seed", "3", "-o", str(out)])
    assert Instance.load(out).model_dump_json() == generate("small", seed=3).model_dump_json()
    assert "small-s3" in capsys.readouterr().out
