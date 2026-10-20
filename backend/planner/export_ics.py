"""iCalendar (.ics, RFC 5545) export of a timetable, written by hand (no library).

Day i of the grid is mapped to week_start + i days (week_start should be a Monday for the default
grid). Times are "floating" local times (no VTIMEZONE): the calendar shows them as-is.
Optional weekly recurrence (RRULE) over `weeks` weeks.
"""

from __future__ import annotations

from datetime import date, timedelta

from planner.model import Instance, Solution


def related_course_ids(instance: Instance, *, group: str | None = None, teacher: str | None = None) -> set[str]:
    """Courses visible in a group's timetable: the group, its ancestors and its descendants."""
    if group is not None:
        family = {group, *instance.ancestors(group)}
        stack = [group]
        while stack:
            for child in instance.children[stack.pop()]:
                family.add(child)
                stack.append(child)
        return {c.id for c in instance.courses if family & set(c.group_ids)}
    if teacher is not None:
        return {c.id for c in instance.courses if c.teacher_id == teacher}
    return set(instance.course_by_id)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Fold lines longer than 75 octets (RFC 5545 §3.1)."""
    out, current = [], ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return "\r\n".join(out)


def to_ics(instance: Instance, solution: Solution, week_start: date, *, group: str | None = None,
           teacher: str | None = None, room: str | None = None, weeks: int = 1,
           stamp: str = "20260101T000000Z") -> str:
    grid = instance.grid
    visible = related_course_ids(instance, group=group, teacher=teacher)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Fedi's Planner//FR", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_escape(instance.name)}"]
    for a in sorted(solution.assignments, key=lambda a: (a.slot, a.course_id)):
        if a.course_id not in visible or (room is not None and a.room_id != room):
            continue
        c = instance.course_by_id[a.course_id]
        ref = grid.slots[a.slot]
        day = week_start + timedelta(days=ref.day)
        start = ref.slot.start.replace(":", "") + "00"
        end = ref.slot.end.replace(":", "") + "00"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{a.course_id}-{a.session}-{day:%Y%m%d}@fedis-planner",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{day:%Y%m%d}T{start}",
            f"DTEND:{day:%Y%m%d}T{end}",
            f"SUMMARY:{_escape(f'{c.subject} ({c.room_type.value})')}",
            f"LOCATION:{_escape(instance.room_by_id[a.room_id].name)}",
            f"DESCRIPTION:{_escape(f'{instance.teacher_by_id[c.teacher_id].name} — ' + ', '.join(c.group_ids))}",
        ]
        if weeks > 1:
            lines.append(f"RRULE:FREQ=WEEKLY;COUNT={weeks}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
