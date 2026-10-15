"""Unit tests for BFS, DFS, Dijkstra and A* on known graphs."""

from __future__ import annotations

import math

from app.algorithms import astar, bfs, dfs, dijkstra, run_algorithm
from app.graph import Edge, EdgeOverlay, Node, RoadGraph, haversine_m
from app.toy_graph import build_toy_graph, disconnected_toy


def diamond() -> RoadGraph:
    """
    Geographic diamond: A-C-D is the short route, A-B-D is the long route.
    Edge lengths equal haversine so the straight-line heuristic is admissible.
    """
    g = RoadGraph("diamond")
    g.add_node(Node("A", 21.15000, 79.08000))
    g.add_node(Node("B", 21.15000, 79.08200))  # ~200 m east
    g.add_node(Node("C", 21.14980, 79.08000))  # ~22 m south
    g.add_node(Node("D", 21.14980, 79.08020))  # ~22 m east of C
    for u, v in [("A", "B"), ("B", "D"), ("A", "C"), ("C", "D")]:
        a, b = g.nodes[u], g.nodes[v]
        L = haversine_m(a.lat, a.lon, b.lat, b.lon)
        g.add_edge(Edge(f"{u}->{v}", u, v, L, speed_kmh=36.0))
        g.add_edge(Edge(f"{v}->{u}", v, u, L, speed_kmh=36.0))
    return g


def test_start_equals_goal():
    g = diamond()
    for name in ("bfs", "dfs", "dijkstra", "astar"):
        res = run_algorithm(name, g, "A", "A", g.cost_fn("distance"), None, g.heuristic_fn("distance"))
        assert res.found
        assert res.path == ["A"]
        assert res.cost == 0


