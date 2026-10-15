"""
Optional eight-node educational graph (not the Nagpur road experiment).

Nodes are placed in metres so straight-line heuristics stay admissible:

        5 m         3 m         4 m
   A -------- B -------- C -------- D
   |          |          |          |
   2 m       (BF)       (CG)       (DH)
   |          |          |          |
   E -------- F -------- G -------- H  (goal)
        4 m         2 m         3 m

BF, CG and DH use the true geographic length between those coordinates.
Independent check of A→H:
  A-E-F-G-H = 2+4+2+3 = 11 m  (optimal distance)
  A-B-F-G-H = 5 + |B-F| + 2 + 3 > 11
  A-B-C-D-H = 5+3+4+|D-H| > 11
"""

from __future__ import annotations

import math

from .graph import Edge, Node, RoadGraph, haversine_m

ORIGIN_LAT = 21.1500
ORIGIN_LON = 79.0800


def _latlon(east_m: float, north_m: float) -> tuple[float, float]:
    lat = ORIGIN_LAT + north_m / 111_320.0
    lon = ORIGIN_LON + east_m / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))
    return lat, lon


def build_toy_graph() -> RoadGraph:
    g = RoadGraph(name="toy-8")
    # metre offsets (east, north)
    layout = {
        "A": (0.0, 2.0),
        "B": (5.0, 2.0),
        "C": (8.0, 2.0),
        "D": (12.0, 2.0),
        "E": (0.0, 0.0),
        "F": (4.0, 0.0),
        "G": (6.0, 0.0),
        "H": (9.0, 0.0),
    }
    for nid, (east, north) in layout.items():
        lat, lon = _latlon(east, north)
        g.add_node(Node(id=nid, lat=lat, lon=lon, osm_id=nid))

    named_lengths = {
        ("A", "B"): 5.0,
        ("B", "C"): 3.0,
        ("C", "D"): 4.0,
        ("A", "E"): 2.0,
        ("E", "F"): 4.0,
        ("F", "G"): 2.0,
        ("G", "H"): 3.0,
    }
    for (u, v), length in named_lengths.items():
        _add_undirected(g, u, v, length)

    for u, v in (("B", "F"), ("C", "G"), ("D", "H")):
        a, b = g.nodes[u], g.nodes[v]
        length = haversine_m(a.lat, a.lon, b.lat, b.lon)
        _add_undirected(g, u, v, length)

    m_opt = g.path_metrics(["A", "E", "F", "G", "H"])
    g.meta = {
        "kind": "toy",
        "description": "Eight-node teaching graph. Not a real road map.",
        "optimal_distance_A_to_H_m": m_opt["distance_m"],
        "optimal_path_A_to_H": ["A", "E", "F", "G", "H"],
    }
    return g


def _add_undirected(g: RoadGraph, u: str, v: str, length: float) -> None:
    speed = 30.0
    for a, b in ((u, v), (v, u)):
        g.add_edge(
            Edge(
                id=f"{a}->{b}",
                u=a,
                v=b,
                length_m=length,
                highway="residential",
                name=f"{a}-{b}",
                speed_kmh=speed,
                oneway=False,
            )
        )


def disconnected_toy() -> RoadGraph:
    """Two components: A-B and X-Y. Used for the unreachable-goal experiment."""
    g = RoadGraph(name="toy-disconnected")
    g.meta = {"kind": "toy", "description": "Two disconnected components."}
    g.add_node(Node("A", 21.15, 79.08))
    g.add_node(Node("B", 21.15, 79.081))
    g.add_node(Node("X", 21.16, 79.09))
    g.add_node(Node("Y", 21.16, 79.091))
    g.add_edge(Edge("A->B", "A", "B", 100, name="AB", speed_kmh=30))
    g.add_edge(Edge("B->A", "B", "A", 100, name="BA", speed_kmh=30))
    g.add_edge(Edge("X->Y", "X", "Y", 100, name="XY", speed_kmh=30))
    g.add_edge(Edge("Y->X", "Y", "X", 100, name="YX", speed_kmh=30))
    return g
