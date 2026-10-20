"use client";

import { Flip } from "gsap/Flip";
import { useMemo, useRef, useState } from "react";
import { Reveal } from "@/components/motion/reveal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { ancestors, conflictHighlight, describeSlot, slotRefs, type ViewMode } from "@/lib/planner";
import {
  type BenchmarkResult,
  type Conflict,
  CRITERIA,
  CRITERION_LABELS,
  type Explanation,
  type Instance,
  type ReplanResult,
  type Score,
  type Solution,
  type Weights,
} from "@/lib/types";
import { type GridAnimation, sessionKey, WeekGrid } from "./week-grid";

const DEFAULT_WEIGHTS: Weights = { student_gaps: 3, teacher_gaps: 1, late: 2, tp_split: 4, imbalance: 1, single_session_day: 2 };
const SAMPLES = [
  { id: "small", label: "Petite école" },
  { id: "medium", label: "Moyenne école" },
  { id: "large", label: "Grande école" },
];

interface RunInfo { label: string; status: string; score?: Score | null; time?: number; note?: string }

export function PlannerApp() {
  const [instance, setInstance] = useState<Instance | null>(null);
  const [solution, setSolution] = useState<Solution | null>(null);
  const [run, setRun] = useState<RunInfo | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [replan, setReplan] = useState<ReplanResult | null>(null);
  const [bench, setBench] = useState<BenchmarkResult | null>(null);
  const [moved, setMoved] = useState<Set<string>>(new Set());
  const [roomChanged, setRoomChanged] = useState<Set<string>>(new Set());
  const [flipIds, setFlipIds] = useState<Map<string, string>>(new Map());
  const [weights, setWeights] = useState<Weights>(DEFAULT_WEIGHTS);
  const [timeLimit, setTimeLimit] = useState(10);
  const [mode, setMode] = useState<ViewMode>("group");
  const [entityId, setEntityId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<Conflict | null>(null);
  const [announcedAt, setAnnouncedAt] = useState(0);
  const [animation, setAnimation] = useState<GridAnimation>({ kind: null, key: 0 });
  const [cascadeKey, setCascadeKey] = useState(0); // remounts the grid so the CSS cascade replays
  const flipState = useRef<Flip.FlipState | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);

  const highlight = useMemo(
    () => (instance && hover ? conflictHighlight(instance, hover, announcedAt) : null),
    [instance, hover, announcedAt],
  );

  async function action<T>(name: string, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(name);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function clearResults() {
    setSolution(null);
    setRun(null);
    setExplanation(null);
    setReplan(null);
    setBench(null);
    setMoved(new Set());
    setRoomChanged(new Set());
    setFlipIds(new Map());
    setHover(null);
  }

  function adoptInstance(inst: Instance) {
    clearResults();
    setInstance(inst);
    const leaf = inst.groups.find((g) => !inst.groups.some((o) => o.parent === g.id));
    setMode("group");
    setEntityId(leaf?.id ?? inst.groups[0]?.id ?? "");
  }

  function show(sol: Solution, info: RunInfo) {
    setSolution(sol);
    setRun(info);
    setReplan(null);
    setMoved(new Set());
    setRoomChanged(new Set());
    setFlipIds(new Map());
    setAnimation((a) => ({ kind: "cascade", key: a.key + 1 }));
    setCascadeKey((k) => k + 1);
  }

  const loadSample = (id: string) => action("load", async () => adoptInstance(await api.sample(id)));
  const generate = (body: { size: string; seed: number; tightness: number; infeasible: string | null }) =>
    action("load", async () => adoptInstance(await api.generate(body)));

  const solve = () =>
    action("solve", async () => {
      if (!instance) return;
      const res = await api.solve(instance, weights, timeLimit);
      setExplanation(null);
      if (res.feasible && res.solution) {
        const s = res.stats;
        const gap = typeof s.gap === "number" ? ` · écart à la borne ${(s.gap * 100).toFixed(0)} %` : "";
        const rooms = s.tp_blocks ? ` · ${s.same_room_blocks}/${s.tp_blocks} blocs de TP dans la même salle` : "";
        show(res.solution, { label: "CP-SAT", status: res.status, score: s.score, time: s.solve_time, note: `${gap}${rooms}` });
      } else {
        setSolution(null);
        setRun({ label: "CP-SAT", status: res.status });
        if (res.status === "INFEASIBLE") setExplanation(await api.explain(instance));
      }
    });

  const runGreedy = () =>
    action("greedy", async () => {
      if (!instance) return;
      const res = await api.greedy(instance, weights);
      show(res.solution, {
        label: "Glouton",
        status: res.unplaced.length ? `${res.unplaced.length} séance(s) non placée(s)` : "complet",
        score: res.score,
        time: res.time,
      });
    });

  const explainNow = () => action("explain", async () => instance && setExplanation(await api.explain(instance)));

  const runBenchmark = () => action("bench", async () => instance && setBench(await api.benchmark(instance, weights, timeLimit)));

  const doReplan = (teacherId: string, slots: number[], announced: number) =>
    action("replan", async () => {
      if (!instance || !solution) return;
      const res = await api.replan({ instance, solution, absence: { teacher_id: teacherId, slots }, announced_at: announced, weights, time_limit: timeLimit });
      setReplan(res);
      setAnnouncedAt(announced);
      if (!res.feasible || !res.solution) {
        setExplanation(res.explanation);
        return;
      }
      // Capture positions before React renders the new timetable: Flip animates from there.
      if (gridRef.current) flipState.current = Flip.getState(gridRef.current.querySelectorAll(".session"));
      const nextFlip = new Map<string, string>();
      const movedKeys = new Set<string>();
      const roomKeys = new Set<string>();
      for (const ch of res.changes) {
        const after = sessionKey(ch.course_id, ch.after_slot);
        if (ch.kind === "moved") {
          const before = sessionKey(ch.course_id, ch.before_slot);
          nextFlip.set(after, flipIds.get(before) ?? before);
          movedKeys.add(after);
        } else roomKeys.add(after);
      }
      for (const [k, v] of flipIds) if (!nextFlip.has(k) && !res.changes.some((c) => sessionKey(c.course_id, c.before_slot) === k)) nextFlip.set(k, v);
      setSolution(res.solution);
      setExplanation(null);
      setMoved(movedKeys);
      setRoomChanged(roomKeys);
      setFlipIds(nextFlip);
      setRun((r) => ({ label: "Replanification", status: res.status, score: r?.score ?? null, note: ` · score ${res.score_before} → ${res.score_after}` }));
      setAnimation((a) => ({ kind: "flip", key: a.key + 1 }));
    });

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-5 px-4 py-6">
      <Reveal className="flex flex-col gap-5">
        <div className="no-print flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="font-heading text-4xl">Planificateur</h1>
            <p className="text-sm text-muted-foreground">Charge ou génère une école, puis résous, explique et replanifie.</p>
          </div>
          {instance && <InstanceSummary instance={instance} />}
        </div>

        {error && (
          <p role="alert" className="no-print rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[20rem_minmax(0,1fr)] print:block">
          <aside className="no-print flex flex-col gap-4">
            <InstanceLoader busy={busy} onSample={loadSample} onGenerate={generate} />
            {instance && (
              <>
                <Card size="sm">
                  <CardHeader>
                    <CardTitle>Résolution</CardTitle>
                    <CardDescription>Limite de temps et poids des préférences.</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3">
                    <label className="flex items-center justify-between gap-2 text-sm">
                      Limite de temps
                      <select className="rounded-md border bg-background px-2 py-1" value={timeLimit} onChange={(e) => setTimeLimit(Number(e.target.value))}>
                        {[5, 10, 30, 60].map((s) => (
                          <option key={s} value={s}>{s} s</option>
                        ))}
                      </select>
                    </label>
                    {CRITERIA.map((k) => (
                      <label key={k} className="flex flex-col gap-0.5 text-sm">
                        <span className="flex justify-between">
                          {CRITERION_LABELS[k]} <span className="font-semibold tabular-nums">{weights[k]}</span>
                        </span>
                        <input type="range" min={0} max={10} value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} />
                      </label>
                    ))}
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button className="btn-shine" onClick={solve} disabled={busy !== null}>
                        {busy === "solve" ? `Résolution… (≤ ${timeLimit} s)` : "Résoudre (CP-SAT)"}
                      </Button>
                      <Button variant="outline" onClick={runGreedy} disabled={busy !== null}>Glouton</Button>
                      <Button variant="outline" onClick={explainNow} disabled={busy !== null}>
                        {busy === "explain" ? "Analyse…" : "Expliquer"}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
                {solution && <ReplanForm instance={instance} busy={busy} onReplan={doReplan} />}
                <Card size="sm">
                  <CardHeader>
                    <CardTitle>Benchmark</CardTitle>
                    <CardDescription>Glouton contre CP-SAT sur cette instance (même score).</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-2 text-sm">
                    <Button variant="outline" onClick={runBenchmark} disabled={busy !== null}>
                      {busy === "bench" ? "Comparaison…" : "Comparer"}
                    </Button>
                    {bench && <BenchmarkView bench={bench} />}
                  </CardContent>
                </Card>
              </>
            )}
          </aside>

          <section className="flex min-w-0 flex-col gap-4">
            {!instance ? (
              <Card>
                <CardContent className="py-10 text-center text-muted-foreground">Choisis une école à gauche pour commencer.</CardContent>
              </Card>
            ) : (
              <>
                <div className="no-print flex flex-wrap items-center justify-between gap-2">
                  <ViewToolbar instance={instance} mode={mode} entityId={entityId} onMode={setMode} onEntity={setEntityId} />
                  <ExportButtons instance={instance} solution={solution} mode={mode} entityId={entityId} onError={setError} />
                </div>
                <h2 className="hidden font-heading text-2xl print:block">
                  Emploi du temps · {entityLabel(instance, mode, entityId)} · {instance.name}
                </h2>
                {run && <RunBanner run={run} />}
                {replan?.feasible && <ChangesList replan={replan} />}
                {explanation && <ConflictsPanel explanation={explanation} instance={instance} onHover={setHover} hover={hover} />}
                <Card className="print-area">
                  <CardContent className="overflow-x-auto" data-lenis-prevent>
                    <WeekGrid
                      key={cascadeKey}
                      instance={instance}
                      solution={solution}
                      mode={mode}
                      entityId={entityId}
                      highlight={highlight}
                      moved={moved}
                      roomChanged={roomChanged}
                      flipIds={flipIds}
                      animation={animation}
                      flipState={flipState}
                      gridRef={gridRef}
                    />
                  </CardContent>
                </Card>
              </>
            )}
          </section>
        </div>
      </Reveal>
    </main>
  );
}

// ------------------------------------------------------------------ panels

function InstanceSummary({ instance }: { instance: Instance }) {
  const sessions = instance.courses.reduce((s, c) => s + c.sessions_per_week, 0);
  return (
    <div className="flex flex-wrap gap-1.5">
      <Badge variant="outline">{instance.name}</Badge>
      <Badge variant="secondary">{instance.groups.length} groupes</Badge>
      <Badge variant="secondary">{instance.teachers.length} profs</Badge>
      <Badge variant="secondary">{instance.rooms.length} salles</Badge>
      <Badge variant="secondary">{sessions} séances</Badge>
    </div>
  );
}

function InstanceLoader({ busy, onSample, onGenerate }: {
  busy: string | null;
  onSample: (id: string) => void;
  onGenerate: (body: { size: string; seed: number; tightness: number; infeasible: string | null }) => void;
}) {
  const [size, setSize] = useState("small");
  const [seed, setSeed] = useState(1);
  const [tightness, setTightness] = useState(0.75);
  const [infeasible, setInfeasible] = useState("");
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>École</CardTitle>
        <CardDescription>Exemples fournis ou instance générée.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-1.5">
          {SAMPLES.map((s) => (
            <Button key={s.id} size="sm" variant="secondary" disabled={busy !== null} onClick={() => onSample(s.id)}>
              {s.label}
            </Button>
          ))}
        </div>
        <details>
          <summary className="cursor-pointer font-medium">Générer</summary>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-0.5">Taille
              <select className="rounded-md border bg-background px-2 py-1" value={size} onChange={(e) => setSize(e.target.value)}>
                <option value="small">petite</option><option value="medium">moyenne</option><option value="large">grande</option>
              </select>
            </label>
            <label className="flex flex-col gap-0.5">Graine
              <input className="rounded-md border bg-background px-2 py-1" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            </label>
            <label className="flex flex-col gap-0.5">Occupation des salles
              <select className="rounded-md border bg-background px-2 py-1" value={tightness} onChange={(e) => setTightness(Number(e.target.value))}>
                <option value={0.75}>75 %</option><option value={0.9}>90 %</option><option value={1}>100 %</option>
              </select>
            </label>
            <label className="flex flex-col gap-0.5">Variante
              <select className="rounded-md border bg-background px-2 py-1" value={infeasible} onChange={(e) => setInfeasible(e.target.value)}>
                <option value="">résoluble</option>
                <option value="room_shortage">pénurie de labos</option>
                <option value="teacher_availability">vacataires en conflit</option>
              </select>
            </label>
          </div>
          <Button className="mt-2" size="sm" disabled={busy !== null} onClick={() => onGenerate({ size, seed, tightness, infeasible: infeasible || null })}>
            {busy === "load" ? "Chargement…" : "Générer"}
          </Button>
        </details>
      </CardContent>
    </Card>
  );
}

