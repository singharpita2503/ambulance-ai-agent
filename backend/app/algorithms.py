"""
Classical AI uninformed and informed search on a road graph.

Each function has the same interface and returns a SearchResult.

Important teaching points
-------------------------
BFS  : FIFO queue; visit-when-enqueued. Optimal only for unweighted edge counts.
DFS  : stack + closed set. Finds a valid path if one exists, not generally optimal.
Dijkstra: priority queue on g(n). Optimal for non-negative edge weights.
A*   : f(n) = g(n) + h(n). Optimal if h is admissible (never overestimates)
       and consistent, and stale heap entries are discarded.

These implementations do NOT call NetworkX path finders.
"""

from __future__ import annotations

import heapq
import itertools
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .graph import CostFn, EdgeOverlay, RoadGraph


@dataclass
class SearchResult:
    algorithm: str
    path: list[str]
    cost: float
    explored: int
    events: list[dict[str, Any]]
    execution_time_s: float
    found: bool
    notes: str
    final_g: Optional[float] = None
    final_h: Optional[float] = None
    final_f: Optional[float] = None
    open_sample: list[dict[str, Any]] = field(default_factory=list)
    closed_sample: list[str] = field(default_factory=list)
    truncated_events: bool = False

    def to_dict(self, include_events: bool = True) -> dict[str, Any]:
        data = {
            "algorithm": self.algorithm,
            "path": self.path,
            "cost": None if self.cost == float("inf") else round(self.cost, 4),
            "explored": self.explored,
            "execution_time_s": round(self.execution_time_s, 6),
            "found": self.found,
            "notes": self.notes,
            "final_g": None if self.final_g is None else round(self.final_g, 4),
            "final_h": None if self.final_h is None else round(self.final_h, 4),
            "final_f": None if self.final_f is None else round(self.final_f, 4),
            "open_sample": self.open_sample,
            "closed_sample": self.closed_sample,
            "truncated_events": self.truncated_events,
            "event_count": len(self.events),
        }
        if include_events:
            data["events"] = self.events
        return data


def _reconstruct(came_from: dict[str, str], start: str, goal: str) -> list[str]:
    if start == goal:
        return [start]
    if goal not in came_from and start != goal:
        return []
    path = [goal]
    cur = goal
    seen = set()
    while cur != start:
        if cur in seen:
            return []
        seen.add(cur)
        parent = came_from.get(cur)
        if parent is None:
            return []
        path.append(parent)
        cur = parent
    path.reverse()
    return path


def _record(
    events: list[dict[str, Any]],
    max_events: int,
    payload: dict[str, Any],
) -> bool:
    """Append an event. Returns True if the log was truncated (no more stored)."""
    if len(events) >= max_events:
        return True
    events.append(payload)
    return False


def bfs(
    graph: RoadGraph,
    start: str,
    goal: str,
    cost_fn: CostFn,
    overlay: Optional[EdgeOverlay] = None,
    heuristic_fn: Optional[Callable[[str, str], float]] = None,
    max_events: int = 2500,
) -> SearchResult:
    """
    Breadth-First Search (uninformed).

    Data structure: FIFO queue.
    Closed/visited: a node is marked visited when it is enqueued, so each
    node is expanded at most once.

    Optimality: BFS returns a path with the fewest edges. That is optimal
    only when every edge has the same weight. On a real road network the
    displayed travel-time / distance cost of a BFS path may be worse than
    Dijkstra / A*.
    """
    t0 = time.perf_counter()
    notes = (
        "BFS minimises the number of road segments (unweighted). "
        "It does not guarantee the shortest distance or fastest time when edge costs differ."
    )
    events: list[dict[str, Any]] = []
    truncated = False
    if start not in graph.nodes or goal not in graph.nodes:
        return SearchResult("bfs", [], float("inf"), 0, events, time.perf_counter() - t0, False, "Unknown start or goal node.")
    if start == goal:
        truncated = _record(events, max_events, {"t": "goal", "n": start, "g": 0, "open": 0, "closed": 1})
        return SearchResult("bfs", [start], 0.0, 1, events, time.perf_counter() - t0, True, notes, 0.0, 0.0, 0.0)

    q: deque[str] = deque([start])
    visited = {start}
    came_from: dict[str, str] = {}
    explored = 0

    while q:
        node = q.popleft()
        explored += 1
        truncated = _record(
            events, max_events,
            {"t": "expand", "n": node, "open": len(q), "closed": len(visited)},
        ) or truncated
        if node == goal:
            path = _reconstruct(came_from, start, goal)
            metrics_cost = _path_cost(graph, path, cost_fn)
            return SearchResult(
                "bfs", path, metrics_cost, explored, events, time.perf_counter() - t0, True, notes,
                metrics_cost, truncated_events=truncated, closed_sample=list(visited)[:20],
            )
        for edge in graph.neighbors(node, overlay):
            if cost_fn(edge) == float("inf"):
                continue
            nxt = edge.v
            if nxt in visited:
                continue
            visited.add(nxt)  # mark when enqueued
            came_from[nxt] = node
            q.append(nxt)
            truncated = _record(
                events, max_events,
                {"t": "enqueue", "n": nxt, "via": node, "open": len(q), "closed": len(visited)},
            ) or truncated

    return SearchResult("bfs", [], float("inf"), explored, events, time.perf_counter() - t0, False, notes + " Goal unreachable.", truncated_events=truncated)


