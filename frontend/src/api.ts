import type {
  CompareResponse,
  GraphMode,
  Health,
  MapInfo,
  RouteResult,
  SimulationSnapshot,
  Snap,
} from "./types";

const BASE = "";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!res.ok) {
    const detail =
      typeof body === "object" && body && "detail" in body
        ? JSON.stringify((body as { detail: unknown }).detail)
        : text;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return body as T;
}

export const api = {
  health: () => http<Health>("/api/health"),
  mapInfo: () => http<MapInfo>("/api/map/info"),
  explanations: () => http<Record<string, string>>("/api/explanations"),
  scenarios: () => http<{ scenarios: { id: string; title: string; description: string }[] }>("/api/scenarios"),
  snap: (body: { lat: number; lon: number; graph_mode: GraphMode }) =>
    http<Snap>("/api/map/snap", { method: "POST", body: JSON.stringify(body) }),
  loadMap: (body: { dist_m: number; force_download?: boolean; use_cache_only?: boolean }) =>
    http<MapInfo & { ok: boolean; stats: { node_count: number; edge_count: number } }>("/api/map/load", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  calculate: (body: Record<string, unknown>) =>
    http<RouteResult>("/api/route/calculate", { method: "POST", body: JSON.stringify(body) }),
  compare: (body: Record<string, unknown>) =>
    http<CompareResponse>("/api/route/compare", { method: "POST", body: JSON.stringify(body) }),
  startSim: (body: Record<string, unknown>) =>
    http<SimulationSnapshot>("/api/simulation/start", { method: "POST", body: JSON.stringify(body) }),
  advance: (id: string, steps = 1) =>
    http<SimulationSnapshot>(`/api/simulation/${id}/advance`, {
      method: "POST",
      body: JSON.stringify({ steps }),
    }),
  event: (id: string, body: Record<string, unknown>) =>
    http<SimulationSnapshot>(`/api/simulation/${id}/event`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  replan: (id: string) =>
    http<SimulationSnapshot>(`/api/simulation/${id}/replan`, { method: "POST", body: "{}" }),
  getSim: (id: string) => http<SimulationSnapshot>(`/api/simulation/${id}`),
  experiment: (scenario_id: string, graph_mode: GraphMode = "toy") =>
    http<Record<string, unknown>>("/api/experiments/run", {
      method: "POST",
      body: JSON.stringify({ scenario_id, graph_mode }),
    }),
};
