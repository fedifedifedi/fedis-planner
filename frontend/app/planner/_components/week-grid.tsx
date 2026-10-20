"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { Flip } from "gsap/Flip";
import { type CSSProperties, type RefObject, useMemo, useRef } from "react";
import { useReducedMotion } from "@/components/motion/use-reduced-motion";
import { type Highlight, slotRefs, subjectHue, type ViewMode, visibleCourses } from "@/lib/planner";
import type { Assignment, Instance, Solution } from "@/lib/types";

gsap.registerPlugin(useGSAP, Flip);

export type GridAnimation = { kind: "cascade" | "flip" | null; key: number };

export const sessionKey = (courseId: string, slot: number) => `${courseId}@${slot}`;

interface Props {
  instance: Instance;
  solution: Solution | null;
  mode: ViewMode;
  entityId: string;
  highlight: Highlight | null;
  moved: Set<string>; // sessionKey of moved sessions (after replanning)
  roomChanged: Set<string>;
  flipIds: Map<string, string>; // sessionKey -> Flip id of its previous position
  animation: GridAnimation;
  flipState: RefObject<Flip.FlipState | null>;
  gridRef: RefObject<HTMLDivElement | null>;
}

/**
 * Weekly grid. Animations (never required to see the content):
 * - "cascade" after a solve: sessions appear in week order (CSS, .cascade in globals.css; the parent remounts the grid);
 * - "flip" after a replan: moved sessions glide from their old slot to the new one (GSAP Flip).
 * The Flip safety timer jumps to the final position if frames do not run; nothing animates with prefers-reduced-motion.
 */
export function WeekGrid(props: Props) {
  const { instance, solution, mode, entityId, highlight, moved, roomChanged, flipIds, animation, flipState, gridRef } = props;
  const reduced = useReducedMotion();
  const refs = useMemo(() => slotRefs(instance), [instance]);
  const courses = useMemo(() => new Map(instance.courses.map((c) => [c.id, c])), [instance]);
  const teachers = useMemo(() => new Map(instance.teachers.map((t) => [t.id, t])), [instance]);
  const rooms = useMemo(() => new Map(instance.rooms.map((r) => [r.id, r])), [instance]);
  const lastKey = useRef(-1);

  const bySlot = useMemo(() => {
    const visible = visibleCourses(instance, mode, entityId);
    const map = new Map<number, Assignment[]>();
    for (const a of solution?.assignments ?? []) {
      if (visible ? !visible.has(a.course_id) : a.room_id !== entityId) continue;
      map.set(a.slot, [...(map.get(a.slot) ?? []), a]);
    }
    return map;
  }, [instance, solution, mode, entityId]);

  useGSAP(
    () => {
      const root = gridRef.current;
      if (!root || animation.key === lastKey.current) return;
      lastKey.current = animation.key;
      // Only the replanning glide uses GSAP (Flip), and only on moved sessions. The cascade is CSS (.cascade in
      // globals.css): a gsap.from would hide the sessions until frames run (same rule as LMAgent's Reveal).
      const movedEls = root.querySelectorAll<HTMLElement>(".session[data-moved]");
      const state = flipState.current;
      flipState.current = null;
      if (reduced || animation.kind !== "flip" || !state || movedEls.length === 0) return;
      const tween = Flip.from(state, { targets: movedEls, duration: 0.9, ease: "power2.inOut", absolute: true, zIndex: 5 });
      // Safety net: if frames do not run (background tab), jump to the final position.
      const safety = window.setTimeout(() => tween.progress(1), (tween.duration() + 1) * 1000);
      return () => window.clearTimeout(safety);
    },
    { dependencies: [animation.key, reduced], scope: gridRef },
  );

  const days = instance.grid.days;
  const rows = Math.max(...days.map((d) => d.slots.length));

  return (
    <div
      ref={gridRef}
      className={`print-area grid gap-1 text-xs ${animation.kind === "cascade" ? "cascade" : ""}`}
      style={{ gridTemplateColumns: `4.5rem repeat(${days.length}, minmax(0, 1fr))` }}
    >
      <span />
      {days.map((d) => (
        <span key={d.name} className="py-1 text-center text-[13px] font-semibold">
          {d.name}
        </span>
      ))}
      {Array.from({ length: rows }, (_, position) => {
        const labelDay = days.find((d) => d.slots[position]);
        const label = labelDay?.slots[position];
        return [
          <span key={`label-${position}`} className="flex flex-col justify-center pr-1 text-right text-[11px] leading-tight text-muted-foreground">
            <span>{label?.start}</span>
            <span>{label?.end}</span>
          </span>,
          ...days.map((day, d) => {
            const ref = refs.find((r) => r.day === d && r.position === position);
            if (!ref) return <span key={`${d}-${position}`} />;
            const items = bySlot.get(ref.index) ?? [];
            return (
              <div
                key={`${d}-${position}`}
                className="grid-cell flex min-h-16 flex-col gap-1 rounded-md bg-muted/40 p-1"
                data-hot={highlight?.slots.has(ref.index) || undefined}
                data-forbidden={highlight?.forbidden.has(ref.index) || undefined}
                title={`${ref.dayName} ${ref.start}-${ref.end}${ref.late ? " (tardif)" : ""}`}
              >
                {items.map((a) => {
                  const c = courses.get(a.course_id);
                  if (!c) return null;
                  const key = sessionKey(a.course_id, a.slot);
                  const hot = highlight ? highlight.courses.has(c.id) : false;
                  const detail =
                    mode === "group"
                      ? `${teachers.get(c.teacher_id)?.name ?? c.teacher_id} · ${rooms.get(a.room_id)?.name ?? a.room_id}`
                      : mode === "teacher"
                        ? `${c.group_ids.join(", ")} · ${rooms.get(a.room_id)?.name ?? a.room_id}`
                        : `${c.group_ids.join(", ")} · ${teachers.get(c.teacher_id)?.name ?? c.teacher_id}`;
                  return (
                    <div
                      key={key}
                      data-flip-id={flipIds.get(key) ?? key}
                      data-moved={moved.has(key) || undefined}
                      data-room-changed={roomChanged.has(key) || undefined}
                      data-hot={hot || undefined}
                      data-dim={(highlight !== null && highlight.courses.size > 0 && !hot) || undefined}
                      className="session rounded-md px-1.5 py-1 shadow-sm"
                      style={{ "--hue": subjectHue(c.subject), "--i": ref.index } as CSSProperties}
                      title={`${c.subject} (${c.room_type}) — ${detail}`}
                    >
                      <span className="flex items-center justify-between gap-1">
                        <span className="truncate font-semibold">{c.subject}</span>
                        <span className="shrink-0 rounded bg-black/5 px-1 text-[10px] font-semibold dark:bg-white/10">{c.room_type}</span>
                      </span>
                      <span className="block truncate opacity-80">{detail}</span>
                    </div>
                  );
                })}
              </div>
            );
          }),
        ];
      })}
    </div>
  );
}