def dfs(
    graph: RoadGraph,
    start: str,
    goal: str,
    cost_fn: CostFn,
    overlay: Optional[EdgeOverlay] = None,
    heuristic_fn: Optional[Callable[[str, str], float]] = None,
    max_events: int = 2500,
) -> SearchResult:
    """
    Depth-First Search (uninformed).

    Data structure: LIFO stack.
    Closed set: a node is added when it is expanded (popped), which prevents
    cycles. DFS returns the first path that reaches the goal. That path is
    valid but not generally optimal in edge count, distance, or time.
    """
    t0 = time.perf_counter()
    notes = (
        "DFS explores one branch as far as possible. It can find a valid route "
        "but does not generally guarantee an optimal route under any cost model."
    )
    events: list[dict[str, Any]] = []
    truncated = False
    if start not in graph.nodes or goal not in graph.nodes:
        return SearchResult("dfs", [], float("inf"), 0, events, time.perf_counter() - t0, False, "Unknown start or goal node.")
    if start == goal:
        truncated = _record(events, max_events, {"t": "goal", "n": start, "g": 0, "open": 0, "closed": 1})
        return SearchResult("dfs", [start], 0.0, 1, events, time.perf_counter() - t0, True, notes, 0.0, 0.0, 0.0)

    stack: list[str] = [start]
    closed: set[str] = set()
    came_from: dict[str, str] = {}
    on_stack: set[str] = {start}
    explored = 0

    while stack:
        node = stack.pop()
        on_stack.discard(node)
        if node in closed:
            continue
        closed.add(node)
        explored += 1
        truncated = _record(
            events, max_events,
            {"t": "expand", "n": node, "open": len(stack), "closed": len(closed)},
        ) or truncated
        if node == goal:
            path = _reconstruct(came_from, start, goal)
            metrics_cost = _path_cost(graph, path, cost_fn)
            return SearchResult(
                "dfs", path, metrics_cost, explored, events, time.perf_counter() - t0, True, notes,
                metrics_cost, truncated_events=truncated, closed_sample=list(closed)[:20],
            )
        # Reverse neighbour order so the first listed road is tried first (deterministic).
        neigh = list(graph.neighbors(node, overlay))
        for edge in reversed(neigh):
            if cost_fn(edge) == float("inf"):
                continue
            nxt = edge.v
            if nxt in closed or nxt in on_stack:
                continue
            came_from[nxt] = node
            stack.append(nxt)
            on_stack.add(nxt)
            truncated = _record(
                events, max_events,
                {"t": "enqueue", "n": nxt, "via": node, "open": len(stack), "closed": len(closed)},
            ) or truncated

    return SearchResult("dfs", [], float("inf"), explored, events, time.perf_counter() - t0, False, notes + " Goal unreachable.", truncated_events=truncated)


