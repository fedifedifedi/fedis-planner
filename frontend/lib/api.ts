import type { BenchmarkResult, Explanation, Instance, ReplanResult, Solution, SolveResponse, Weights } from "@/lib/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(`API injoignable (${API_URL}). Lance le backend : cd backend; .venv\\Scripts\\python.exe -m uvicorn api.main:app`);
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const json = JSON.parse(text);
      detail = typeof json.detail === "string" ? json.detail : (json.detail?.[0]?.msg ?? text);
    } catch {
      // plain-text error
    }
    throw new Error(`Erreur ${res.status} : ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  sample: (name: string) => request<Instance>(`/instances/samples/${name}`),
  generate: (body: { size: string; seed: number; tightness: number; infeasible?: string | null }) =>
    request<Instance>("/instances/generate", body),
  solve: (instance: Instance, weights: Weights, time_limit: number) =>
    request<SolveResponse>("/solve", { instance, weights, time_limit }),
  greedy: (instance: Instance, weights: Weights) =>
    request<{ solution: Solution; unplaced: { course_id: string; session: number }[]; time: number; score: SolveResponse["stats"]["score"] }>(
      "/greedy",
      { instance, weights },
    ),
  explain: (instance: Instance) => request<Explanation>("/explain", { instance }),
  replan: (body: { instance: Instance; solution: Solution; absence: { teacher_id: string; slots: number[] }; announced_at: number; weights: Weights; time_limit: number }) =>
    request<ReplanResult>("/replan", body),
  benchmark: (instance: Instance, weights: Weights, time_limit: number) =>
    request<BenchmarkResult>("/benchmark", { instance, weights, time_limit }),
  /** .ics file (RFC 5545, built by the backend) for the current filter; returns the file as a Blob. */
  exportIcs: async (body: { instance: Instance; solution: Solution; group?: string; teacher?: string; room?: string; weeks?: number }) => {
    const res = await fetch(`${API_URL}/export/ics`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`Erreur ${res.status} : ${await res.text()}`);
    return res.blob();
  },
};
