"""Real-road checks. Skipped when no cached OSM extract is present."""

from __future__ import annotations

import math

import pytest

from app.algorithms import astar, dijkstra
from app.graph import EdgeOverlay
from app.osm_loader import load_from_cache


@pytest.fixture(scope="module")
def osm_graph():
    g = load_from_cache()
    if g is None:
        pytest.skip("No cached Nagpur OSM graph. Load the map once with internet.")
    return g


def test_osm_route_follows_existing_edges(osm_graph):
    west = min(osm_graph.nodes.values(), key=lambda n: n.lon)
    east = max(osm_graph.nodes.values(), key=lambda n: n.lon)
    ov = EdgeOverlay()
    res = astar(
        osm_graph,
        west.id,
        east.id,
        osm_graph.cost_fn("distance", ov),
        ov,
        osm_graph.heuristic_fn("distance"),
        max_events=0,
    )
    if not res.found:
        pytest.skip("West–east pair is disconnected in this extract.")
    metrics = osm_graph.path_metrics(res.path, ov)
    assert metrics["reachable"]
    assert math.isclose(res.cost, metrics["distance_m"], rel_tol=1e-4)
    for u, v in zip(res.path, res.path[1:]):
        assert osm_graph.edge_between_any(u, v) is not None


def test_osm_astar_matches_dijkstra_cost(osm_graph):
    nodes = list(osm_graph.nodes.values())
    start = min(nodes, key=lambda n: n.lat)
    goal = max(nodes, key=lambda n: n.lat)
    ov = EdgeOverlay()
    a = astar(
        osm_graph, start.id, goal.id,
        osm_graph.cost_fn("distance", ov), ov, osm_graph.heuristic_fn("distance"), 0,
    )
    d = dijkstra(
        osm_graph, start.id, goal.id,
        osm_graph.cost_fn("distance", ov), ov, osm_graph.heuristic_fn("distance"), 0,
    )
    if not (a.found and d.found):
        pytest.skip("North–south pair unreachable in this extract.")
    assert math.isclose(a.cost, d.cost, rel_tol=1e-4)
