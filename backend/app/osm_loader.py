"""
Load a driveable OSM road graph for a small Nagpur bounding box.

Primary path: OSMnx (when installed and a download succeeds).
Fallback path: Overpass API, parsed into RoadGraph without NetworkX pathfinding.

Downloaded graphs are cached as JSON under backend/data/ so the same bbox
is not re-fetched. This respects OSM usage: small area, reuse cache.
"""

from __future__ import annotations

import json
import math
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

import httpx

from .graph import Edge, Node, RoadGraph, haversine_m, speed_for_highway

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Nagpur city centre (public landmark region). Small study area ~4 km across.
NAGPUR_CENTER = {"lat": 21.1458, "lon": 79.0882, "label": "Nagpur centre"}
DEFAULT_DIST_M = 2200
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OSM_MAP_API = "https://api.openstreetmap.org/api/0.6/map"


def bbox_from_point(lat: float, lon: float, dist_m: float) -> dict[str, float]:
    dlat = dist_m / 111_320.0
    dlon = dist_m / (111_320.0 * max(0.2, math.cos(math.radians(lat))))
    return {
        "north": lat + dlat,
        "south": lat - dlat,
        "east": lon + dlon,
        "west": lon - dlon,
    }


def cache_path(bbox: dict[str, float]) -> Path:
    key = "{south:.4f}_{west:.4f}_{north:.4f}_{east:.4f}".format(**bbox)
    return DATA_DIR / f"nagpur_{key}.json"


