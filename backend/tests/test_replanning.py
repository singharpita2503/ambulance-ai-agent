from app.graph import EdgeOverlay
from app.simulation import (
    advance,
    apply_event,
    compare_replan_vs_control,
    remaining_affected,
    start_simulation,
)
from app.toy_graph import build_toy_graph
from app.scenarios import run_scenario


def test_replan_from_current_position():
    g = build_toy_graph()
    sim, res = start_simulation(g, "A", "H", "astar", "distance", True, EdgeOverlay())
    assert res.path == ["A", "E", "F", "G", "H"]
    advance(sim, g, 1)  # now at E
    assert sim.current_node == "E"
    apply_event(sim, g, "block", "F->G")
    assert sim.replan_count == 1
    assert sim.remaining_path[0] == "E"
    assert "F->G" not in g.path_metrics(sim.remaining_path, sim.overlay).get("edge_ids", [])
    assert sim.remaining_path[-1] == "H"
    assert sim.status == "running"


def test_no_replan_stops_at_blocked_next_road():
    g = build_toy_graph()
    sim, _ = start_simulation(g, "A", "H", "astar", "distance", False, EdgeOverlay())
    advance(sim, g, 2)  # A -> E -> F
    assert sim.current_node == "F"
    apply_event(sim, g, "block", "F->G", auto_replan=False)
    assert sim.status == "stopped"
    assert sim.current_node == "F"
    assert sim.current_node != "H"


def test_never_animates_through_blocked_edge():
    g = build_toy_graph()
    sim, _ = start_simulation(g, "A", "H", "astar", "distance", False, EdgeOverlay())
    apply_event(sim, g, "block", "A->E", auto_replan=False)
    apply_event(sim, g, "block", "A->B", auto_replan=False)
    advance(sim, g, 5)
    assert sim.current_node == "A"
    assert sim.status in {"stopped", "failed"}


def test_congestion_with_replan_reruns_search():
    g = build_toy_graph()
    sim, _ = start_simulation(g, "A", "H", "astar", "time", True, EdgeOverlay())
    apply_event(sim, g, "congestion", "F->G", congestion=8.0, auto_replan=True)
    assert sim.replan_count == 1
    assert sim.status in {"running", "arrived"}


def test_congestion_no_replan_continues_with_higher_time():
    g = build_toy_graph()
    sim, _ = start_simulation(g, "A", "H", "astar", "time", False, EdgeOverlay())
    before = g.path_metrics(sim.remaining_path, sim.overlay)["time_s"]
    apply_event(sim, g, "congestion", "F->G", congestion=4.0, auto_replan=False)
    after = g.path_metrics(sim.remaining_path, sim.overlay)["time_s"]
    assert after > before
    assert sim.status == "running"
    # Can still finish because the road is not blocked.
    advance(sim, g, 20)
    assert sim.status == "arrived"


def test_no_alternative_does_not_claim_arrival():
    out = run_scenario("no_alternative")
    assert out["found"] is False
    assert out["status"] == "failed"


def test_disconnected_failure():
    out = run_scenario("disconnected")
    assert out["found"] is False
    assert out["completed"] is False


def test_remaining_affected_detection():
    g = build_toy_graph()
    ov = EdgeOverlay()
    path = ["A", "E", "F", "G", "H"]
    assert remaining_affected(path, g, ov) is False
    ov.set_blocked("F->G", True)
    assert remaining_affected(path, g, ov) is True


def test_compare_replan_vs_control_block():
    g = build_toy_graph()
    out = compare_replan_vs_control(
        g, "A", "H", "astar", "distance",
        block_edge_id="F->G", block_after_hops=1,
    )
    wr = out["with_replanning"]
    wo = out["without_replanning"]
    # With replan the agent should still be able to finish (G can be avoided via C or B/D).
    assert wr["completed"] is True
    assert wo["completed"] is False or wo["status"] in {"stopped", "failed"}


def test_auto_block_ahead_of_ambulance():
    g = build_toy_graph()
    sim, _ = start_simulation(
        g, "A", "H", "astar", "distance", True, EdgeOverlay(), auto_block_after=1
    )
    advance(sim, g, 1)
    assert sim.auto_block_done
    assert sim.overlay.is_blocked("F->G")
    assert sim.replan_count >= 1
    advance(sim, g, 20)
    assert sim.status == "arrived"
    assert sim.current_node == "H"


def test_scenario_normal_optimal():
    out = run_scenario("normal")
    astar_dist = next(r for r in out["rows"] if r["algorithm"] == "astar" and r["objective"] == "distance")
    assert astar_dist["found"]
    assert astar_dist["path"] == ["A", "E", "F", "G", "H"]
    assert astar_dist["cost"] == 11