def dijkstra(
    graph: RoadGraph,
    start: str,
    goal: str,
    cost_fn: CostFn,
    overlay: Optional[EdgeOverlay] = None,
    heuristic_fn: Optional[Callable[[str, str], float]] = None,
    max_events: int = 2500,
) -> SearchResult:
    """
    Dijkstra's algorithm (uniform-cost search).

    Data structure: min-heap ordered by g(n) = accumulated path cost.
    Relaxation: if a cheaper path to a node is found, g is updated and the
    node is pushed again. Stale heap entries (g worse than the best known)
    are discarded when popped.

    Optimality: guaranteed for graphs with non-negative edge costs.
    """
    t0 = time.perf_counter()
    notes = (
        "Dijkstra is optimal for non-negative edge costs. Here it optimises the "
        "same objective (distance or estimated time) as A*."
    )
    return _best_first(
        algorithm="dijkstra",
        graph=graph,
        start=start,
        goal=goal,
        cost_fn=cost_fn,
        overlay=overlay,
        heuristic_fn=lambda _n, _g: 0.0,
        notes=notes,
        max_events=max_events,
        t0=t0,
        use_heuristic=False,
    )


def astar(
    graph: RoadGraph,
    start: str,
    goal: str,
    cost_fn: CostFn,
    overlay: Optional[EdgeOverlay] = None,
    heuristic_fn: Optional[Callable[[str, str], float]] = None,
    max_events: int = 2500,
) -> SearchResult:
    """
    A* search (informed / heuristic search).

        f(n) = g(n) + h(n)

    g(n) : cost of the cheapest known path from start to n
    h(n) : estimated remaining cost from n to the goal
    f(n) : estimated total cost of the path through n

    Distance objective: h = straight-line (haversine) metres.
    Time objective:     h = straight-line metres / 90 km/h  (seconds).

    Assumptions for optimality
    --------------------------
    1. Edge costs are non-negative.
    2. h never overestimates the true remaining cost (admissible).
    3. Congestion multipliers are >= 1, so they cannot make travel faster
       than the 90 km/h heuristic bound.
    4. Stale priority-queue entries are ignored (g worse than g_best).
    5. Tie-break is deterministic (insertion counter, then node id).
    """
    t0 = time.perf_counter()
    if heuristic_fn is None:
        heuristic_fn = graph.heuristic_fn("distance")
    notes = (
        "A* is optimal when h is admissible and edge costs are non-negative. "
        "Straight-line distance never exceeds road distance, so the metre heuristic is admissible. "
        "The time heuristic divides that distance by 90 km/h, an upper bound on estimated road speed."
    )
    return _best_first(
        algorithm="astar",
        graph=graph,
        start=start,
        goal=goal,
        cost_fn=cost_fn,
        overlay=overlay,
        heuristic_fn=heuristic_fn,
        notes=notes,
        max_events=max_events,
        t0=t0,
        use_heuristic=True,
    )


