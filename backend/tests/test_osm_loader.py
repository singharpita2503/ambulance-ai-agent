import pytest

from app import osm_loader
from app.graph import Node, RoadGraph


def _graph() -> RoadGraph:
    graph = RoadGraph(name="test")
    graph.add_node(Node(id="1", lat=21.1458, lon=79.0882))
    return graph


def test_citywide_map_load_uses_osmnx_and_saves_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(osm_loader, "DATA_DIR", tmp_path)
    calls = []

    def load_with_osmnx(bbox, lat, lon, dist_m):
        calls.append(dist_m)
        return _graph()

    def unexpected_loader(*_args):
        raise AssertionError("The compact-map API should not load a city-wide extract.")

    monkeypatch.setattr(osm_loader, "_load_osmnx", load_with_osmnx)
    monkeypatch.setattr(osm_loader, "_load_osm_map_api", unexpected_loader)
    monkeypatch.setattr(osm_loader, "_load_overpass", unexpected_loader)

    graph = osm_loader.load_map()

    assert calls == [osm_loader.DEFAULT_DIST_M]
    assert graph.meta["dist_m"] == osm_loader.DEFAULT_DIST_M
    assert osm_loader.cache_path(graph.meta["bbox"]).exists()


def test_small_cached_extract_is_not_used_as_citywide_map(monkeypatch, tmp_path):
    monkeypatch.setattr(osm_loader, "DATA_DIR", tmp_path)
    small_bbox = osm_loader.bbox_from_point(
        osm_loader.NAGPUR_CENTER["lat"],
        osm_loader.NAGPUR_CENTER["lon"],
        1800,
    )
    small_graph = _graph()
    small_graph.meta["bbox"] = small_bbox
    osm_loader.save_cache(small_graph, osm_loader.cache_path(small_bbox))

    def unavailable(*_args):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(osm_loader, "_load_osmnx", unavailable)
    monkeypatch.setattr(osm_loader, "_load_overpass", unavailable)

    with pytest.raises(RuntimeError, match="no local cache exists"):
        osm_loader.load_map()
