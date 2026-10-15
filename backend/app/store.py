"""In-memory process state. No database."""

from __future__ import annotations

from typing import Optional

from .graph import RoadGraph
from .simulation import Simulation
from .toy_graph import build_toy_graph

nagpur_graph: Optional[RoadGraph] = None
toy_graph: RoadGraph = build_toy_graph()
simulations: dict[str, Simulation] = {}
map_status: dict = {
    "loaded": False,
    "message": "Road network not loaded yet.",
    "source": None,
}


def get_graph(mode: str) -> RoadGraph:
    if mode == "toy":
        return toy_graph
    if nagpur_graph is None:
        raise RuntimeError(
            "Nagpur road network is not loaded. Use POST /api/map/load "
            "(internet required on first download) or switch graph_mode to 'toy'."
        )
    return nagpur_graph
