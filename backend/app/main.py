"""
FastAPI backend for the ambulance route-planning agent.

Large NetworkX objects are never returned. Responses use node IDs,
edge geometry, metrics and compact search traces.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import store
from .algorithms import run_algorithm
from .graph import EdgeOverlay
from .models import (
    CompareRequest,
    ExperimentRequest,
    MapLoadRequest,
    RouteRequest,
    SimulationAdvanceRequest,
    SimulationEventRequest,
    SimulationStartRequest,
    SnapRequest,
)
from .osm_loader import (
    DEFAULT_DIST_M,
    NAGPUR_CENTER,
    bbox_from_point,
    cache_path,
    load_from_cache,
    load_map,
    sample_waypoints,
)
from .scenarios import run_scenario, scenario_catalog
from .simulation import (
    advance,
    apply_event,
    replan,
    snapshot,
    start_simulation,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    cached = load_from_cache()
    if cached is not None:
        store.nagpur_graph = cached
        store.map_status = {
            "loaded": True,
            "message": (
                f"Loaded cached OSM graph: {len(cached.nodes)} nodes / {len(cached.edges)} edges."
            ),
            "source": cached.meta.get("source", "cache"),
            "warning": cached.meta.get("warning"),
        }
    yield


app = FastAPI(
    title="AI Ambulance Route Planning Agent",
    description=(
        "Search-based intelligent agent (BFS, DFS, Dijkstra, A*) on an OpenStreetMap "
        "road graph of Nagpur. Congestion is simulated — not live traffic."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _overlay_from_req(blocked: list[str], congestion: dict[str, float]) -> EdgeOverlay:
    ov = EdgeOverlay()
    for eid in blocked:
        ov.set_blocked(eid, True)
    for eid, m in congestion.items():
        ov.set_congestion(eid, m)
    return ov


def _resolve_endpoints(graph, req: RouteRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    if req.start_node and req.start_node in graph.nodes:
        s_node = graph.nodes[req.start_node]
        start_snap = {
            "node_id": s_node.id,
            "lat": s_node.lat,
            "lon": s_node.lon,
            "snap_distance_m": 0.0,
            "requested": {"lat": s_node.lat, "lon": s_node.lon},
        }
    elif req.start:
        start_snap = graph.snap(req.start.lat, req.start.lon)
    else:
        raise HTTPException(400, "Provide start coordinates or start_node.")

    if req.goal_node and req.goal_node in graph.nodes:
        g_node = graph.nodes[req.goal_node]
        goal_snap = {
            "node_id": g_node.id,
            "lat": g_node.lat,
            "lon": g_node.lon,
            "snap_distance_m": 0.0,
            "requested": {"lat": g_node.lat, "lon": g_node.lon},
        }
    elif req.goal:
        goal_snap = graph.snap(req.goal.lat, req.goal.lon)
    else:
        raise HTTPException(400, "Provide goal coordinates or goal_node.")
    return start_snap, goal_snap


def _pack_route(graph, result, overlay, start_snap, goal_snap, include_events: bool) -> dict[str, Any]:
    metrics = graph.path_metrics(result.path, overlay) if result.found else {}
    payload = result.to_dict(include_events=include_events)
    payload.update({
        "start_snap": start_snap,
        "goal_snap": goal_snap,
        "distance_m": metrics.get("distance_m"),
        "time_s": metrics.get("time_s"),
        "edge_ids": metrics.get("edge_ids") or [],
        "geometry": graph.path_geometry(result.path, overlay) if result.found else [],
        "cost_unit": "metres" if payload.get("algorithm") else "",
    })
    return payload


@app.get("/api/health")
def health() -> dict[str, Any]:
    g = store.nagpur_graph
    return {
        "status": "ok",
        "graph_loaded": g is not None,
        "nodes": 0 if g is None else len(g.nodes),
        "edges": 0 if g is None else len(g.edges),
        "map_status": store.map_status,
        "agent": "search-based planning agent (not a machine-learning model)",
    }


@app.get("/api/map/info")
def map_info() -> dict[str, Any]:
    g = store.nagpur_graph
    toy = store.toy_graph
    info: dict[str, Any] = {
        "center": NAGPUR_CENTER,
        "default_dist_m": DEFAULT_DIST_M,
        "loaded": g is not None,
        "status": store.map_status,
        "toy": toy.stats(),
        "tile_attribution": "© OpenStreetMap contributors",
        "traffic_disclaimer": (
            "OSM road data has no dependable live traffic speeds. "
            "Congestion controls in this project are simulated."
        ),
        "hospital_disclaimer": (
            "OSM extracts may not list every hospital. Choose any destination on the "
            "road network, or a sample waypoint. Names are approximate public areas."
        ),
        "toy_roads": toy.road_geojson(),
        "toy_samples": [
            {"id": "A", "label": "Toy start A", "kind": "start", "snap": {"node_id": "A", "lat": toy.nodes["A"].lat, "lon": toy.nodes["A"].lon, "snap_distance_m": 0.0}},
            {"id": "H", "label": "Toy goal H", "kind": "hospital", "snap": {"node_id": "H", "lat": toy.nodes["H"].lat, "lon": toy.nodes["H"].lon, "snap_distance_m": 0.0}},
        ],
    }
    if g is not None:
        info["nagpur"] = g.stats()
        info["samples"] = sample_waypoints(g)
        info["roads"] = g.road_geojson(max_features=50000)
    return info


@app.post("/api/map/snap")
def map_snap(req: SnapRequest) -> dict[str, Any]:
    try:
        graph = store.get_graph(req.graph_mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return graph.snap(req.lat, req.lon)


@app.post("/api/map/load")
def map_load(req: MapLoadRequest) -> dict[str, Any]:
    try:
        if req.use_cache_only:
            bbox = bbox_from_point(req.lat, req.lon, req.dist_m)
            graph = load_from_cache(cache_path(bbox))
            if graph is None:
                raise RuntimeError(
                    "No cached graph exists for this map radius. Load / download the city-wide map first."
                )
        else:
            graph = load_map(
                dist_m=req.dist_m,
                lat=req.lat,
                lon=req.lon,
                force_download=req.force_download,
            )
    except Exception as exc:  # noqa: BLE001
        store.map_status = {"loaded": store.nagpur_graph is not None, "message": str(exc), "source": None}
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    store.nagpur_graph = graph
    store.map_status = {
        "loaded": True,
        "message": f"Loaded {len(graph.nodes)} nodes / {len(graph.edges)} edges from {graph.meta.get('source')}.",
        "source": graph.meta.get("source"),
        "warning": graph.meta.get("warning"),
    }
    return {
        "ok": True,
        "stats": graph.stats(),
        "status": store.map_status,
        "samples": sample_waypoints(graph),
        "center": graph.meta.get("center") or NAGPUR_CENTER,
        "bbox": graph.meta.get("bbox"),
        "roads": graph.road_geojson(max_features=50000),
        "attribution": graph.meta.get("attribution"),
        "traffic_note": graph.meta.get("traffic_note"),
    }


@app.post("/api/route/calculate")
def route_calculate(req: RouteRequest) -> dict[str, Any]:
    try:
        graph = store.get_graph(req.graph_mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    start_snap, goal_snap = _resolve_endpoints(graph, req)
    overlay = _overlay_from_req(req.blocked_edges, req.congestion)
    result = run_algorithm(
        req.algorithm,
        graph,
        start_snap["node_id"],
        goal_snap["node_id"],
        graph.cost_fn(req.objective, overlay),
        overlay,
        graph.heuristic_fn(req.objective),
        max_events=req.max_events if req.include_events else 0,
    )
    packed = _pack_route(graph, result, overlay, start_snap, goal_snap, req.include_events)
    packed["objective"] = req.objective
    packed["cost_unit"] = "seconds (estimated)" if req.objective == "time" else "metres"
    packed["fairness_note"] = (
        "BFS and DFS do not optimise this cost; their cost is the weighted cost of whatever path they found."
        if req.algorithm in {"bfs", "dfs"}
        else "Dijkstra and A* optimise the selected objective with the same edge weights."
    )
    if not result.found:
        packed["error_hint"] = (
            "Destination unreachable from the snapped start (disconnected component, one-way restrictions, or blocked roads)."
        )
    return packed


@app.post("/api/route/compare")
def route_compare(req: CompareRequest) -> dict[str, Any]:
    try:
        graph = store.get_graph(req.graph_mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    start_snap, goal_snap = _resolve_endpoints(graph, req)
    overlay = _overlay_from_req(req.blocked_edges, req.congestion)
    rows = []
    for algo in req.algorithms:
        result = run_algorithm(
            algo,
            graph,
            start_snap["node_id"],
            goal_snap["node_id"],
            graph.cost_fn(req.objective, overlay),
            overlay,
            graph.heuristic_fn(req.objective),
            max_events=0,
        )
        packed = _pack_route(graph, result, overlay, start_snap, goal_snap, False)
        packed["objective"] = req.objective
        packed["cost_unit"] = "seconds (estimated)" if req.objective == "time" else "metres"
        rows.append(packed)

    astar_row = next((r for r in rows if r["algorithm"] == "astar" and r["found"]), None)
    dij_row = next((r for r in rows if r["algorithm"] == "dijkstra" and r["found"]), None)
    optimality = None
    if astar_row and dij_row and astar_row["cost"] is not None and dij_row["cost"] is not None:
        diff = abs(astar_row["cost"] - dij_row["cost"])
        optimality = {
            "astar_matches_dijkstra": diff <= 1e-2 * max(1.0, dij_row["cost"]),
            "cost_difference": round(diff, 4),
            "note": "On this graph A* and Dijkstra should match optimal cost when h is admissible.",
        }
    return {
        "objective": req.objective,
        "start_snap": start_snap,
        "goal_snap": goal_snap,
        "rows": rows,
        "optimality_check": optimality,
        "comparison_valid": True,
        "note": (
            "All algorithms used the same graph, start, goal, overlay and objective. "
            "Execution time is CPU search time, not UI animation time. "
            "BFS/DFS costs are not claimed as optimal."
        ),
    }


@app.post("/api/simulation/start")
def simulation_start(req: SimulationStartRequest) -> dict[str, Any]:
    try:
        graph = store.get_graph(req.graph_mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    start_snap, goal_snap = _resolve_endpoints(graph, req)
    overlay = _overlay_from_req(req.blocked_edges, req.congestion)
    sim, _ = start_simulation(
        graph,
        start_snap["node_id"],
        goal_snap["node_id"],
        req.algorithm,
        req.objective,
        req.replan_enabled,
        overlay,
        req.auto_block_after,
    )
    store.simulations[sim.id] = sim
    snap = snapshot(sim, graph)
    snap["start_snap"] = start_snap
    snap["goal_snap"] = goal_snap
    snap["graph_mode"] = req.graph_mode
    return snap


def _sim_graph(sim_id: str):
    sim = store.simulations.get(sim_id)
    if sim is None:
        raise HTTPException(404, "Unknown simulation id")
    mode = "toy" if sim.graph_name.startswith("toy") else "nagpur"
    try:
        return sim, store.get_graph(mode)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/simulation/{sim_id}")
def simulation_get(sim_id: str) -> dict[str, Any]:
    sim, graph = _sim_graph(sim_id)
    return snapshot(sim, graph)


@app.post("/api/simulation/{sim_id}/advance")
def simulation_advance(sim_id: str, req: SimulationAdvanceRequest) -> dict[str, Any]:
    sim, graph = _sim_graph(sim_id)
    return advance(sim, graph, req.steps)


class SimulationEventWithId(SimulationEventRequest):
    id: str


@app.post("/api/simulation/event")
def simulation_event_body(req: SimulationEventWithId) -> dict[str, Any]:
    return simulation_event(req.id, req)


@app.post("/api/simulation/{sim_id}/event")
def simulation_event(sim_id: str, req: SimulationEventRequest) -> dict[str, Any]:
    sim, graph = _sim_graph(sim_id)
    try:
        return apply_event(sim, graph, req.event_type, req.edge_id, req.congestion, req.auto_replan)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/simulation/replan")
def simulation_replan_body(payload: dict[str, str]) -> dict[str, Any]:
    sim_id = payload.get("id") or payload.get("sim_id")
    if not sim_id:
        raise HTTPException(400, "Provide id")
    return simulation_replan(sim_id)


@app.post("/api/simulation/{sim_id}/replan")
def simulation_replan(sim_id: str) -> dict[str, Any]:
    sim, graph = _sim_graph(sim_id)
    replan(sim, graph, reason="manual")
    return snapshot(sim, graph)


@app.get("/api/scenarios")
def scenarios() -> dict[str, Any]:
    return {"scenarios": scenario_catalog()}


@app.post("/api/experiments/run")
def experiments_run(req: ExperimentRequest) -> dict[str, Any]:
    graph = None
    if req.graph_mode == "nagpur":
        graph = store.nagpur_graph
    try:
        return run_scenario(req.scenario_id, graph)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/explanations")
def explanations() -> dict[str, Any]:
    return {
        "agent": (
            "This program is a goal-based search agent. Percepts are the road graph, "
            "the snapped start/goal, and simulated road events. Actions are selecting "
            "the next road segment. It is not trained on data."
        ),
        "state": "A state is a road-network node (intersection).",
        "action": "An action is traversing a directed edge to a neighbouring node.",
        "initial_state": "The OSM node nearest to the clicked ambulance origin.",
        "goal_state": "The OSM node nearest to the clicked destination.",
        "path_cost": "Sum of edge lengths (metres) or estimated travel times (seconds).",
        "open_list": "Frontier of generated but not yet expanded nodes (queue, stack or priority queue).",
        "closed_list": "Set of expanded nodes, used to avoid re-expansion / cycles.",
        "heuristic": (
            "h(n) is straight-line metres, or metres / 90 km/h for time. "
            "It is admissible because a road path cannot be shorter than the great-circle distance, "
            "and estimated speeds are ≤ 90 km/h."
        ),
        "dynamic": (
            "When an edge on the remaining route is blocked or slowed, the agent may re-run "
            "search from the current node. That is planning in a dynamic environment."
        ),
    }
