import math

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_snap_toy():
    r = client.post("/api/map/snap", json={"graph_mode": "toy", "lat": 21.15, "lon": 79.08})
    assert r.status_code == 200
    body = r.json()
    assert body["node_id"] in {"A", "E"}
    assert "snap_distance_m" in body


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_toy_route_astar():
    r = client.post(
        "/api/route/calculate",
        json={
            "graph_mode": "toy",
            "algorithm": "astar",
            "objective": "distance",
            "start_node": "A",
            "goal_node": "H",
            "include_events": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["path"] == ["A", "E", "F", "G", "H"]
    assert abs(body["cost"] - 11) < 1e-6
    assert math.isfinite(body["distance_m"])
    assert math.isfinite(body["time_s"])


def test_compare_same_objective():
    r = client.post(
        "/api/route/compare",
        json={
            "graph_mode": "toy",
            "objective": "distance",
            "start_node": "A",
            "goal_node": "H",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["comparison_valid"] is True
    assert body["optimality_check"]["astar_matches_dijkstra"] is True
    for row in body["rows"]:
        if row["found"]:
            assert math.isfinite(row["distance_m"])
            assert math.isfinite(row["time_s"])


def test_simulation_block_and_replan():
    r = client.post(
        "/api/simulation/start",
        json={
            "graph_mode": "toy",
            "algorithm": "astar",
            "objective": "distance",
            "start_node": "A",
            "goal_node": "H",
            "replan_enabled": True,
        },
    )
    sim = r.json()
    sim_id = sim["id"]
    client.post(f"/api/simulation/{sim_id}/advance", json={"steps": 1})
    ev = client.post(
        f"/api/simulation/{sim_id}/event",
        json={"event_type": "block", "edge_id": "F->G", "auto_replan": True},
    )
    assert ev.status_code == 200
    body = ev.json()
    assert body["replanned"] is True
    assert body["replan_count"] >= 1
    assert "remaining_time_before_s" in body
    assert "remaining_time_after_s" in body


def test_advance_returns_real_edge_geometry():
    r = client.post(
        "/api/simulation/start",
        json={
            "graph_mode": "toy",
            "algorithm": "astar",
            "objective": "distance",
            "start_node": "A",
            "goal_node": "H",
            "replan_enabled": True,
        },
    )
    sim_id = r.json()["id"]
    moved = client.post(f"/api/simulation/{sim_id}/advance", json={"steps": 1})
    assert moved.status_code == 200
    geom = moved.json()["last_moved_geometry"]
    assert len(geom) >= 2
    assert geom[0][0] != geom[-1][0] or geom[0][1] != geom[-1][1]