function ViewToolbar({ instance, mode, entityId, onMode, onEntity }: {
  instance: Instance; mode: ViewMode; entityId: string; onMode: (m: ViewMode) => void; onEntity: (id: string) => void;
}) {
  const options =
    mode === "group"
      ? instance.groups.map((g) => ({ id: g.id, label: `${" ".repeat(ancestors(instance, g.id).length)}${g.name} (${g.size})` }))
      : mode === "teacher"
        ? [...instance.teachers].sort((a, b) => a.name.localeCompare(b.name)).map((t) => ({ id: t.id, label: t.name }))
        : instance.rooms.map((r) => ({ id: r.id, label: `${r.name} · ${r.type} · ${r.capacity} places` }));
  const switchMode = (m: ViewMode) => {
    onMode(m);
    const first = m === "group" ? instance.groups[0]?.id : m === "teacher" ? instance.teachers[0]?.id : instance.rooms[0]?.id;
    onEntity(first ?? "");
  };
  return (
    <div className="no-print flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Vue" className="inline-flex overflow-hidden rounded-md border bg-card text-sm">
        {(["group", "teacher", "room"] as ViewMode[]).map((m) => (
          <button key={m} type="button" aria-pressed={mode === m} onClick={() => switchMode(m)}
            className="px-2.5 py-1 font-medium aria-pressed:bg-primary aria-pressed:text-primary-foreground">
            {{ group: "Groupe", teacher: "Prof", room: "Salle" }[m]}
          </button>
        ))}
      </div>
      <select aria-label="Filtre" className="min-w-56 rounded-md border bg-background px-2 py-1 text-sm" value={entityId} onChange={(e) => onEntity(e.target.value)}>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

function entityLabel(instance: Instance, mode: ViewMode, id: string): string {
  if (mode === "group") return instance.groups.find((g) => g.id === id)?.name ?? id;
  if (mode === "teacher") return instance.teachers.find((t) => t.id === id)?.name ?? id;
  return instance.rooms.find((r) => r.id === id)?.name ?? id;
}

/** PDF: browser print (A4 landscape, grid only, see @media print in globals.css). .ics: built by the API. */
function ExportButtons({ instance, solution, mode, entityId, onError }: {
  instance: Instance; solution: Solution | null; mode: ViewMode; entityId: string; onError: (m: string) => void;
}) {
  const [weeks, setWeeks] = useState(1);
  const downloadIcs = async () => {
    if (!solution) return;
    try {
      const blob = await api.exportIcs({ instance, solution, [mode]: entityId, weeks });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${entityLabel(instance, mode, entityId).replace(/[^\w.-]+/g, "_")}.ics`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Button variant="outline" size="sm" disabled={!solution} onClick={() => window.print()}>
        PDF (imprimer)
      </Button>
      <select aria-label="Semaines" className="rounded-md border bg-background px-2 py-1" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
        {[1, 4, 12, 15].map((w) => (
          <option key={w} value={w}>{w} semaine{w > 1 ? "s" : ""}</option>
        ))}
      </select>
      <Button variant="outline" size="sm" disabled={!solution} onClick={downloadIcs}>
        Exporter .ics
      </Button>
    </div>
  );
}

function RunBanner({ run }: { run: RunInfo }) {
  return (
    <div className="no-print flex flex-wrap items-center gap-2 text-sm">
      <Badge>{run.label}</Badge>
      <Badge variant={run.status === "INFEASIBLE" ? "destructive" : "outline"}>{run.status}</Badge>
      {run.score && <span>score <strong className="tabular-nums">{run.score.total}</strong></span>}
      {typeof run.time === "number" && <span className="text-muted-foreground">{run.time.toFixed(2)} s</span>}
      {run.note && <span className="text-muted-foreground">{run.note}</span>}
      {run.score && (
        <span className="flex flex-wrap gap-1">
          {CRITERIA.filter((k) => run.score!.breakdown[k] > 0).map((k) => (
            <Badge key={k} variant="secondary">{CRITERION_LABELS[k]} : {run.score!.breakdown[k]}</Badge>
          ))}
        </span>
      )}
    </div>
  );
}

function ConflictsPanel({ explanation, instance, onHover, hover }: {
  explanation: Explanation; instance: Instance; onHover: (c: Conflict | null) => void; hover: Conflict | null;
}) {
  const items = [...explanation.prechecks, ...explanation.core];
  const highlight = hover ? conflictHighlight(instance, hover) : null;
  const concerned = highlight ? instance.courses.filter((c) => highlight.courses.has(c.id)).slice(0, 24) : [];
  return (
    <Card size="sm" className={`no-print ${explanation.feasible ? "" : "ring-destructive/40"}`}>
      <CardHeader>
        <CardTitle>{explanation.feasible ? "Aucun conflit" : "Pourquoi il n'y a pas de solution"}</CardTitle>
        <CardDescription>
          {explanation.summary}
          {!explanation.feasible && ` ${explanation.minimal ? "Ensemble minimal prouvé" : "Minimalité non prouvée"} (${explanation.checks} vérifications, ${explanation.time} s).`}
        </CardDescription>
      </CardHeader>
      {items.length > 0 && (
        <CardContent className="flex flex-col gap-2">
          <ul className="flex flex-col gap-1.5" onMouseLeave={() => onHover(null)}>
            {items.map((c, i) => (
              <li key={`${c.family}-${c.entity}-${i}`}>
                <button
                  type="button"
                  onMouseEnter={() => onHover(c)}
                  onFocus={() => onHover(c)}
                  onBlur={() => onHover(null)}
                  className="w-full rounded-md border px-2.5 py-1.5 text-left text-sm hover:bg-accent focus-visible:bg-accent"
                >
                  <Badge variant={c.family.startsWith("precheck") ? "secondary" : "destructive"} className="mr-2">
                    {c.family.startsWith("precheck") ? "comptage" : c.family}
                  </Badge>
                  {c.message}
                </button>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">Survole une contrainte : les cours et créneaux concernés sont surlignés dans la grille.</p>
          {concerned.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {concerned.map((c) => (
                <span key={c.id} className="chip rounded border px-1.5 py-0.5 text-xs" data-hot>{c.subject} · {c.group_ids.join(", ")}</span>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function ReplanForm({ instance, busy, onReplan }: {
  instance: Instance; busy: string | null; onReplan: (teacher: string, slots: number[], announced: number) => void;
}) {
  const teachers = useMemo(() => [...instance.teachers].sort((a, b) => a.name.localeCompare(b.name)), [instance]);
  const refs = useMemo(() => slotRefs(instance), [instance]);
  const [teacher, setTeacher] = useState(teachers[0]?.id ?? "");
  const [days, setDays] = useState<number[]>([1]);
  const [announced, setAnnounced] = useState(0);
  const slots = refs.filter((r) => days.includes(r.day)).map((r) => r.index);
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Imprévu : prof absent</CardTitle>
        <CardDescription>Replanifie en déplaçant le moins de séances possible.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <select className="rounded-md border bg-background px-2 py-1" value={teacher} onChange={(e) => setTeacher(e.target.value)}>
          {teachers.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {instance.grid.days.map((d, i) => (
            <label key={d.name} className="flex items-center gap-1">
              <input type="checkbox" checked={days.includes(i)} onChange={(e) => setDays(e.target.checked ? [...days, i] : days.filter((x) => x !== i))} />
              {d.name}
            </label>
          ))}
        </div>
        <label className="flex flex-col gap-0.5">Annoncé
          <select className="rounded-md border bg-background px-2 py-1" value={announced} onChange={(e) => setAnnounced(Number(e.target.value))}>
            <option value={0}>avant la semaine</option>
            {refs.slice(1).map((r) => (
              <option key={r.index} value={r.index}>le {describeSlot(instance, r.index)} (passé figé)</option>
            ))}
          </select>
        </label>
        <Button disabled={busy !== null || slots.length === 0} onClick={() => onReplan(teacher, slots, announced)}>
          {busy === "replan" ? "Replanification…" : "Replanifier"}
        </Button>
      </CardContent>
    </Card>
  );
}

function ChangesList({ replan }: { replan: ReplanResult }) {
  return (
    <Card size="sm" className="no-print">
      <CardHeader>
        <CardTitle>
          {replan.sessions_moved} séance(s) déplacée(s) · minimum possible {replan.min_moves}
          {replan.rooms_changed ? ` · ${replan.rooms_changed} salle(s) changée(s)` : ""}
        </CardTitle>
        <CardDescription>
          {replan.frozen_sessions > 0 && `${replan.frozen_sessions} séance(s) passée(s) figée(s). `}Score {replan.score_before} → {replan.score_after}.
          Les séances déplacées sont surlignées dans la grille.
        </CardDescription>
      </CardHeader>
      {replan.changes.length > 0 && (
        <CardContent>
          <ul className="flex flex-col gap-1 text-sm">
            {replan.changes.map((c) => (
              <li key={`${c.course_id}-${c.after_slot}-${c.kind}`}>
                <strong>{c.course_id}</strong> : {c.before} → <span className="rounded bg-mark/60 px-1 text-[#1c2a4a]">{c.after}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      )}
    </Card>
  );
}

function BenchmarkView({ bench }: { bench: BenchmarkResult }) {
  const g = bench.greedy;
  const c = bench.cpsat;
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-muted-foreground">
        <tr><th /><th>Glouton</th><th>CP-SAT</th></tr>
      </thead>
      <tbody className="tabular-nums">
        <tr><th className="font-medium">Score</th><td>{g.score.total}</td><td>{c.score?.total ?? "-"}</td></tr>
        <tr><th className="font-medium">Temps</th><td>{g.time.toFixed(3)} s</td><td>{c.time.toFixed(2)} s</td></tr>
        <tr><th className="font-medium">Non placées</th><td>{g.unplaced}</td><td>{c.status === "INFEASIBLE" ? "infaisable" : 0}</td></tr>
        <tr><th className="font-medium">Statut</th><td>-</td><td>{c.status}</td></tr>
      </tbody>
    </table>
  );
}
