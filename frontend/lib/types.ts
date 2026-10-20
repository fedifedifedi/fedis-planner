// Mirrors of the backend Pydantic models (backend/planner/*.py).

export type RoomType = "CM" | "TD" | "TP";

export interface TimeSlot { start: string; end: string; late: boolean }
export interface Day { name: string; slots: TimeSlot[] }
export interface Grid { days: Day[]; max_break_minutes: number }
export interface Teacher { id: string; name: string; unavailable: number[] }
export interface Room { id: string; name: string; capacity: number; type: RoomType }
export interface Group { id: string; name: string; size: number; parent: string | null }
export interface Course {
  id: string;
  subject: string;
  teacher_id: string;
  group_ids: string[];
  room_type: RoomType;
  sessions_per_week: number;
  max_sessions_per_day: number;
}
export interface Instance { name: string; grid: Grid; teachers: Teacher[]; rooms: Room[]; groups: Group[]; courses: Course[] }

export interface Assignment { course_id: string; session: number; slot: number; room_id: string }
export interface Solution { assignments: Assignment[] }

export const CRITERIA = ["student_gaps", "teacher_gaps", "late", "tp_split", "imbalance", "single_session_day"] as const;
export type Criterion = (typeof CRITERIA)[number];
export type Weights = Record<Criterion, number>;

export const CRITERION_LABELS: Record<Criterion, string> = {
  student_gaps: "Trous des étudiants",
  teacher_gaps: "Trous des profs",
  late: "Créneaux tardifs",
  tp_split: "TP non consécutifs",
  imbalance: "Journées déséquilibrées",
  single_session_day: "Journée à une seule séance",
};

export interface Score { total: number; breakdown: Record<Criterion, number>; weights: Weights }

export interface SolveResponse {
  status: string;
  feasible: boolean;
  solution: Solution | null;
  stats: {
    variables?: number;
    solve_time?: number;
    room_time?: number | null;
    best_bound?: number | null;
    gap?: number | null;
    same_room_blocks?: number | null;
    tp_blocks?: number | null;
    score?: Score | null;
    [key: string]: unknown;
  };
}

export interface Conflict { family: string; entity: string; message: string; details: Record<string, unknown> }
export interface Explanation {
  feasible: boolean;
  summary: string;
  prechecks: Conflict[];
  core: Conflict[];
  minimal: boolean;
  checks: number;
  time: number;
}

export interface Change {
  course_id: string;
  kind: "moved" | "room";
  before_slot: number;
  before_room: string;
  after_slot: number;
  after_room: string;
  before: string;
  after: string;
}

export interface ReplanResult {
  status: string;
  feasible: boolean;
  solution: Solution | null;
  changes: Change[];
  sessions_moved: number | null;
  rooms_changed: number | null;
  min_moves: number;
  frozen_sessions: number;
  score_before: number | null;
  score_after: number | null;
  explanation: Explanation | null;
}

export interface BenchmarkResult {
  greedy: { time: number; unplaced: number; score: Score };
  cpsat: { status: string; time: number; best_bound: number | null; gap: number | null; score: Score | null };
}
