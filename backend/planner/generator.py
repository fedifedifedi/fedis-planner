"""Realistic instance generator (small / medium / large school).

Structure: promotion -> TD groups -> TP subgroups.
  - CM (lecture)  : whole promotion, lecture hall, 1 session/week
  - TD (tutorial) : each group, tutorial room, 1 session/week
  - TP (lab)      : each subgroup, lab, 2 sessions/week (max 2/day -> consecutive block possible)

Reproducibility: a single local random.Random(seed); every set/dict is sorted before drawing.

CLI: python -m planner.generator --size medium --seed 42 -o instances/medium.json
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from planner.model import Course, GridConfig, Group, Instance, Room, RoomType, Teacher


@dataclass(frozen=True)
class Profile:
    levels: tuple[str, ...]
    groups_per_promo: int
    subgroups_per_group: int = 2
    subjects_per_promo: int = 6


PROFILES: dict[str, Profile] = {
    "small": Profile(levels=("L1",), groups_per_promo=3),
    "medium": Profile(levels=("L1", "L2", "L3"), groups_per_promo=4),
    "large": Profile(levels=("L1", "L2", "L3", "M1", "M2"), groups_per_promo=6),
}

# (code, name, has_tp) — 8 subjects per level, 4 with labs, so a 6-subject draw has 2 to 4 labs.
CATALOG: dict[str, list[tuple[str, str, bool]]] = {
    "L1": [
        ("ANA", "Analyse", False), ("ALG", "Algèbre linéaire", False), ("ALGO", "Algorithmique", True),
        ("PROG", "Programmation Python", True), ("ARCHI", "Architecture des ordinateurs", True),
        ("WEB", "Introduction au Web", True), ("ANG", "Anglais", False), ("COM", "Communication", False),
    ],
    "L2": [
        ("PROBA", "Probabilités", False), ("POO", "Programmation orientée objet", True),
        ("BDD", "Bases de données", True), ("SYS", "Systèmes d'exploitation", True),
        ("RES", "Réseaux", True), ("LOG", "Logique", False), ("ANG", "Anglais", False),
        ("GEST", "Gestion d'entreprise", False),
    ],
    "L3": [
        ("GL", "Génie logiciel", True), ("COMP", "Compilation", True), ("RO", "Recherche opérationnelle", False),
        ("WEBA", "Développement web avancé", True), ("SECU", "Sécurité informatique", True),
        ("STAT", "Statistiques", False), ("ANG", "Anglais", False), ("DROIT", "Droit du numérique", False),
    ],
    "M1": [
        ("IA", "Intelligence artificielle", True), ("ML", "Apprentissage automatique", True),
        ("CLOUD", "Cloud computing", True), ("DIST", "Systèmes distribués", True),
        ("OPTIM", "Optimisation combinatoire", False), ("GPROJ", "Gestion de projet", False),
        ("ANG", "Anglais", False), ("ETH", "Éthique de l'IA", False),
    ],
    "M2": [
        ("DL", "Deep learning", True), ("BIG", "Big data", True), ("CYBER", "Cybersécurité avancée", True),
        ("DEVOPS", "DevOps", True), ("ENTR", "Entrepreneuriat", False), ("RECH", "Méthodologie de recherche", False),
        ("ANG", "Anglais professionnel", False), ("VEILLE", "Veille technologique", False),
    ],
}

FIRST_NAMES = [
    "Claire", "Julien", "Sophie", "Karim", "Nadia", "Thomas", "Amina", "Lucas", "Élodie", "Mehdi",
    "Camille", "Antoine", "Leïla", "Hugo", "Sarah", "Youssef", "Manon", "Nicolas", "Inès", "Pierre",
    "Fatima", "Romain", "Chloé", "Samir", "Laura", "Mathieu", "Yasmine", "Olivier", "Emma", "Rachid",
    "Julie", "Vincent", "Salma", "Benoît", "Marion", "Hamza", "Céline", "Sébastien", "Nour", "Alexandre",
]
LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Lefebvre", "Moreau", "Laurent", "Garcia", "Benali", "Roux", "Fournier",
    "Girard", "Bonnet", "Mercier", "Haddad", "Lambert", "Fontaine", "Rousseau", "Vincent", "Chevalier", "Mansouri",
    "Robin", "Gauthier", "Perrin", "Morel", "Brahimi", "Clément", "Nicolas", "Masson", "Henry", "Marchand",
    "Duval", "Denis", "Lemaire", "Trabelsi", "Faure", "André", "Mathieu", "Blanc", "Guerin", "Boyer",
]
HALL_NAMES = ["Turing", "Curie", "Pascal", "Lovelace", "Hopper", "Fermat", "Gauss", "Noether"]

FULL_TIME_LOAD = (6, 10)  # sessions/week (1h30 each)
PART_TIME_LOAD = (4, 6)
PART_TIME_RATE = 0.2
HALF_DAY_OFF_RATE = 0.3  # full-time teachers with one weekly half-day off (research, meetings)


@dataclass
class _TeacherDraft:
    id: str
    name: str
    capacity: int
    unavailable: list[int]
    load: int = 0
    pool: str = ""


@dataclass
class _Builder:
    rng: random.Random
    grid: GridConfig
    names: list[str]
    teachers: list[_TeacherDraft] = field(default_factory=list)

    def _half_days(self) -> list[list[int]]:
        """Morning / afternoon slot blocks of each day (afternoon = starting at 13:30 or later)."""
        blocks: list[list[int]] = []
        for slots in self.grid.slots_by_day:
            morning = [t for t in slots if self.grid.slots[t].slot.start < "13:30"]
            afternoon = [t for t in slots if self.grid.slots[t].slot.start >= "13:30"]
            blocks += [b for b in (morning, afternoon) if b]
        return blocks

    def new_teacher(self, pool: str) -> _TeacherDraft:
        rng = self.rng
        idx = len(self.teachers) + 1
        if rng.random() < PART_TIME_RATE:
            capacity = rng.randint(*PART_TIME_LOAD)
            days_off = rng.sample(range(self.grid.num_days), k=min(2, self.grid.num_days - 1))
            unavailable = sorted(t for d in days_off for t in self.grid.slots_by_day[d])
        else:
            capacity = rng.randint(*FULL_TIME_LOAD)
            unavailable = sorted(rng.choice(self._half_days())) if rng.random() < HALF_DAY_OFF_RATE else []
        draft = _TeacherDraft(id=f"T{idx:03d}", name=self.names[idx - 1], capacity=capacity,
                              unavailable=unavailable, pool=pool)
        self.teachers.append(draft)
        return draft

    def assign(self, pool: str, sessions: int) -> str:
        """Fill-first: first teacher of the subject pool with enough remaining capacity, else hire one."""
        for t in self.teachers:
            if t.pool == pool and t.capacity - t.load >= sessions:
                t.load += sessions
                return t.id
        t = self.new_teacher(pool)
        t.load += sessions
        return t.id


def _teacher_names(rng: random.Random, count: int) -> list[str]:
    pairs = [f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES]
    if count > len(pairs):
        raise ValueError(f"not enough names for {count} teachers")
    return rng.sample(pairs, k=count)


def _ceil_to(x: int, step: int) -> int:
    return step * math.ceil(x / step)


def _make_rooms(rng: random.Random, grid: GridConfig, groups: list[Group], courses: list[Course],
                tightness: float) -> list[Room]:
    by_id = {g.id: g for g in groups}
    rooms: list[Room] = []
    for rtype in (RoomType.CM, RoomType.TD, RoomType.TP):
        typed = [c for c in courses if c.room_type == rtype]
        if not typed:
            continue
        demand = sum(c.sessions_per_week for c in typed)
        count = max(1, math.ceil(demand / (grid.num_slots * tightness)))
        need = max(sum(by_id[g].size for g in c.group_ids) for c in typed)
        for i in range(count):
            capacity = _ceil_to(need, 10) + rng.choice([0, 10, 20])
            if rtype == RoomType.CM:
                rid, name = f"AMPHI-{i + 1}", f"Amphi {HALL_NAMES[i % len(HALL_NAMES)]}"
            elif rtype == RoomType.TD:
                rid = f"B{100 * (1 + i // 10) + i % 10 + 1}"
                name = f"Salle {rid}"
            else:
                rid = f"L{100 * (2 + i // 10) + i % 10 + 1}"
                name = f"Labo info {rid}"
            rooms.append(Room(id=rid, name=name, capacity=capacity, type=rtype))
    return rooms


def generate(size: str = "small", seed: int = 42, tightness: float = 0.75,
             grid: GridConfig | None = None) -> Instance:
    """Build a realistic instance. `tightness` = target room occupancy per room type (0 < t <= 1)."""
    if size not in PROFILES:
        raise ValueError(f"unknown size {size!r}, expected one of {sorted(PROFILES)}")
    if not 0 < tightness <= 1:
        raise ValueError("tightness must be in (0, 1]")
    profile = PROFILES[size]
    grid = grid or GridConfig()
    rng = random.Random(seed)

    groups: list[Group] = []
    courses: list[Course] = []
    # names drawn up-front so the teacher count does not shift the rest of the random stream
    builder = _Builder(rng=rng, grid=grid, names=_teacher_names(rng, 200))

    for level in profile.levels:
        group_ids: list[str] = []
        sub_ids: dict[str, list[str]] = {}
        promo_size = 0
        promo_groups: list[Group] = []
        for g in range(profile.groups_per_promo):
            gid = f"{level}-G{g + 1}"
            subs = []
            for s in range(profile.subgroups_per_group):
                sid = f"{gid}{chr(ord('a') + s)}"
                subs.append(Group(id=sid, name=sid, size=rng.randint(14, 18), parent=gid))
            gsize = sum(x.size for x in subs)
            promo_size += gsize
            promo_groups.append(Group(id=gid, name=gid, size=gsize, parent=level))
            promo_groups.extend(subs)
            group_ids.append(gid)
            sub_ids[gid] = [x.id for x in subs]
        groups.append(Group(id=level, name=f"Promo {level}", size=promo_size))
        groups.extend(promo_groups)

        subjects = rng.sample(CATALOG[level], k=profile.subjects_per_promo)
        subjects.sort(key=lambda s: s[0])
        for code, name, has_tp in subjects:
            pool = code
            courses.append(Course(id=f"{level}-{code}-CM", subject=name, teacher_id=builder.assign(pool, 1),
                                  group_ids=[level], room_type=RoomType.CM, sessions_per_week=1))
            for gid in group_ids:
                courses.append(Course(id=f"{level}-{code}-TD-{gid.split('-')[1]}", subject=name,
                                      teacher_id=builder.assign(pool, 1), group_ids=[gid],
                                      room_type=RoomType.TD, sessions_per_week=1))
            if has_tp:
                for gid in group_ids:
                    for sid in sub_ids[gid]:
                        courses.append(Course(id=f"{level}-{code}-TP-{sid.split('-')[1]}", subject=name,
                                              teacher_id=builder.assign(pool, 2), group_ids=[sid],
                                              room_type=RoomType.TP, sessions_per_week=2))

    teachers = [Teacher(id=t.id, name=t.name, unavailable=t.unavailable) for t in builder.teachers]
    rooms = _make_rooms(rng, grid, groups, courses, tightness)
    return Instance(name=f"{size}-s{seed}", grid=grid, teachers=teachers, rooms=rooms,
                    groups=groups, courses=courses)


# ------------------------------------------------------------------ infeasible variants

INFEASIBLE_KINDS = ("room_shortage", "teacher_availability")


def make_infeasible(instance: Instance, kind: str, seed: int = 0) -> Instance:
    """Return an infeasible copy of `instance` that still passes model validation.

    - room_shortage: too few labs for the lab sessions. Detectable by simple counting
      (lab sessions > labs x slots) — meant for quick pre-checks.
    - teacher_availability: two adjunct teachers, 1 session and the same single available
      slot each; one teaches a promotion's CM, the other a TD of one of its groups. Every
      volume check passes, but both sessions would need the same slot for the same students.
      Only the solver can detect it.
    """
    rng = random.Random(seed)
    data = instance.model_dump()
    n = instance.grid.num_slots

    if kind == "room_shortage":
        labs = [r for r in instance.rooms if r.type == RoomType.TP]
        demand = sum(c.sessions_per_week for c in instance.courses if c.room_type == RoomType.TP)
        keep = math.ceil(demand / n) - 1
        if keep < 1:
            raise ValueError(f"lab demand {demand} fits in one lab ({n} slots): cannot create a shortage")
        kept = sorted(labs, key=lambda r: (-r.capacity, r.id))[:keep]  # keep the largest: still compatible
        data["rooms"] = [r.model_dump() for r in instance.rooms if r.type != RoomType.TP] + \
                        [r.model_dump() for r in kept]

    elif kind == "teacher_availability":
        promos = sorted(g.id for g in instance.groups if g.parent is None and instance.children[g.id])
        candidates = []
        for p in promos:
            cms = sorted(c.id for c in instance.courses if c.group_ids == [p] and c.sessions_per_week == 1)
            tds = sorted(c.id for c in instance.courses
                         if len(c.group_ids) == 1 and instance.group_by_id[c.group_ids[0]].parent == p
                         and c.sessions_per_week == 1)
            if cms and tds:
                candidates.append((p, cms, tds))
        if not candidates:
            raise ValueError("no promotion with a 1-session CM and a 1-session TD of one of its groups")
        _, cms, tds = rng.choice(candidates)
        cm_id, td_id = rng.choice(cms), rng.choice(tds)
        slot = rng.choice([t for t in range(n) if t not in set(instance.grid.late_slots)])
        others = [t for t in range(n) if t != slot]
        data["teachers"] += [
            {"id": "V001", "name": "Hélène Vacataire-Morin", "unavailable": others},
            {"id": "V002", "name": "Marc Vacataire-Petit", "unavailable": others},
        ]
        for c in data["courses"]:
            if c["id"] == cm_id:
                c["teacher_id"] = "V001"
            elif c["id"] == td_id:
                c["teacher_id"] = "V002"
    else:
        raise ValueError(f"unknown kind {kind!r}, expected one of {INFEASIBLE_KINDS}")

    data["name"] = f"{instance.name}-{kind}"
    return Instance.model_validate(data)


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a timetabling instance")
    parser.add_argument("--size", choices=sorted(PROFILES), default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tightness", type=float, default=0.75)
    parser.add_argument("--infeasible", choices=INFEASIBLE_KINDS)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)

    inst = generate(args.size, args.seed, args.tightness)
    if args.infeasible:
        inst = make_infeasible(inst, args.infeasible, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    inst.save(args.output)
    print(f"{inst.name}: {len(inst.groups)} groups, {len(inst.teachers)} teachers, "
          f"{len(inst.rooms)} rooms, {len(inst.courses)} courses, "
          f"{sum(c.sessions_per_week for c in inst.courses)} sessions -> {args.output}")


if __name__ == "__main__":
    main()
