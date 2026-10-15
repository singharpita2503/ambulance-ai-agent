"""
Reproducible baseline experiments.

Toy-graph scenarios are fully offline. Nagpur scenarios require a loaded OSM graph
and pick real edges from that graph at runtime (they do not invent roads).
"""

from __future__ import annotations

from typing import Any, Optional

from .graph import EdgeOverlay, RoadGraph
from .simulation import compare_replan_vs_control, start_simulation, apply_event, advance
from .algorithms import run_algorithm
from .toy_graph import build_toy_graph, disconnected_toy


def scenario_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "normal",
            "title": "Normal road conditions",
            "graph": "toy",
            "description": "A to H with no blocks. Optimal distance is 11 m via A-E-F-G-H.",
        },
        {
            "id": "blocked_before",
            "title": "One road blocked before departure",
            "graph": "toy",
            "description": "Edge E→F is blocked before search. Planner must avoid it.",
        },
        {
            "id": "blocked_during",
            "title": "Road blocked during the journey",
            "graph": "toy",
            "description": "Ambulance starts A-E-F-G-H. After reaching E, F→G is blocked.",
        },
        {
            "id": "congestion",
            "title": "Increased congestion on the planned route",
            "graph": "toy",
            "description": "F→G congestion ×5. Re-planning may choose another time-optimal path.",
        },
        {
            "id": "no_alternative",
            "title": "No alternative route available",
            "graph": "toy",
            "description": "All roads into H except G→H remain, but G→H is blocked after leaving G's predecessors.",
        },
        {
            "id": "disconnected",
            "title": "Start and destination disconnected",
            "graph": "toy-disconnected",
            "description": "A cannot reach Y. Agent must report failure, not arrival.",
        },
    ]


def run_scenario(scenario_id: str, graph: Optional[RoadGraph] = None) -> dict[str, Any]:
    sid = scenario_id.strip().lower()
    if sid == "normal":
        g = build_toy_graph()
        return _compare_all(g, "A", "H", EdgeOverlay(), "Normal conditions")
    if sid == "blocked_before":
        g = build_toy_graph()
        overlay = EdgeOverlay()
        overlay.set_blocked("E->F", True)
        overlay.set_blocked("F->E", True)
        return _compare_all(g, "A", "H", overlay, "E-F blocked before departure")
    if sid == "blocked_during":
        g = build_toy_graph()
        # After 1 hop (A->E), block F->G on the optimal remaining path.
        return compare_replan_vs_control(
            g, "A", "H", "astar", "distance",
            block_edge_id="F->G", block_after_hops=1,
        ) | {"title": "Blocked during journey (A* distance)"}
    if sid == "congestion":
        g = build_toy_graph()
        return compare_replan_vs_control(
            g, "A", "H", "astar", "time",
            congestion_edge_id="F->G", congestion=5.0, block_after_hops=1,
        ) | {"title": "Congestion on F→G (A* time)"}
    if sid == "no_alternative":
        g = build_toy_graph()
        overlay = EdgeOverlay()
        # Block every inbound edge to H.
        overlay.set_blocked("G->H", True)
        overlay.set_blocked("D->H", True)
        sim, res = start_simulation(g, "A", "H", "astar", "distance", True, overlay)
        return {
            "title": "No route to hospital",
            "found": res.found,
            "status": sim.status,
            "notes": "The agent must not claim arrival when H is unreachable.",
            "result": res.to_dict(include_events=False),
        }
    if sid == "disconnected":
        g = disconnected_toy()
        sim, res = start_simulation(g, "A", "Y", "astar", "distance", True, EdgeOverlay())
        return {
            "title": "Disconnected components",
            "found": res.found,
            "status": sim.status,
            "completed": sim.status == "arrived",
            "result": res.to_dict(include_events=False),
        }
    if sid.startswith("nagpur") and graph is not None:
        return _nagpur_demo(graph, sid)
    raise KeyError(f"Unknown scenario '{scenario_id}'")


def _compare_all(g: RoadGraph, start: str, goal: str, overlay: EdgeOverlay, title: str) -> dict[str, Any]:
    rows = []
    for algo in ("bfs", "dfs", "dijkstra", "astar"):
        for objective in ("distance", "time"):
            res = run_algorithm(
                algo, g, start, goal, g.cost_fn(objective, overlay), overlay, g.heuristic_fn(objective), max_events=200,
            )
            metrics = g.path_metrics(res.path, overlay) if res.found else {}
            rows.append({
                "algorithm": algo,
                "objective": objective,
                "found": res.found,
                "cost": None if not res.found else res.cost,
                "distance_m": metrics.get("distance_m"),
                "time_s": metrics.get("time_s"),
                "explored": res.explored,
                "execution_time_s": res.execution_time_s,
                "path": res.path,
                "notes": res.notes,
            })
    return {"title": title, "start": start, "goal": goal, "rows": rows}


def _nagpur_demo(graph: RoadGraph, sid: str) -> dict[str, Any]:
    nodes = list(graph.nodes)
    if len(nodes) < 4:
        raise RuntimeError("Nagpur graph is not loaded.")
    # Deterministic: first and last node by id are a poor pair; use geographic extremes.
    west = min(graph.nodes.values(), key=lambda n: n.lon)
    east = max(graph.nodes.values(), key=lambda n: n.lon)
    start, goal = west.id, east.id
    overlay = EdgeOverlay()
    res = run_algorithm("astar", graph, start, goal, graph.cost_fn("distance", overlay), overlay, graph.heuristic_fn("distance"), 400)
    return {
        "title": "Nagpur geographic west→east A* (distance)",
        "start": start,
        "goal": goal,
        "found": res.found,
        "result": res.to_dict(include_events=False),
        "metrics": graph.path_metrics(res.path, overlay) if res.found else {},
        "note": "This pair is a reproducible extreme of the current extract, not a named hospital.",
    }