def _best_first(
    algorithm: str,
    graph: RoadGraph,
    start: str,
    goal: str,
    cost_fn: CostFn,
    overlay: Optional[EdgeOverlay],
    heuristic_fn: Callable[[str, str], float],
    notes: str,
    max_events: int,
    t0: float,
    use_heuristic: bool,
) -> SearchResult:
    events: list[dict[str, Any]] = []
    truncated = False
    if start not in graph.nodes or goal not in graph.nodes:
        return SearchResult(algorithm, [], float("inf"), 0, events, time.perf_counter() - t0, False, "Unknown start or goal node.")

    h0 = heuristic_fn(start, goal) if use_heuristic else 0.0
    if start == goal:
        truncated = _record(events, max_events, {"t": "goal", "n": start, "g": 0, "h": h0, "f": h0, "open": 0, "closed": 1})
        return SearchResult(algorithm, [start], 0.0, 1, events, time.perf_counter() - t0, True, notes, 0.0, h0, h0)

    counter = itertools.count()
    # heap entries: (f, g, tie, node)
    heap: list[tuple[float, float, int, str]] = []
    g_best: dict[str, float] = {start: 0.0}
    came_from: dict[str, str] = {}
    closed: set[str] = set()
    heapq.heappush(heap, (h0, 0.0, next(counter), start))
    explored = 0
    last_open_sample: list[dict[str, Any]] = []

    while heap:
        f, g, _, node = heapq.heappop(heap)
        best = g_best.get(node, float("inf"))
        if g > best + 1e-9:
            continue  # stale heap entry (a cheaper g was already recorded)
        if node in closed:
            continue
        closed.add(node)
        explored += 1
        h = heuristic_fn(node, goal) if use_heuristic else 0.0
        truncated = _record(
            events,
            max_events,
            {
                "t": "expand",
                "n": node,
                "g": round(g, 4),
                "h": round(h, 4),
                "f": round(g + h, 4),
                "open": len(heap),
                "closed": len(closed),
            },
        ) or truncated
        if node == goal:
            path = _reconstruct(came_from, start, goal)
            last_open_sample = _open_sample(heap, g_best, heuristic_fn, goal, use_heuristic)
            return SearchResult(
                algorithm, path, g, explored, events, time.perf_counter() - t0, True, notes,
                g, h, g + h, last_open_sample, list(closed)[:25], truncated,
            )
        for edge in graph.neighbors(node, overlay):
            step = cost_fn(edge)
            if step == float("inf"):
                continue
            nxt = edge.v
            ng = g + step
            if ng + 1e-9 < g_best.get(nxt, float("inf")):
                g_best[nxt] = ng
                came_from[nxt] = node
                closed.discard(nxt)  # reopen if a cheaper path is found
                nh = heuristic_fn(nxt, goal) if use_heuristic else 0.0
                nf = ng + nh
                heapq.heappush(heap, (nf, ng, next(counter), nxt))
                truncated = _record(
                    events,
                    max_events,
                    {
                        "t": "enqueue",
                        "n": nxt,
                        "via": node,
                        "g": round(ng, 4),
                        "h": round(nh, 4),
                        "f": round(nf, 4),
                        "open": len(heap),
                        "closed": len(closed),
                    },
                ) or truncated

    return SearchResult(
        algorithm, [], float("inf"), explored, events, time.perf_counter() - t0, False,
        notes + " Goal unreachable.", truncated_events=truncated, closed_sample=list(closed)[:25],
    )


def _open_sample(
    heap: list[tuple[float, float, int, str]],
    g_best: dict[str, float],
    heuristic_fn: Callable[[str, str], float],
    goal: str,
    use_heuristic: bool,
    k: int = 8,
) -> list[dict[str, Any]]:
    items = []
    seen = set()
    for f, g, _, n in sorted(heap)[:40]:
        if n in seen:
            continue
        if g > g_best.get(n, float("inf")) + 1e-9:
            continue
        seen.add(n)
        h = heuristic_fn(n, goal) if use_heuristic else 0.0
        items.append({"n": n, "g": round(g, 3), "h": round(h, 3), "f": round(g + h, 3)})
        if len(items) >= k:
            break
    return items


def _path_cost(graph: RoadGraph, path: list[str], cost_fn: CostFn) -> float:
    if not path:
        return float("inf")
    total = 0.0
    for u, v in zip(path, path[1:]):
        edge = graph.edge_between_any(u, v)
        if edge is None:
            return float("inf")
        total += cost_fn(edge)
    return total


ALGORITHMS: dict[str, Callable[..., SearchResult]] = {
    "bfs": bfs,
    "dfs": dfs,
    "dijkstra": dijkstra,
    "astar": astar,
}


def run_algorithm(
    name: str,
    graph: RoadGraph,
    start: str,
    goal: str,
    cost_fn: CostFn,
    overlay: Optional[EdgeOverlay] = None,
    heuristic_fn: Optional[Callable[[str, str], float]] = None,
    max_events: int = 2500,
) -> SearchResult:
    key = name.lower().strip()
    if key not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm '{name}'. Choose bfs, dfs, dijkstra or astar.")
    h = heuristic_fn
    if h is None:
        # Infer units from a dummy: callers should pass the matching heuristic.
        h = graph.heuristic_fn("distance")
    return ALGORITHMS[key](graph, start, goal, cost_fn, overlay, h, max_events)
