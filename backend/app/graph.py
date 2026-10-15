"""
Road-network graph used as the agent's environment.

States  = road intersections (graph nodes)
Actions = traverse a directed road segment (graph edge)
Path cost = sum of edge costs under the selected objective
            (metres for distance, seconds for estimated travel time)

This module does not call NetworkX shortest-path functions.
NetworkX/OSMnx are used only to import or validate OSM data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional


EARTH_RADIUS_M = 6_371_000.0

# Conservative default speeds by OSM highway class (km/h).
# These are planning estimates, not live traffic speeds.
HIGHWAY_SPEED_KMH: dict[str, float] = {
    "motorway": 80.0,
    "motorway_link": 50.0,
    "trunk": 70.0,
    "trunk_link": 45.0,
    "primary": 50.0,
    "primary_link": 40.0,
    "secondary": 40.0,
    "secondary_link": 35.0,
    "tertiary": 35.0,
    "tertiary_link": 30.0,
    "unclassified": 30.0,
    "residential": 25.0,
    "living_street": 15.0,
    "service": 20.0,
    "track": 15.0,
    "road": 30.0,
}
DEFAULT_SPEED_KMH = 30.0
# Upper bound used by the travel-time heuristic so h(n) stays admissible
# as long as no edge is faster than this after congestion (>= 1.0).
MAX_HEURISTIC_SPEED_KMH = 90.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (admissible straight-line heuristic)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def parse_maxspeed_kmh(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text or text in {"none", "signals", "variable"}:
        return None
    if "mph" in text:
        try:
            return float(text.replace("mph", "").strip().split()[0]) * 1.60934
        except ValueError:
            return None
    try:
        return float(text.replace("km/h", "").replace("kmh", "").strip().split()[0])
    except ValueError:
        return None


def speed_for_highway(highway: Any, maxspeed: Any = None) -> float:
    parsed = parse_maxspeed_kmh(maxspeed)
    if parsed and 5.0 <= parsed <= 130.0:
        return parsed
    if isinstance(highway, list) and highway:
        highway = highway[0]
    key = str(highway or "road").lower()
    return HIGHWAY_SPEED_KMH.get(key, DEFAULT_SPEED_KMH)


@dataclass
class Node:
    id: str
    lat: float
    lon: float
    osm_id: Optional[str] = None


@dataclass
class Edge:
    id: str
    u: str
    v: str
    length_m: float
    highway: str = "road"
    name: str = ""
    speed_kmh: float = DEFAULT_SPEED_KMH
    geometry: list[tuple[float, float]] = field(default_factory=list)  # (lat, lon)
    oneway: bool = True
    osm_way_id: Optional[str] = None

    @property
    def base_time_s(self) -> float:
        speed_m_s = (self.speed_kmh / 3.6) if self.speed_kmh > 0 else (DEFAULT_SPEED_KMH / 3.6)
        return self.length_m / speed_m_s


@dataclass
class EdgeOverlay:
    """Per-simulation dynamic attributes. The base graph stays immutable."""

    blocked: dict[str, bool] = field(default_factory=dict)
    congestion: dict[str, float] = field(default_factory=dict)

    def is_blocked(self, edge_id: str) -> bool:
        return bool(self.blocked.get(edge_id, False))

    def multiplier(self, edge_id: str) -> float:
        # Congestion only slows traffic; values < 1 would break admissibility.
        return max(1.0, float(self.congestion.get(edge_id, 1.0)))

    def set_blocked(self, edge_id: str, value: bool) -> None:
        if value:
            self.blocked[edge_id] = True
        else:
            self.blocked.pop(edge_id, None)

    def set_congestion(self, edge_id: str, multiplier: float) -> None:
        m = max(1.0, float(multiplier))
        if m == 1.0:
            self.congestion.pop(edge_id, None)
        else:
            self.congestion[edge_id] = m

    def clone(self) -> "EdgeOverlay":
        return EdgeOverlay(blocked=dict(self.blocked), congestion=dict(self.congestion))


CostFn = Callable[[Edge], float]


class RoadGraph:
    def __init__(self, name: str = "graph") -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.adj: dict[str, list[str]] = {}
        self.meta: dict[str, Any] = {}

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.adj.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        if edge.u not in self.nodes or edge.v not in self.nodes:
            raise ValueError(f"Edge {edge.id} refers to unknown nodes {edge.u}->{edge.v}")
        if edge.length_m <= 0:
            edge.length_m = max(0.1, haversine_m(
                self.nodes[edge.u].lat, self.nodes[edge.u].lon,
                self.nodes[edge.v].lat, self.nodes[edge.v].lon,
            ))
        if not edge.geometry:
            u, v = self.nodes[edge.u], self.nodes[edge.v]
            edge.geometry = [(u.lat, u.lon), (v.lat, v.lon)]
        self.edges[edge.id] = edge
        self.adj.setdefault(edge.u, []).append(edge.id)

    def neighbors(self, node_id: str, overlay: Optional[EdgeOverlay] = None) -> Iterable[Edge]:
        for eid in self.adj.get(node_id, []):
            edge = self.edges[eid]
            if overlay is not None and overlay.is_blocked(eid):
                continue
            yield edge

    def cost_fn(self, objective: str, overlay: Optional[EdgeOverlay] = None) -> CostFn:
        """
        Distance objective uses length in metres.
        Time objective uses estimated seconds = (length / speed) * congestion.
        Congestion never changes geometric distance unless a different model is chosen.
        """

        def _cost(edge: Edge) -> float:
            if overlay is not None and overlay.is_blocked(edge.id):
                return math.inf
            if objective == "time":
                return edge.base_time_s * (overlay.multiplier(edge.id) if overlay else 1.0)
            return edge.length_m

        return _cost

    def path_metrics(
        self,
        path: list[str],
        overlay: Optional[EdgeOverlay] = None,
    ) -> dict[str, Any]:
        if not path:
            return {
                "distance_m": math.inf,
                "time_s": math.inf,
                "blocked": True,
                "edge_ids": [],
                "reachable": False,
            }
        distance = 0.0
        time_s = 0.0
        edge_ids: list[str] = []
        for u, v in zip(path, path[1:]):
            edge = self.find_edge(u, v, overlay)
            if edge is None:
                return {
                    "distance_m": math.inf,
                    "time_s": math.inf,
                    "blocked": True,
                    "edge_ids": edge_ids,
                    "reachable": False,
                    "broken_at": [u, v],
                }
            distance += edge.length_m
            mult = overlay.multiplier(edge.id) if overlay else 1.0
            time_s += edge.base_time_s * mult
            edge_ids.append(edge.id)
        return {
            "distance_m": distance,
            "time_s": time_s,
            "blocked": False,
            "edge_ids": edge_ids,
            "reachable": True,
        }

    def find_edge(self, u: str, v: str, overlay: Optional[EdgeOverlay] = None) -> Optional[Edge]:
        best: Optional[Edge] = None
        for eid in self.adj.get(u, []):
            edge = self.edges[eid]
            if edge.v != v:
                continue
            if overlay is not None and overlay.is_blocked(eid):
                continue
            if best is None or edge.length_m < best.length_m:
                best = edge
        return best

    def edge_between_any(self, u: str, v: str) -> Optional[Edge]:
        for eid in self.adj.get(u, []):
            edge = self.edges[eid]
            if edge.v == v:
                return edge
        return None

    def snap(self, lat: float, lon: float) -> dict[str, Any]:
        if not self.nodes:
            raise ValueError("Graph has no nodes to snap to")
        best_id = ""
        best_d = math.inf
        for nid, node in self.nodes.items():
            d = haversine_m(lat, lon, node.lat, node.lon)
            if d < best_d:
                best_d = d
                best_id = nid
        node = self.nodes[best_id]
        return {
            "node_id": best_id,
            "lat": node.lat,
            "lon": node.lon,
            "snap_distance_m": round(best_d, 2),
            "requested": {"lat": lat, "lon": lon},
        }

    def heuristic_fn(self, objective: str) -> Callable[[str, str], float]:
        max_speed_m_s = MAX_HEURISTIC_SPEED_KMH / 3.6

        def _h(node_id: str, goal_id: str) -> float:
            a, b = self.nodes[node_id], self.nodes[goal_id]
            dist = haversine_m(a.lat, a.lon, b.lat, b.lon)
            if objective == "time":
                return dist / max_speed_m_s
            return dist

        return _h

    def path_geometry(self, path: list[str], overlay: Optional[EdgeOverlay] = None) -> list[list[float]]:
        coords: list[list[float]] = []
        for u, v in zip(path, path[1:]):
            edge = self.find_edge(u, v, overlay) or self.edge_between_any(u, v)
            if edge is None:
                break
            pts = edge.geometry or []
            for lat, lon in pts:
                if not coords or coords[-1] != [lat, lon]:
                    coords.append([lat, lon])
        return coords

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "meta": self.meta,
            "nodes": {
                nid: {"lat": n.lat, "lon": n.lon, "osm_id": n.osm_id}
                for nid, n in self.nodes.items()
            },
            "edges": [
                {
                    "id": e.id,
                    "u": e.u,
                    "v": e.v,
                    "length_m": e.length_m,
                    "highway": e.highway,
                    "name": e.name,
                    "speed_kmh": e.speed_kmh,
                    "geometry": [[lat, lon] for lat, lon in e.geometry],
                    "oneway": e.oneway,
                    "osm_way_id": e.osm_way_id,
                }
                for e in self.edges.values()
            ],
        }

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> "RoadGraph":
        g = cls(name=data.get("name", "graph"))
        g.meta = dict(data.get("meta") or {})
        for nid, raw in (data.get("nodes") or {}).items():
            g.add_node(Node(id=str(nid), lat=float(raw["lat"]), lon=float(raw["lon"]), osm_id=raw.get("osm_id")))
        for raw in data.get("edges") or []:
            geom = [(float(p[0]), float(p[1])) for p in raw.get("geometry") or []]
            g.add_edge(
                Edge(
                    id=str(raw["id"]),
                    u=str(raw["u"]),
                    v=str(raw["v"]),
                    length_m=float(raw["length_m"]),
                    highway=str(raw.get("highway") or "road"),
                    name=str(raw.get("name") or ""),
                    speed_kmh=float(raw.get("speed_kmh") or DEFAULT_SPEED_KMH),
                    geometry=geom,
                    oneway=bool(raw.get("oneway", True)),
                    osm_way_id=raw.get("osm_way_id"),
                )
            )
        return g

    def road_geojson(self, overlay: Optional[EdgeOverlay] = None, max_features: int = 12000) -> dict[str, Any]:
        features = []
        for i, edge in enumerate(self.edges.values()):
            if i >= max_features:
                break
            blocked = overlay.is_blocked(edge.id) if overlay else False
            congestion = overlay.multiplier(edge.id) if overlay else 1.0
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": edge.id,
                        "u": edge.u,
                        "v": edge.v,
                        "name": edge.name,
                        "highway": edge.highway,
                        "length_m": round(edge.length_m, 2),
                        "speed_kmh": edge.speed_kmh,
                        "blocked": blocked,
                        "congestion": congestion,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon, lat] for lat, lon in edge.geometry],
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "meta": self.meta,
        }
