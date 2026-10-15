from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


AlgorithmName = Literal["bfs", "dfs", "dijkstra", "astar"]
ObjectiveName = Literal["distance", "time"]
GraphMode = Literal["nagpur", "toy"]


class LatLon(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class MapLoadRequest(BaseModel):
    lat: float = 21.1458
    lon: float = 79.0882
    dist_m: float = Field(2200, ge=800, le=8000)
    force_download: bool = False
    use_cache_only: bool = False


class SnapRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    graph_mode: GraphMode = "nagpur"


class RouteRequest(BaseModel):
    algorithm: AlgorithmName = "astar"
    objective: ObjectiveName = "distance"
    graph_mode: GraphMode = "nagpur"
    start: Optional[LatLon] = None
    goal: Optional[LatLon] = None
    start_node: Optional[str] = None
    goal_node: Optional[str] = None
    blocked_edges: list[str] = []
    congestion: dict[str, float] = {}
    include_events: bool = True
    max_events: int = Field(2500, ge=0, le=20000)


class CompareRequest(RouteRequest):
    algorithms: list[AlgorithmName] = ["bfs", "dfs", "dijkstra", "astar"]


class SimulationStartRequest(RouteRequest):
    replan_enabled: bool = True
    auto_block_after: Optional[int] = Field(None, ge=0, le=50)


class SimulationEventRequest(BaseModel):
    event_type: Literal["block", "unblock", "congestion"]
    edge_id: str
    congestion: float = Field(2.0, ge=1.0, le=20.0)
    auto_replan: bool = True


class SimulationAdvanceRequest(BaseModel):
    steps: int = Field(1, ge=1, le=500)


class ExperimentRequest(BaseModel):
    scenario_id: str
    graph_mode: GraphMode = "toy"
    algorithm: AlgorithmName = "astar"
    objective: ObjectiveName = "distance"


class ErrorBody(BaseModel):
    error: str
    detail: Optional[Any] = None
