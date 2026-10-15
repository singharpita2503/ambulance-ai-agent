"""
Ambulance simulation with optional mid-journey A* re-planning.

The environment is dynamic: edges may become blocked or congested after
the initial plan. The agent is a search-based planner, not a learned policy.

If re-planning is disabled and the next remaining edge is blocked, the
ambulance stops at the last reachable junction. It never traverses a
blocked road.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .algorithms import SearchResult, run_algorithm
from .graph import EdgeOverlay, RoadGraph


@dataclass
class Simulation:
    id: str
    graph_name: str
    start: str
    goal: str
    algorithm: str
    objective: str
    replan_enabled: bool
    overlay: EdgeOverlay
    current_node: str
    remaining_path: list[str]
    travelled_path: list[str]
    initial_path: list[str]
    previous_remaining: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    replan_count: int = 0
    status: str = "ready"  # ready | running | stopped | arrived | failed
    last_search: Optional[dict[str, Any]] = None
    auto_block_after: Optional[int] = None
    auto_block_done: bool = False
    seed_note: str = ""


def _search(
    graph: RoadGraph,
    start: str,
    goal: str,
    algorithm: str,
    objective: str,
    overlay: EdgeOverlay,
    max_events: int = 2500,
) -> SearchResult:
    return run_algorithm(
        algorithm,
        graph,
        start,
        goal,
        graph.cost_fn(objective, overlay),
        overlay,
        graph.heuristic_fn(objective),
        max_events=max_events,
    )


def start_simulation(
    graph: RoadGraph,
    start: str,
    goal: str,
    algorithm: str,
    objective: str,
    replan_enabled: bool = True,
    overlay: Optional[EdgeOverlay] = None,
    auto_block_after: Optional[int] = None,
) -> tuple[Simulation, SearchResult]:
    overlay = overlay.clone() if overlay else EdgeOverlay()
    result = _search(graph, start, goal, algorithm, objective, overlay)
    sim = Simulation(
        id=str(uuid.uuid4()),
        graph_name=graph.name,
        start=start,
        goal=goal,
        algorithm=algorithm,
        objective=objective,
        replan_enabled=replan_enabled,
        overlay=overlay,
        current_node=start,
        remaining_path=list(result.path),
        travelled_path=[start],
        initial_path=list(result.path),
        last_search=result.to_dict(include_events=True),
        auto_block_after=auto_block_after,
        status="running" if result.found else "failed",
    )
    sim.events.append({
        "type": "plan",
        "found": result.found,
        "path": result.path,
        "cost": result.cost if result.found else None,
        "explored": result.explored,
        "execution_time_s": result.execution_time_s,
    })
    if not result.found:
        sim.events.append({"type": "fail", "reason": "No path from start to goal under current road conditions."})
    return sim, result


def remaining_affected(
    remaining_path: list[str],
    graph: RoadGraph,
    overlay: EdgeOverlay,
    changed_edge_id: Optional[str] = None,
) -> bool:
    """True if the remaining path is blocked or uses the changed edge."""
    for u, v in zip(remaining_path, remaining_path[1:]):
        edge = graph.find_edge(u, v, overlay)
        if edge is None:
            return True
        if changed_edge_id and edge.id == changed_edge_id:
            return True
    return False


def _edge_latlngs(edge) -> list[list[float]]:
    return [[float(lat), float(lon)] for lat, lon in (edge.geometry or [])]


def advance(sim: Simulation, graph: RoadGraph, steps: int = 1) -> dict[str, Any]:
    """Move the ambulance `steps` nodes along remaining_path (along real edges)."""
    moved = 0
    last_moved_geometry: list[list[float]] = []
    for _ in range(max(0, steps)):
        maybe_auto_block(sim, graph)
        if sim.status in {"arrived", "failed", "stopped"}:
            break
        if len(sim.remaining_path) <= 1:
            sim.status = "arrived" if sim.current_node == sim.goal else "failed"
            break
        nxt = sim.remaining_path[1]
        edge = graph.find_edge(sim.current_node, nxt, sim.overlay)
        if edge is None:
            if sim.replan_enabled:
                replan(sim, graph, reason="next_edge_blocked_or_missing")
                continue
            sim.status = "stopped"
            sim.events.append({
                "type": "stopped",
                "reason": "Next road is blocked and re-planning is disabled.",
                "at": sim.current_node,
            })
            break
        last_moved_geometry = _edge_latlngs(edge)
        sim.current_node = nxt
        sim.travelled_path.append(nxt)
        sim.remaining_path = sim.remaining_path[1:]
        moved += 1
        maybe_auto_block(sim, graph)
        if sim.current_node == sim.goal:
            sim.status = "arrived"
            sim.events.append({"type": "arrived", "at": sim.goal})
            break
    return snapshot(sim, graph) | {"moved": moved, "last_moved_geometry": last_moved_geometry}


def apply_event(
    sim: Simulation,
    graph: RoadGraph,
    event_type: str,
    edge_id: str,
    congestion: float = 1.0,
    auto_replan: bool = True,
) -> dict[str, Any]:
    if edge_id not in graph.edges:
        raise KeyError(f"Unknown edge {edge_id}")
    time_before = graph.path_metrics(sim.remaining_path, sim.overlay).get("time_s")
    if event_type == "block":
        sim.overlay.set_blocked(edge_id, True)
    elif event_type == "unblock":
        sim.overlay.set_blocked(edge_id, False)
    elif event_type == "congestion":
        sim.overlay.set_congestion(edge_id, congestion)
    else:
        raise ValueError("event_type must be block, unblock or congestion")

    affected = remaining_affected(sim.remaining_path, graph, sim.overlay, changed_edge_id=edge_id)
    record = {
        "type": "road_event",
        "event_type": event_type,
        "edge_id": edge_id,
        "congestion": sim.overlay.multiplier(edge_id),
        "blocked": sim.overlay.is_blocked(edge_id),
        "affected_remaining_route": affected,
        "at": sim.current_node,
        "remaining_time_before_s": None if time_before == float("inf") else time_before,
    }
    sim.events.append(record)

    replanned = False
    if affected and sim.replan_enabled and auto_replan and sim.status == "running":
        replan(sim, graph, reason=f"event:{event_type}")
        replanned = True
    elif affected and not sim.replan_enabled and event_type == "block":
        # No-replanning control: if the immediate next edge is blocked, stop.
        if len(sim.remaining_path) >= 2:
            nxt = sim.remaining_path[1]
            if graph.find_edge(sim.current_node, nxt, sim.overlay) is None:
                sim.status = "stopped"
                sim.events.append({
                    "type": "stopped",
                    "reason": "Blocked road ahead and re-planning disabled.",
                    "at": sim.current_node,
                })
    time_after = graph.path_metrics(sim.remaining_path, sim.overlay).get("time_s")
    record["remaining_time_after_s"] = None if time_after == float("inf") else time_after
    return snapshot(sim, graph) | {
        "affected": affected,
        "replanned": replanned,
        "remaining_time_before_s": record["remaining_time_before_s"],
        "remaining_time_after_s": record["remaining_time_after_s"],
    }


def maybe_auto_block(sim: Simulation, graph: RoadGraph) -> Optional[str]:
    """
    Deterministic automatic block: after `auto_block_after` travelled hops,
    block the next remaining edge that is not the final hop (if possible).
    """
    if sim.auto_block_done or sim.auto_block_after is None:
        return None
    hops = max(0, len(sim.travelled_path) - 1)
    if hops < sim.auto_block_after:
        return None
    if len(sim.remaining_path) < 3:
        return None
    u, v = sim.remaining_path[1], sim.remaining_path[2]
    edge = graph.edge_between_any(u, v)
    if edge is None:
        return None
    sim.auto_block_done = True
    apply_event(sim, graph, "block", edge.id, auto_replan=True)
    return edge.id


def replan(sim: Simulation, graph: RoadGraph, reason: str = "manual") -> SearchResult:
    sim.previous_remaining = list(sim.remaining_path)
    result = _search(graph, sim.current_node, sim.goal, sim.algorithm, sim.objective, sim.overlay)
    sim.replan_count += 1
    sim.last_search = result.to_dict(include_events=True)
    if result.found:
        sim.remaining_path = list(result.path)
        sim.status = "running"
        sim.events.append({
            "type": "replan",
            "reason": reason,
            "from": sim.current_node,
            "found": True,
            "path": result.path,
            "cost": result.cost,
            "explored": result.explored,
            "execution_time_s": result.execution_time_s,
            "count": sim.replan_count,
        })
    else:
        sim.status = "failed"
        sim.remaining_path = [sim.current_node]
        sim.events.append({
            "type": "replan",
            "reason": reason,
            "from": sim.current_node,
            "found": False,
            "message": "No alternative route exists from the current junction.",
            "count": sim.replan_count,
        })
    return result


def snapshot(sim: Simulation, graph: RoadGraph) -> dict[str, Any]:
    remaining_metrics = graph.path_metrics(sim.remaining_path, sim.overlay)
    travelled_metrics = graph.path_metrics(sim.travelled_path, sim.overlay)
    return {
        "id": sim.id,
        "status": sim.status,
        "algorithm": sim.algorithm,
        "objective": sim.objective,
        "replan_enabled": sim.replan_enabled,
        "replan_count": sim.replan_count,
        "current_node": sim.current_node,
        "start": sim.start,
        "goal": sim.goal,
        "current": {
            "id": sim.current_node,
            "lat": graph.nodes[sim.current_node].lat,
            "lon": graph.nodes[sim.current_node].lon,
        },
        "remaining_path": sim.remaining_path,
        "travelled_path": sim.travelled_path,
        "initial_path": sim.initial_path,
        "previous_remaining": sim.previous_remaining,
        "remaining_geometry": graph.path_geometry(sim.remaining_path, sim.overlay),
        "previous_geometry": graph.path_geometry(sim.previous_remaining),
        "travelled_geometry": graph.path_geometry(sim.travelled_path),
        "distance_travelled_m": travelled_metrics.get("distance_m") if travelled_metrics.get("reachable") else 0.0,
        "remaining_distance_m": remaining_metrics.get("distance_m") if remaining_metrics.get("reachable") else None,
        "remaining_time_s": remaining_metrics.get("time_s") if remaining_metrics.get("reachable") else None,
        "blocked_edges": sorted(eid for eid, v in sim.overlay.blocked.items() if v),
        "congestion": dict(sim.overlay.congestion),
        "events": sim.events,
        "last_search": sim.last_search,
        "completed": sim.status == "arrived",
        "failed": sim.status in {"failed", "stopped"},
        "next_edge_geometry": (
            graph.path_geometry(sim.remaining_path[:2], sim.overlay)
            if len(sim.remaining_path) >= 2
            else []
        ),
    }


def compare_replan_vs_control(
    graph: RoadGraph,
    start: str,
    goal: str,
    algorithm: str,
    objective: str,
    block_edge_id: Optional[str] = None,
    block_after_hops: int = 1,
    congestion_edge_id: Optional[str] = None,
    congestion: float = 1.0,
) -> dict[str, Any]:
    """
    Run the same scenario twice: with re-planning and without.
    Temporary edge changes are isolated in overlays (graph is not mutated).
    """
    def run(replan_enabled: bool) -> dict[str, Any]:
        overlay = EdgeOverlay()
        sim, initial = start_simulation(
            graph, start, goal, algorithm, objective, replan_enabled, overlay, auto_block_after=None
        )
        if not initial.found:
            return snapshot(sim, graph) | {"initial_found": False}
        # Travel `block_after_hops`, then apply the event, then try to finish.
        advance(sim, graph, steps=block_after_hops)
        if block_edge_id:
            apply_event(sim, graph, "block", block_edge_id, auto_replan=replan_enabled)
        if congestion_edge_id:
            apply_event(sim, graph, "congestion", congestion_edge_id, congestion=congestion, auto_replan=replan_enabled)
        # Attempt to consume the rest of the path (capped).
        for _ in range(len(graph.nodes) + 5):
            if sim.status != "running":
                break
            before = sim.current_node
            advance(sim, graph, steps=1)
            if sim.current_node == before and sim.status == "running":
                break
        snap = snapshot(sim, graph)
        snap["initial_found"] = True
        snap["initial_cost"] = initial.cost
        return snap

    with_replan = run(True)
    without = run(False)
    return {
        "with_replanning": with_replan,
        "without_replanning": without,
        "note": (
            "Both runs use the same graph, start, goal, algorithm, objective and event. "
            "Execution times are search times, not animation times."
        ),
    }
