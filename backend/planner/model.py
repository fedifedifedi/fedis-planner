"""Domain model: configurable grid, teachers, rooms, groups, courses, instance and solution."""

from __future__ import annotations

import re
from enum import Enum
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class RoomType(str, Enum):
    CM = "CM"  # lecture hall
    TD = "TD"  # tutorial room
    TP = "TP"  # lab


# --------------------------------------------------------------------------- grid


class TimeSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: str
    end: str
    late: bool = False

    @field_validator("start", "end")
    @classmethod
    def _check_format(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError(f"invalid time {v!r}, expected HH:MM")
        return v

    @model_validator(mode="after")
    def _check_order(self) -> TimeSlot:
        if _minutes(self.start) >= _minutes(self.end):
            raise ValueError(f"slot {self.start}-{self.end}: start must be before end")
        return self

    @property
    def label(self) -> str:
        return f"{self.start}-{self.end}"


class Day(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    slots: list[TimeSlot] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_no_overlap(self) -> Day:
        for a, b in zip(self.slots, self.slots[1:]):
            if _minutes(a.end) > _minutes(b.start):
                raise ValueError(f"{self.name}: slots {a.label} and {b.label} overlap or are unordered")
        return self


class SlotRef(BaseModel):
    """A slot located in the week: global index t, day index and position within the day."""

    model_config = ConfigDict(frozen=True)

    index: int
    day: int
    position: int
    day_name: str
    slot: TimeSlot


DEFAULT_SLOTS = [
    TimeSlot(start="08:30", end="10:00"),
    TimeSlot(start="10:10", end="11:40"),
    TimeSlot(start="11:50", end="13:20"),
    TimeSlot(start="14:00", end="15:30"),
    TimeSlot(start="15:40", end="17:10", late=True),
]


def default_days() -> list[Day]:
    weekdays = [Day(name=n, slots=DEFAULT_SLOTS) for n in ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi")]
    return weekdays + [Day(name="Samedi", slots=DEFAULT_SLOTS[:3])]


class GridConfig(BaseModel):
    """Week grid. Slots get a global index t = 0..num_slots-1, day after day."""

    model_config = ConfigDict(frozen=True)

    days: list[Day] = Field(default_factory=default_days, min_length=1)
    max_break_minutes: int = Field(default=15, ge=0, description="two adjacent slots are consecutive "
                                   "if the break between them is at most this long (lunch breaks a block)")

    @cached_property
    def slots(self) -> list[SlotRef]:
        refs: list[SlotRef] = []
        for d, day in enumerate(self.days):
            for p, s in enumerate(day.slots):
                refs.append(SlotRef(index=len(refs), day=d, position=p, day_name=day.name, slot=s))
        return refs

    @property
    def num_slots(self) -> int:
        return len(self.slots)

    @property
    def num_days(self) -> int:
        return len(self.days)

    @cached_property
    def slots_by_day(self) -> list[list[int]]:
        by_day: list[list[int]] = [[] for _ in self.days]
        for ref in self.slots:
            by_day[ref.day].append(ref.index)
        return by_day

    @property
    def late_slots(self) -> list[int]:
        return [ref.index for ref in self.slots if ref.slot.late]

    @cached_property
    def consecutive_pairs(self) -> frozenset[tuple[int, int]]:
        """(t, t+1) pairs on the same day whose break is <= max_break_minutes."""
        pairs = set()
        for day_slots in self.slots_by_day:
            for a, b in zip(day_slots, day_slots[1:]):
                gap = _minutes(self.slots[b].slot.start) - _minutes(self.slots[a].slot.end)
                if gap <= self.max_break_minutes:
                    pairs.add((a, b))
        return frozenset(pairs)

    @cached_property
    def full_days(self) -> list[int]:
        """Days having the maximum number of slots (Mon-Fri by default): used for day balance."""
        longest = max(len(d.slots) for d in self.days)
        return [i for i, d in enumerate(self.days) if len(d.slots) == longest]

    def describe(self, t: int) -> str:
        ref = self.slots[t]
        return f"{ref.day_name} {ref.slot.label}"


# ----------------------------------------------------------------------- entities


class Teacher(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    unavailable: list[int] = Field(default_factory=list, description="global slot indices")


class Room(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    capacity: int = Field(gt=0)
    type: RoomType


class Group(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    size: int = Field(gt=0)
    parent: str | None = None  # e.g. TP subgroup G1a -> G1


class Course(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    subject: str
    teacher_id: str
    group_ids: list[str] = Field(min_length=1)
    room_type: RoomType
    sessions_per_week: int = Field(ge=1, description="number of 1-slot sessions")
    max_sessions_per_day: int | None = Field(default=None, ge=1, description="default: 2 for TP, 1 otherwise")

    @model_validator(mode="before")
    @classmethod
    def _default_max_per_day(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("max_sessions_per_day") is None:
            data = {**data, "max_sessions_per_day": 2 if data.get("room_type") in (RoomType.TP, "TP") else 1}
        return data

    @property
    def is_lab(self) -> bool:
        return self.room_type == RoomType.TP


# ----------------------------------------------------------------------- instance


def _check_unique(kind: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise ValueError(f"duplicate {kind} id {i!r}")
        seen.add(i)


class Instance(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = "instance"
    grid: GridConfig = Field(default_factory=GridConfig)
    teachers: list[Teacher]
    rooms: list[Room]
    groups: list[Group]
    courses: list[Course]

    # ---- lookups

    @cached_property
    def teacher_by_id(self) -> dict[str, Teacher]:
        return {t.id: t for t in self.teachers}

    @cached_property
    def room_by_id(self) -> dict[str, Room]:
        return {r.id: r for r in self.rooms}

    @cached_property
    def group_by_id(self) -> dict[str, Group]:
        return {g.id: g for g in self.groups}

    @cached_property
    def course_by_id(self) -> dict[str, Course]:
        return {c.id: c for c in self.courses}

    def ancestors(self, group_id: str) -> list[str]:
        """Parent chain of a group, closest first (assumes no cycle)."""
        chain: list[str] = []
        parent = self.group_by_id[group_id].parent
        while parent is not None:
            chain.append(parent)
            parent = self.group_by_id[parent].parent
        return chain

    @cached_property
    def children(self) -> dict[str, list[str]]:
        kids: dict[str, list[str]] = {g.id: [] for g in self.groups}
        for g in self.groups:
            if g.parent is not None:
                kids[g.parent].append(g.id)
        return kids

    @cached_property
    def student_chains(self) -> list[frozenset[str]]:
        """One chain per leaf group: the leaf and all its ancestors.

        Students of a leaf attend every course of every group in its chain, so at any
        slot at most one session may involve a group of a given chain. Sibling subgroups
        (G1a, G1b) belong to different chains and may run in parallel.
        """
        return [frozenset([g.id, *self.ancestors(g.id)]) for g in self.groups if not self.children[g.id]]

    def course_size(self, course: Course) -> int:
        return sum(self.group_by_id[g].size for g in course.group_ids)

    def compatible_rooms(self, course: Course) -> list[Room]:
        size = self.course_size(course)
        return [r for r in self.rooms if r.type == course.room_type and r.capacity >= size]

    # ---- validation

    @model_validator(mode="after")
    def _validate(self) -> Instance:
        _check_unique("teacher", [t.id for t in self.teachers])
        _check_unique("room", [r.id for r in self.rooms])
        _check_unique("group", [g.id for g in self.groups])
        _check_unique("course", [c.id for c in self.courses])

        n = self.grid.num_slots
        for t in self.teachers:
            bad = [s for s in t.unavailable if not 0 <= s < n]
            if bad:
                raise ValueError(f"teacher {t.id}: unavailable slots {bad} outside grid 0..{n - 1}")

        self._validate_group_tree()
        self._validate_courses()
        self._validate_loads()
        return self

    def _validate_group_tree(self) -> None:
        groups = {g.id: g for g in self.groups}
        for g in self.groups:
            if g.parent is None:
                continue
            if g.parent not in groups:
                raise ValueError(f"group {g.id}: unknown parent {g.parent!r}")
            if g.size > groups[g.parent].size:
                raise ValueError(
                    f"group {g.id}: size {g.size} exceeds parent {g.parent} size {groups[g.parent].size}"
                )
        for g in self.groups:
            seen = {g.id}
            parent = g.parent
            while parent is not None:
                if parent in seen:
                    raise ValueError(f"cycle in group hierarchy involving {g.id!r}")
                seen.add(parent)
                parent = groups[parent].parent

    def _validate_courses(self) -> None:
        for c in self.courses:
            if c.teacher_id not in self.teacher_by_id:
                raise ValueError(f"course {c.id}: unknown teacher {c.teacher_id!r}")
            unknown = [g for g in c.group_ids if g not in self.group_by_id]
            if unknown:
                raise ValueError(f"course {c.id}: unknown groups {unknown}")
            if len(set(c.group_ids)) != len(c.group_ids):
                raise ValueError(f"course {c.id}: duplicate groups")
            for g in c.group_ids:
                overlap = set(self.ancestors(g)) & set(c.group_ids)
                if overlap:
                    raise ValueError(f"course {c.id}: group {g} and its ancestor {sorted(overlap)} both listed")
            if not self.compatible_rooms(c):
                raise ValueError(
                    f"course {c.id}: no {c.room_type.value} room with capacity >= {self.course_size(c)}"
                )
            per_day_cap = sum(min(c.max_sessions_per_day, len(d.slots)) for d in self.grid.days)
            if c.sessions_per_week > per_day_cap:
                raise ValueError(
                    f"course {c.id}: {c.sessions_per_week} sessions cannot fit with "
                    f"max {c.max_sessions_per_day}/day (week capacity {per_day_cap})"
                )

    def _validate_loads(self) -> None:
        """Necessary (not sufficient) volume checks; deeper conflicts are explained by explain.py."""
        n = self.grid.num_slots
        for t in self.teachers:
            load = sum(c.sessions_per_week for c in self.courses if c.teacher_id == t.id)
            available = n - len(set(t.unavailable))
            if load > available:
                raise ValueError(f"teacher {t.id}: {load} sessions but only {available} available slots")
        for chain in self.student_chains:
            load = sum(c.sessions_per_week for c in self.courses if chain & set(c.group_ids))
            if load > n:
                leaf = next(g for g in chain if not self.children[g])
                raise ValueError(f"group {leaf} (with ancestors): {load} sessions but only {n} slots")

    # ---- persistence

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Instance:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------- solution


class Assignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    course_id: str
    session: int = Field(ge=0, description="session number within the course, 0-based")
    slot: int = Field(ge=0, description="global slot index")
    room_id: str


class Solution(BaseModel):
    assignments: list[Assignment] = Field(default_factory=list)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Solution:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
