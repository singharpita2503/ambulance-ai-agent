"""Graph environment tests: snapping, metrics, overlays, route-edge consistency."""

from __future__ import annotations

import math

from app.graph import Edge, EdgeOverlay, Node, RoadGraph, haversine_m, speed_for_highway
from app.toy_graph import build_toy_graph


def test_snap_reports_distance():
    g = build_toy_graph()
    node = g.nodes["A"]
    snap = g.snap(node.lat, node.lon)
    assert snap["node_id"] == "A"
    assert snap["snap_distance_m"] == 0
    far = g.snap(node.lat + 0.001, node.lon)
    assert far["snap_distance_m"] > 0
    assert far["node_id"] in g.nodes


def test_blocked_overlay_hides_neighbour():
    g = build_toy_graph()
    ov = EdgeOverlay()
    neigh = {e.id for e in g.neighbors("A")}
    assert "A->E" in neigh
    ov.set_blocked("A->E", True)
    neigh2 = {e.id for e in g.neighbors("A", ov)}
    assert "A->E" not in neigh2
    assert g.cost_fn("distance", ov)(g.edges["A->E"]) == math.inf


def test_congestion_multiplies_time_only():
    g = build_toy_graph()
    ov = EdgeOverlay()
    ov.set_congestion("A->E", 3.0)
    dist_cost = g.cost_fn("distance", ov)(g.edges["A->E"])
    time_cost = g.cost_fn("time", ov)(g.edges["A->E"])
    assert math.isclose(dist_cost, g.edges["A->E"].length_m)
    assert math.isclose(time_cost, g.edges["A->E"].base_time_s * 3.0)


def test_path_metrics_break_on_missing_edge():
    g = build_toy_graph()
    broken = g.path_metrics(["A", "H"])
    assert broken["reachable"] is False


def test_speed_table_used_for_estimates():
    assert speed_for_highway("residential") == 25.0
    assert speed_for_highway("motorway") == 80.0
    parsed = speed_for_highway("primary", "50")
    assert parsed == 50.0


def test_heuristic_never_overestimates_toy_distance():
    g = build_toy_graph()
    h = g.heuristic_fn("distance")
    true = g.path_metrics(["A", "E", "F", "G", "H"])["distance_m"]
    assert h("A", "H") <= true + 1e-6
    assert h("H", "H") == 0


def test_one_way_is_directional():
    g = RoadGraph("oneway")
    g.add_node(Node("U", 21.15, 79.08))
    g.add_node(Node("V", 21.1501, 79.08))
    L = haversine_m(21.15, 79.08, 21.1501, 79.08)
    g.add_edge(Edge("U->V", "U", "V", L, oneway=True, speed_kmh=30))
    assert g.edge_between_any("U", "V") is not None
    assert g.edge_between_any("V", "U") is None