def test_dijkstra_and_astar_weighted_optimum():
    g = diamond()
    ov = EdgeOverlay()
    d = dijkstra(g, "A", "D", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
    a = astar(g, "A", "D", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
    assert d.found and a.found
    assert d.path == ["A", "C", "D"]
    assert a.path == ["A", "C", "D"]
    expected = g.path_metrics(["A", "C", "D"])["distance_m"]
    assert math.isclose(d.cost, expected, rel_tol=1e-6)
    assert math.isclose(a.cost, d.cost, rel_tol=1e-6)


def test_bfs_fewest_edges_not_weighted_optimum():
    g = diamond()
    res = bfs(g, "A", "D", g.cost_fn("distance"), None, g.heuristic_fn("distance"))
    assert res.found
    # Both A-B-D and A-C-D have 2 edges; BFS may return either depending on adj order.
    assert len(res.path) == 3
    short = g.path_metrics(["A", "C", "D"])["distance_m"]
    long = g.path_metrics(["A", "B", "D"])["distance_m"]
    assert res.cost in {short, long} or math.isclose(res.cost, short) or math.isclose(res.cost, long)


def test_dfs_returns_valid_path_not_necessarily_optimal():
    g = diamond()
    res = dfs(g, "A", "D", g.cost_fn("distance"), None, g.heuristic_fn("distance"))
    assert res.found
    assert res.path[0] == "A" and res.path[-1] == "D"
    for u, v in zip(res.path, res.path[1:]):
        assert g.edge_between_any(u, v) is not None


def test_unreachable_goal():
    g = disconnected_toy()
    for name in ("bfs", "dfs", "dijkstra", "astar"):
        res = run_algorithm(name, g, "A", "Y", g.cost_fn("distance"), None, g.heuristic_fn("distance"))
        assert not res.found
        assert res.path == []
        assert res.cost == float("inf")


def test_blocked_edges_force_detour():
    g = diamond()
    ov = EdgeOverlay()
    ov.set_blocked("A->C", True)
    ov.set_blocked("C->A", True)
    d = dijkstra(g, "A", "D", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
    assert d.found
    assert d.path == ["A", "B", "D"]
    assert math.isclose(d.cost, g.path_metrics(["A", "B", "D"])["distance_m"], rel_tol=1e-6)


def test_congested_edges_affect_time_not_distance():
    g = diamond()
    ov = EdgeOverlay()
    ov.set_congestion("A->C", 50.0)
    ov.set_congestion("C->D", 50.0)
    dist = astar(g, "A", "D", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
    time_res = astar(g, "A", "D", g.cost_fn("time", ov), ov, g.heuristic_fn("time"))
    assert dist.path == ["A", "C", "D"]  # distance ignores congestion
    # Time should avoid the heavily slowed short path.
    assert time_res.found
    assert time_res.path == ["A", "B", "D"]


def test_heuristic_units_time_vs_distance():
    g = diamond()
    hd = g.heuristic_fn("distance")("A", "D")
    ht = g.heuristic_fn("time")("A", "D")
    a, d = g.nodes["A"], g.nodes["D"]
    straight = haversine_m(a.lat, a.lon, d.lat, d.lon)
    assert math.isclose(hd, straight, rel_tol=1e-6)
    assert ht < hd  # seconds vs metres for this tiny graph
    assert math.isclose(ht, straight / (90 / 3.6), rel_tol=1e-6)
    # Admissible: heuristic <= true remaining cost of optimal path (2 m).
    # For this geographic diamond the straight line may be close to 111 m;
    # admissibility is vs true *path* cost in the same units — for distance,
    # haversine(A,D) must be <= length of any path. 2 m of graph length with
    # ~157 m geographic separation would violate that, so this graph is schematic.
    # Check instead that h(goal, goal) is 0 and h is non-negative.
    assert hd >= 0 and ht >= 0
    assert g.heuristic_fn("distance")("D", "D") == 0
    true_dist = g.path_metrics(["A", "C", "D"])["distance_m"]
    assert hd <= true_dist + 1e-6  # admissible on this geographic graph


def test_toy_graph_optimal_distance_independently():
    g = build_toy_graph()
    ov = EdgeOverlay()
    # Independent verification: enumerate that A-E-F-G-H = 11 is cheaper than A-B-F-G-H = 12.
    m1 = g.path_metrics(["A", "E", "F", "G", "H"], ov)
    m2 = g.path_metrics(["A", "B", "F", "G", "H"], ov)
    m3 = g.path_metrics(["A", "B", "C", "D", "H"], ov)
    assert m1["reachable"] and m2["reachable"] and m3["reachable"]
    assert m1["distance_m"] < m2["distance_m"]
    assert m1["distance_m"] < m3["distance_m"]
    res = astar(g, "A", "H", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
    dij = dijkstra(g, "A", "H", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
    assert res.found and dij.found
    assert math.isclose(res.cost, m1["distance_m"], rel_tol=1e-6)
    assert math.isclose(dij.cost, res.cost, rel_tol=1e-6)
    assert res.path == ["A", "E", "F", "G", "H"]
    assert dij.path == res.path


def test_returned_route_follows_edges_and_cost_matches():
    g = build_toy_graph()
    ov = EdgeOverlay()
    for name in ("bfs", "dfs", "dijkstra", "astar"):
        res = run_algorithm(name, g, "A", "H", g.cost_fn("distance", ov), ov, g.heuristic_fn("distance"))
        assert res.found
        metrics = g.path_metrics(res.path, ov)
        assert metrics["reachable"]
        assert math.isclose(res.cost, metrics["distance_m"], rel_tol=1e-6)


def test_same_objective_for_comparison():
    """A* time cost must be compared with Dijkstra time cost, not distance."""
    g = diamond()
    ov = EdgeOverlay()
    a_time = astar(g, "A", "D", g.cost_fn("time", ov), ov, g.heuristic_fn("time"))
    d_time = dijkstra(g, "A", "D", g.cost_fn("time", ov), ov, g.heuristic_fn("time"))
    assert math.isclose(a_time.cost, d_time.cost, rel_tol=1e-6)
