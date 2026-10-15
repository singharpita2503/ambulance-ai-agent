export type AlgorithmName = "bfs" | "dfs" | "dijkstra" | "astar";
export type ObjectiveName = "distance" | "time";
export type GraphMode = "nagpur" | "toy";
export type PickMode = "start" | "goal" | "block" | "congestion" | "idle";

export interface LatLon {
  lat: number;
  lon: number;
}

export interface Snap {
  node_id: string;
  lat: number;
  lon: number;
  snap_distance_m: number;
  requested?: LatLon;
}

export interface SearchEvent {
  t: string;
  n: string;
  g?: number;
  h?: number;
  f?: number;
  open?: number;
  closed?: number;
  via?: string;
}

export interface RouteResult {
  algorithm: string;
  path: string[];
  cost: number | null;
  explored: number;
  execution_time_s: number;
  found: boolean;
  notes: string;
  final_g?: number | null;
  final_h?: number | null;
  final_f?: number | null;
  open_sample?: { n: string; g: number; h: number; f: number }[];
  closed_sample?: string[];
  truncated_events?: boolean;
  event_count?: number;
  events?: SearchEvent[];
  start_snap?: Snap;
  goal_snap?: Snap;
  distance_m?: number | null;
  time_s?: number | null;
  edge_ids?: string[];
  geometry?: number[][];
  objective?: string;
  cost_unit?: string;
  fairness_note?: string;
  error_hint?: string;
}

export interface CompareResponse {
  objective: string;
  start_snap: Snap;
  goal_snap: Snap;
  rows: RouteResult[];
  optimality_check: {
    astar_matches_dijkstra: boolean;
    cost_difference: number;
    note: string;
  } | null;
  comparison_valid: boolean;
  note: string;
}

export interface SimulationSnapshot {
  id: string;
  status: string;
  algorithm: string;
  objective: string;
  replan_enabled: boolean;
  replan_count: number;
  current_node: string;
  start: string;
  goal: string;
  current: { id: string; lat: number; lon: number };
  remaining_path: string[];
  travelled_path: string[];
  initial_path: string[];
  previous_remaining: string[];
  remaining_geometry: number[][];
  previous_geometry: number[][];
  travelled_geometry: number[][];
  distance_travelled_m: number | null;
  remaining_distance_m: number | null;
  remaining_time_s: number | null;
  blocked_edges: string[];
  congestion: Record<string, number>;
  events: Record<string, unknown>[];
  last_search: RouteResult | null;
  completed: boolean;
  failed: boolean;
  affected?: boolean;
  replanned?: boolean;
  start_snap?: Snap;
  goal_snap?: Snap;
  last_moved_geometry?: number[][];
  next_edge_geometry?: number[][];
  remaining_time_before_s?: number | null;
  remaining_time_after_s?: number | null;
}

export interface SampleWaypoint {
  id: string;
  label: string;
  lat: number;
  lon: number;
  kind: string;
  snap: Snap;
}

export interface MapInfo {
  center: LatLon & { label?: string };
  default_dist_m: number;
  loaded: boolean;
  status: { loaded: boolean; message: string; source?: string | null; warning?: string };
  toy: { name: string; node_count: number; edge_count: number; meta: Record<string, unknown> };
  tile_attribution: string;
  traffic_disclaimer: string;
  hospital_disclaimer: string;
  nagpur?: { name: string; node_count: number; edge_count: number; meta: Record<string, unknown> };
  samples?: SampleWaypoint[];
  toy_samples?: SampleWaypoint[];
  roads?: { type: string; features: unknown[] };
  toy_roads?: { type: string; features: unknown[] };
}

export interface Health {
  status: string;
  graph_loaded: boolean;
  nodes: number;
  edges: number;
  map_status: MapInfo["status"];
  agent: string;
}