def latest_cache() -> Optional[Path]:
    files = sorted(DATA_DIR.glob("nagpur_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def load_from_cache(path: Optional[Path] = None) -> Optional[RoadGraph]:
    path = path or latest_cache()
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    graph = RoadGraph.from_cache_dict(data)
    graph.meta["cache_file"] = str(path)
    graph.meta["source"] = graph.meta.get("source", "cache")
    return graph


def save_cache(graph: RoadGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(graph.to_cache_dict(), f)


def load_map(
    dist_m: float = DEFAULT_DIST_M,
    lat: float = NAGPUR_CENTER["lat"],
    lon: float = NAGPUR_CENTER["lon"],
    force_download: bool = False,
) -> RoadGraph:
    bbox = bbox_from_point(lat, lon, dist_m)
    path = cache_path(bbox)
    if not force_download:
        cached = load_from_cache(path)
        if cached is not None:
            return cached
        # Reuse any previous Nagpur extract if the exact bbox file is missing.
        any_cache = load_from_cache()
        if any_cache is not None and not force_download:
            return any_cache

    errors: list[str] = []
    graph: Optional[RoadGraph] = None
    # Prefer the official OSM map API for this small bbox; Overpass is often congested.
    try:
        graph = _load_osm_map_api(bbox)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"OSM map API: {exc}")

    if graph is None:
        try:
            graph = _load_osmnx(bbox, lat, lon, dist_m)
        except Exception as exc:  # noqa: BLE001 — fallback is intentional
            errors.append(f"OSMnx: {exc}")

    if graph is None:
        try:
            graph = _load_overpass(bbox)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Overpass: {exc}")

    if graph is None:
        cached = load_from_cache()
        if cached is not None:
            cached.meta["warning"] = "Download failed; loaded previously cached graph. " + " | ".join(errors)
            return cached
        raise RuntimeError(
            "Could not download OpenStreetMap data and no local cache exists. "
            "Connect to the internet and retry. Details: " + " | ".join(errors)
        )

    graph.meta.update({
        "bbox": bbox,
        "center": {"lat": lat, "lon": lon},
        "dist_m": dist_m,
        "attribution": "© OpenStreetMap contributors",
        "traffic_note": (
            "OpenStreetMap does not provide live traffic. Congestion in this app "
            "is a user-controlled simulation, not a real-time feed."
        ),
    })
    save_cache(graph, path)
    graph.meta["cache_file"] = str(path)
    return graph


def _load_osmnx(bbox: dict[str, float], lat: float, lon: float, dist_m: float) -> RoadGraph:
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = str(DATA_DIR / "osmnx_cache")
    os.makedirs(DATA_DIR / "osmnx_cache", exist_ok=True)

    try:
        G = ox.graph_from_point((lat, lon), dist=int(dist_m), network_type="drive", simplify=True)
    except TypeError:
        west, south, east, north = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
        G = ox.graph.graph_from_bbox((west, south, east, north), network_type="drive")

    graph = RoadGraph(name="nagpur-osm")
    graph.meta["source"] = "osmnx"
    graph.meta["networkx_nodes"] = G.number_of_nodes()
    graph.meta["networkx_edges"] = G.number_of_edges()

    for nid, data in G.nodes(data=True):
        # OSMnx uses x=lon, y=lat
        graph.add_node(Node(id=str(nid), lat=float(data["y"]), lon=float(data["x"]), osm_id=str(nid)))

    for u, v, k, data in G.edges(keys=True, data=True):
        geom = _edge_geometry(data, graph.nodes[str(u)], graph.nodes[str(v)])
        length = float(data.get("length") or 0.0)
        if length <= 0 and geom:
            length = _polyline_length(geom)
        highway = data.get("highway", "road")
        if isinstance(highway, list):
            highway = highway[0]
        name = data.get("name") or ""
        if isinstance(name, list):
            name = ", ".join(str(x) for x in name)
        graph.add_edge(
            Edge(
                id=f"{u}-{v}-{k}",
                u=str(u),
                v=str(v),
                length_m=length,
                highway=str(highway),
                name=str(name),
                speed_kmh=speed_for_highway(highway, data.get("maxspeed")),
                geometry=geom,
                oneway=True,
                osm_way_id=str(data.get("osmid", "")),
            )
        )
    return graph


def _edge_geometry(data: dict[str, Any], u: Node, v: Node) -> list[tuple[float, float]]:
    geom = data.get("geometry")
    if geom is None:
        return [(u.lat, u.lon), (v.lat, v.lon)]
    try:
        coords = list(geom.coords)
        return [(float(y), float(x)) for x, y in coords]  # shapely (lon, lat)
    except Exception:
        return [(u.lat, u.lon), (v.lat, v.lon)]


def _polyline_length(geom: list[tuple[float, float]]) -> float:
    total = 0.0
    for (a, b), (c, d) in zip(geom, geom[1:]):
        total += haversine_m(a, b, c, d)
    return total


def _load_osm_map_api(bbox: dict[str, float]) -> RoadGraph:
    """
    Small-bbox download via the official OSM API (no Overpass).
    Suitable for the project's 3–5 km study area. Not for city-wide extracts.
    """
    params = {
        "bbox": f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}",
    }
    last_err: Optional[Exception] = None
    xml_text = ""
    for attempt in range(3):
        try:
            resp = httpx.get(
                OSM_MAP_API,
                params=params,
                timeout=60.0,
                headers={"User-Agent": "AI-Route-Agent-college-project/1.0"},
            )
            resp.raise_for_status()
            xml_text = resp.text
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    if not xml_text:
        raise RuntimeError(f"OSM map API failed: {last_err}")
    return _graph_from_osm_xml(xml_text, source="osm-map-api")


def _graph_from_osm_xml(xml_text: str, source: str) -> RoadGraph:
    root = ET.fromstring(xml_text)
    nodes_raw: dict[str, tuple[float, float]] = {}
    ways: list[tuple[list[str], dict[str, str]]] = []
    for el in root:
        tag = el.tag.split("}")[-1]
        if tag == "node":
            nid = el.attrib.get("id")
            if nid is None:
                continue
            nodes_raw[nid] = (float(el.attrib["lat"]), float(el.attrib["lon"]))
        elif tag == "way":
            tags = {
                t.attrib["k"]: t.attrib.get("v", "")
                for t in el
                if t.tag.split("}")[-1] == "tag" and "k" in t.attrib
            }
            nds = [n.attrib["ref"] for n in el if n.tag.split("}")[-1] == "nd" and "ref" in n.attrib]
            if "highway" in tags:
                tags["_osm_way_id"] = el.attrib.get("id", "")
                ways.append((nds, tags))
    return _graph_from_ways(nodes_raw, ways, source)


def _graph_from_ways(
    nodes_raw: dict[str, tuple[float, float]],
    ways: list[tuple[list[str], dict[str, str]]],
    source: str,
) -> RoadGraph:
    graph = RoadGraph(name="nagpur-osm")
    graph.meta["source"] = source
    skip_hw = {
        "footway", "path", "cycleway", "pedestrian", "steps", "bridleway",
        "corridor", "platform", "proposed", "construction", "abandoned",
    }
    used: set[str] = set()
    for nds, tags in ways:
        hw = str(tags.get("highway", "road"))
        if hw in skip_hw:
            continue
        for nid in nds:
            used.add(nid)
    for nid in used:
        if nid not in nodes_raw:
            continue
        lat, lon = nodes_raw[nid]
        graph.add_node(Node(id=nid, lat=lat, lon=lon, osm_id=nid))

    for nds, tags in ways:
        hw = str(tags.get("highway", "road"))
        if hw in skip_hw:
            continue
        nids = [n for n in nds if n in graph.nodes]
        if len(nids) < 2:
            continue
        oneway_tag = str(tags.get("oneway", "no")).lower()
        name = str(tags.get("name") or "")
        speed = speed_for_highway(hw, tags.get("maxspeed"))
        way_id = tags.get("_osm_way_id") or name or hw
        for i in range(len(nids) - 1):
            u, v = nids[i], nids[i + 1]
            geom = [
                (graph.nodes[u].lat, graph.nodes[u].lon),
                (graph.nodes[v].lat, graph.nodes[v].lon),
            ]
            length = haversine_m(*geom[0], *geom[1])
            forward = oneway_tag != "-1"
            reverse = oneway_tag not in {"yes", "true", "1"}
            if forward:
                graph.add_edge(
                    Edge(
                        id=f"{way_id}-{i}-{u}-{v}",
                        u=u,
                        v=v,
                        length_m=length,
                        highway=hw,
                        name=name,
                        speed_kmh=speed,
                        geometry=geom,
                        oneway=oneway_tag in {"yes", "true", "1", "-1"},
                        osm_way_id=str(way_id),
                    )
                )
            if reverse:
                graph.add_edge(
                    Edge(
                        id=f"{way_id}-{i}-{v}-{u}",
                        u=v,
                        v=u,
                        length_m=length,
                        highway=hw,
                        name=name,
                        speed_kmh=speed,
                        geometry=list(reversed(geom)),
                        oneway=oneway_tag in {"yes", "true", "1", "-1"},
                        osm_way_id=str(way_id),
                    )
                )
    if len(graph.edges) < 10:
        raise RuntimeError("OSM extract returned too few driveable edges for this bbox.")
    return graph


def _load_overpass(bbox: dict[str, float]) -> RoadGraph:
    query = f"""
    [out:json][timeout:90];
    (
      way["highway"]
        ["highway"!~"footway|path|cycleway|pedestrian|steps|bridleway|corridor|platform"]
        ["area"!~"yes"]
        ({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]});
    );
    (._;>;);
    out body;
    """
    data = None
    last_err = None
    for url in OVERPASS_URLS:
        try:
            resp = httpx.post(url, data={"data": query}, timeout=90.0)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if data is None:
        raise RuntimeError(f"Overpass request failed: {last_err}")

    nodes_raw = {}
    ways = []
    for el in data.get("elements", []):
        if el.get("type") == "node":
            nodes_raw[el["id"]] = el
        elif el.get("type") == "way":
            ways.append(el)

    graph = RoadGraph(name="nagpur-osm")
    graph.meta["source"] = "overpass"

    used_nodes: set[int] = set()
    for way in ways:
        for nid in way.get("nodes") or []:
            used_nodes.add(nid)
    for nid in used_nodes:
        raw = nodes_raw.get(nid)
        if not raw:
            continue
        graph.add_node(Node(id=str(nid), lat=float(raw["lat"]), lon=float(raw["lon"]), osm_id=str(nid)))

    skip_hw = {"footway", "path", "cycleway", "pedestrian", "steps", "bridleway"}
    for way in ways:
        tags = way.get("tags") or {}
        hw = str(tags.get("highway", "road"))
        if hw in skip_hw:
            continue
        nids = [str(n) for n in way.get("nodes") or [] if str(n) in graph.nodes]
        if len(nids) < 2:
            continue
        oneway_tag = str(tags.get("oneway", "no")).lower()
        name = str(tags.get("name") or "")
        speed = speed_for_highway(hw, tags.get("maxspeed"))
        for i in range(len(nids) - 1):
            u, v = nids[i], nids[i + 1]
            geom = [
                (graph.nodes[u].lat, graph.nodes[u].lon),
                (graph.nodes[v].lat, graph.nodes[v].lon),
            ]
            length = haversine_m(*geom[0], *geom[1])
            forward = oneway_tag != "-1"
            reverse = oneway_tag not in {"yes", "true", "1"}
            if forward:
                graph.add_edge(
                    Edge(
                        id=f"{way['id']}-{i}-{u}-{v}",
                        u=u,
                        v=v,
                        length_m=length,
                        highway=hw,
                        name=name,
                        speed_kmh=speed,
                        geometry=geom,
                        oneway=oneway_tag in {"yes", "true", "1", "-1"},
                        osm_way_id=str(way["id"]),
                    )
                )
            if reverse:
                graph.add_edge(
                    Edge(
                        id=f"{way['id']}-{i}-{v}-{u}",
                        u=v,
                        v=u,
                        length_m=length,
                        highway=hw,
                        name=name,
                        speed_kmh=speed,
                        geometry=list(reversed(geom)),
                        oneway=oneway_tag in {"yes", "true", "1", "-1"},
                        osm_way_id=str(way["id"]),
                    )
                )
    if len(graph.edges) < 10:
        raise RuntimeError("Overpass returned too few driveable edges for this bbox.")
    return graph


def sample_waypoints(graph: RoadGraph) -> list[dict[str, Any]]:
    """
    Named sample points inside the loaded extract.
    Labels are well-known public areas; they are NOT a live hospital registry.
    Each point is snapped to the road network.
    """
    candidates = [
        {"id": "zero_mile", "label": "Zero Mile Stone area (approx.)", "lat": 21.1498, "lon": 79.0806, "kind": "start"},
        {"id": "sitabuldi", "label": "Sitabuldi area (approx.)", "lat": 21.1463, "lon": 79.0848, "kind": "start"},
        {"id": "railway", "label": "Nagpur Junction area (approx.)", "lat": 21.1522, "lon": 79.0888, "kind": "start"},
        {"id": "civil_lines", "label": "Civil Lines area (approx.)", "lat": 21.1510, "lon": 79.0740, "kind": "start"},
        {"id": "variety", "label": "Variety Square area (approx.)", "lat": 21.1475, "lon": 79.0795, "kind": "start"},
        {"id": "medical_sq", "label": "Medical College Square area (approx. hospital district)", "lat": 21.1533, "lon": 79.0920, "kind": "hospital"},
        {"id": "ramdaspeth", "label": "Ramdaspeth area (approx.)", "lat": 21.1400, "lon": 79.0800, "kind": "hospital"},
        {"id": "dhantoli", "label": "Dhantoli area (approx.)", "lat": 21.1395, "lon": 79.0835, "kind": "hospital"},
    ]
    out = []
    for c in candidates:
        try:
            snap = graph.snap(c["lat"], c["lon"])
        except ValueError:
            continue
        # Drop points that snap unreasonably far (outside the extract).
        if snap["snap_distance_m"] > 1200:
            continue
        out.append({**c, "snap": snap})
    return out
