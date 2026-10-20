// Client-side helpers on an instance (mirrors of backend logic where needed).
import type { Conflict, Course, Instance } from "@/lib/types";

export interface SlotRef { index: number; day: number; position: number; dayName: string; start: string; end: string; late: boolean }

export function slotRefs(instance: Instance): SlotRef[] {
  const refs: SlotRef[] = [];
  instance.grid.days.forEach((day, d) =>
    day.slots.forEach((s, p) => refs.push({ index: refs.length, day: d, position: p, dayName: day.name, start: s.start, end: s.end, late: s.late })),
  );
  return refs;
}

export function describeSlot(instance: Instance, t: number): string {
  const ref = slotRefs(instance)[t];
  return ref ? `${ref.dayName} ${ref.start}-${ref.end}` : `créneau ${t}`;
}

export function ancestors(instance: Instance, groupId: string): string[] {
  const byId = new Map(instance.groups.map((g) => [g.id, g]));
  const chain: string[] = [];
  let parent = byId.get(groupId)?.parent ?? null;
  while (parent) {
    chain.push(parent);
    parent = byId.get(parent)?.parent ?? null;
  }
  return chain;
}

export function descendants(instance: Instance, groupId: string): string[] {
  const out: string[] = [];
  const stack = [groupId];
  while (stack.length) {
    const id = stack.pop()!;
    for (const g of instance.groups) if (g.parent === id) { out.push(g.id); stack.push(g.id); }
  }
  return out;
}

export type ViewMode = "group" | "teacher" | "room";

/** Courses shown in a group's timetable: the group, its ancestors and its descendants (same as export_ics.py). */
export function visibleCourses(instance: Instance, mode: ViewMode, id: string): Set<string> | null {
  if (mode === "teacher") return new Set(instance.courses.filter((c) => c.teacher_id === id).map((c) => c.id));
  if (mode === "group") {
    const family = new Set([id, ...ancestors(instance, id), ...descendants(instance, id)]);
    return new Set(instance.courses.filter((c) => c.group_ids.some((g) => family.has(g))).map((c) => c.id));
  }
  return null; // room: filtered on assignments
}

export function courseSize(instance: Instance, course: Course): number {
  const byId = new Map(instance.groups.map((g) => [g.id, g.size]));
  return course.group_ids.reduce((sum, g) => sum + (byId.get(g) ?? 0), 0);
}

/** Stable hue per subject, so a subject keeps its colour everywhere. */
export function subjectHue(subject: string): number {
  let h = 0;
  for (const ch of subject) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export interface Highlight { courses: Set<string>; slots: Set<number>; forbidden: Set<number> }

/** Courses and slots concerned by a conflict (for the hover highlight in the grid). */
export function conflictHighlight(instance: Instance, conflict: Conflict, announcedAt = 0): Highlight {
  const h: Highlight = { courses: new Set(), slots: new Set(), forbidden: new Set() };
  const n = slotRefs(instance).length;
  const add = (pred: (c: Course) => boolean) => instance.courses.filter(pred).forEach((c) => h.courses.add(c.id));
  switch (conflict.family) {
    case "availability": {
      add((c) => c.teacher_id === conflict.entity);
      const teacher = instance.teachers.find((t) => t.id === conflict.entity);
      teacher?.unavailable.forEach((t) => h.forbidden.add(t));
      for (let t = 0; t < n; t++) if (!h.forbidden.has(t)) h.slots.add(t);
      break;
    }
    case "teacher":
      add((c) => c.teacher_id === conflict.entity);
      break;
    case "students": {
      const groups = new Set((conflict.details.groups as string[] | undefined) ?? [conflict.entity]);
      add((c) => c.group_ids.some((g) => groups.has(g)));
      break;
    }
    case "room_capacity":
    case "precheck_rooms": {
      const [type, k] = conflict.entity.split(":");
      add((c) => c.room_type === type && courseSize(instance, c) >= Number(k));
      break;
    }
    case "max_per_day":
      h.courses.add(conflict.entity);
      break;
    case "past":
      for (let t = 0; t < announcedAt; t++) h.forbidden.add(t);
      break;
  }
  return h;
}
