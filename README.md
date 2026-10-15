# AI-Based Emergency Ambulance Route Planning Agent

A 7th-semester B.Tech (ECE / Artificial Intelligence) project that demonstrates **classical AI search** on a **real OpenStreetMap road network** around Nagpur, Maharashtra.

This is a **search-based planning agent**, not a chatbot and not a machine-learning model. The backend actually runs BFS, DFS, Dijkstra and A\* on a directed road graph. Mid-journey road blocks trigger optional **re-planning from the ambulance’s current junction**.

Congestion controls are **simulated**. OpenStreetMap does not provide a dependable live traffic feed, and this project does not pretend otherwise.

## 1. The real-world problem

An ambulance must reach a hospital quickly on a city street network. Roads have different lengths and typical speeds, some streets are one-way, and conditions can change after departure (a blockage or slower traffic). A straight line on the map is not a legal driving path. The agent therefore:

1. Snaps clicked coordinates to the nearest road-network node (intersection).
2. Searches over **states = intersections** and **actions = directed road segments**.
3. Returns a route whose geometry follows OSM ways.
4. Optionally re-runs search when a remaining edge is blocked or slowed.

Hospital names in the sample list are **approximate public areas** inside the extract, not a live hospital registry. You may click any reachable destination on the road graph.

## 2. Intelligent agent and environment

| Concept | In this project |
| --- | --- |
| Agent type | Goal-based / problem-solving agent (offline planner + closed-loop re-planner) |
| Percepts | Road graph, snapped start/goal, overlay of blocked/congested edges, current node |
| Actuators | Choice of next edge; optional re-plan action |
| Environment | Partially static OSM graph + **dynamic overlay** (blocks, congestion multipliers) |
| Deterministic? | Yes, for a fixed overlay and algorithm. Use the toy scenarios for reproducible labs. |
| Fully observable? | The graph and overlay are fully known to the planner (not a hidden-traffic model) |

**State.** A node ID in the road graph (an intersection).

**Action.** Traverse a directed edge to a neighbour (skipped if blocked).

**Initial state.** OSM node nearest to the ambulance click.

**Goal test.** Current node equals the snapped destination.

**Path cost.** Sum of edge costs under the selected objective:

- **Distance:** length in metres.
- **Time:** estimated seconds = `(length_m / speed_m_s) × congestion_multiplier`.

Speeds come from OSM `highway` class and optional `maxspeed` tags. They are **planning estimates**, not measured travel times.

## 3. Graph vs search tree

The **graph** is the road network: nodes and directed edges with geometry. The **search tree** (or search forest) is the set of paths generated while exploring. Open and closed lists prevent unbounded expansion:

- **Open list (frontier):** generated but not yet expanded. FIFO queue (BFS), stack (DFS), or min-heap on \(f\) (Dijkstra / A\*).
- **Closed list:** expanded nodes. Dijkstra/A\* still allow a cheaper \(g(n)\) to re-open a node via a new heap entry; **stale** heap entries are discarded when popped.

## 4. Algorithms (implemented in `backend/app/algorithms.py`)

NetworkX is **not** used to compute shortest paths. It / OSMnx may only import or validate OSM data.

### BFS

FIFO queue. A node is marked visited **when enqueued**. Optimal for **fewest edges** on an unweighted graph. On a real network with unequal lengths, the BFS path’s metre/second cost may be worse than Dijkstra/A\*. The UI still reports that weighted cost honestly.

### DFS

LIFO stack plus a closed set. Returns the first path that hits the goal. Valid if one exists; **not** generally optimal in hops, distance, or time.

### Dijkstra (uniform-cost search)

Priority queue on \(g(n)\). Relaxes an edge when a cheaper path is found. **Optimal** for non-negative edge weights. Uses the **same** objective (distance or time) as A\* in a comparison.

### A\*

\[
f(n) = g(n) + h(n)
\]

- \(g(n)\): cost of the cheapest known path from the start.
- \(h(n)\): heuristic estimate of remaining cost.
- \(f(n)\): estimated total cost through \(n\).

**Distance heuristic:** great-circle (haversine) metres to the goal. Admissible because no road can be shorter than the straight-line distance on the Earth model we use.

**Time heuristic:** that distance divided by **90 km/h**, an upper bound on the estimated class speeds in this project. Congestion multipliers are \(\ge 1\), so they cannot make travel faster than this bound. If you later add edges faster than 90 km/h, the time heuristic would no longer be admissible.

**Optimality assumptions:** non-negative costs; admissible \(h\); stale heap entries ignored; deterministic tie-break (insertion counter).

## 5. Dynamic environment and re-planning

The base graph is immutable. A per-simulation **overlay** stores blocked flags and congestion multipliers.

1. Plan an initial route.
2. Move the ambulance along **edge geometry**, node by node.
3. A user click, or a deterministic auto-block after \(k\) hops, changes an edge.
4. If the remaining path uses a missing/blocked edge and re-planning is on, A\* (or the selected algorithm) runs **from the current node**.
5. The old remaining route is shown dashed; the new route is solid.
6. If re-planning is **off** and the **next** edge is blocked, the agent **stops**. It never animates through an impassable road.
7. Congestion without a block: the no-replan control may continue, paying a higher estimated time; the replan run may choose another path.

If no alternative exists, status is `failed`. Arrival is claimed **only** when the current node is the goal.

## 6. Why this is not machine learning

No parameters are trained on data. Behaviour is defined by the search procedure, the cost model, and the overlay. Changing the heuristic or the overlay changes the plan immediately; there is no “learning from past trips.”

## 7. OpenStreetMap data

- Study area: configurable radius around Nagpur centre `(21.1458, 79.0882)`, default **2200 m** (about 4 km across).
- Download via **OSMnx** when available, otherwise the **Overpass API**.
- Cached as JSON under `backend/data/nagpur_*.json`. Reuse the cache; do not repeatedly download the same bbox.
- Tiles: `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` with attribution **© OpenStreetMap contributors**.
- Comply with OSM tile and Overpass usage: keep the bbox small, cache results, do not hammer the servers.

If download fails, the API returns an error and will load a previous cache when one exists.

## 8. Simulated congestion vs live traffic

| Live traffic | This project |
| --- | --- |
| Probe GPS, city feeds, paid APIs | User or scenario sets a multiplier \(\ge 1\) on selected edges |
| Changes continuously | Changes only when you apply an event |
| Observed speed | `base_time × multiplier` |

Never describe the orange overlay as “real-time Nagpur traffic.”

## 9. Project layout

```
AI_Route_Agent/
  backend/app/          FastAPI app, graph, algorithms, OSM loader, simulation
  backend/tests/        pytest (toy graph is fully offline)
  backend/data/         cached OSM extracts (created after first download)
  frontend/             React + Vite + TypeScript + Leaflet + Recharts
  requirements.txt
  README.md
```

The eight-node **toy graph** (`backend/app/toy_graph.py`) is a separate educational demo. Independent check: **A→E→F→G→H = 11 m** is cheaper than A→B→F→G→H and A→B→C→D→H on that layout.

## 10. Setup on Windows

Install **Python 3.11 or 3.12**, **Node.js 18+**, and Git. A first Nagpur download needs internet.

Open **PowerShell** in the project folder:

```powershell
cd C:\Users\ASUS\Downloads\PROJECTS\AI_Route_Agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `Activate.ps1` is blocked:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Frontend:

```powershell
cd frontend
npm install
```

### Run the backend

```powershell
cd C:\Users\ASUS\Downloads\PROJECTS\AI_Route_Agent
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs

### Run the frontend

```powershell
cd C:\Users\ASUS\Downloads\PROJECTS\AI_Route_Agent\frontend
npm run dev
```

UI: http://127.0.0.1:5173  
Vite proxies `/api` to the backend. On first use click **Load / download map** (internet) or **Cache only** if `backend/data` already has a JSON extract.

### Tests

```powershell
cd C:\Users\ASUS\Downloads\PROJECTS\AI_Route_Agent
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Toy-graph, algorithm, re-planning and API tests are **offline**. Tests named `test_osm_optional.py` **skip** until a cached OSM file exists.

## 11. Suggested demonstration (viva)

1. Switch graph to **eight-node teaching graph**, start A, goal H, A\* distance → path A–E–F–G–H, cost 11 m.
2. Compare all four algorithms. Dijkstra and A\* match; BFS/DFS may not be metre-optimal.
3. Load the Nagpur extract. Click origin and destination. Confirm snap distances. Plan with A\*.
4. Run simulation. Enable **block** mode, click a road **ahead** of the ambulance. Dashed old remainder, solid new route.
5. Repeat with re-planning **off** and show the ambulance **stopping**.
6. State clearly that orange roads are simulated congestion.

## 12. API (selected)

| Method | Path | Role |
| --- | --- | --- |
| GET | `/api/health` | Process and graph status |
| GET | `/api/map/info` | Centre, stats, samples, road GeoJSON |
| POST | `/api/map/snap` | Snap a lat/lon click to the nearest road node |
| POST | `/api/map/load` | Download or cache load |
| POST | `/api/route/calculate` | One algorithm |
| POST | `/api/route/compare` | BFS, DFS, Dijkstra, A\* on the same instance |
| POST | `/api/simulation/start` | Begin travel + optional auto-block |
| POST | `/api/simulation/{id}/advance` | Move along remaining nodes |
| POST | `/api/simulation/{id}/event` | Block / unblock / congestion |
| POST | `/api/simulation/replan` or `/{id}/replan` | Re-search from current node |
| GET | `/api/simulation/{id}` | Snapshot |
| GET | `/api/scenarios` | Toy baseline catalogue |
| POST | `/api/experiments/run` | Reproducible toy experiments |
| GET | `/api/explanations` | Syllabus phrasing for the UI |

Responses use node IDs, edge ids, polylines and metrics — not raw NetworkX objects.

## 13. Known limitations and future scope

- Study area is small by design; a city-wide graph is heavier than a typical lab PC download.
- No live traffic, no guaranteed hospital POIs, no turn restrictions beyond OSM one-way geometry as imported.
- DFS/BFS on a large OSM graph can explore many nodes; that is expected.
- Search traces are capped (default 2500 events) so the browser stays usable; the search itself still runs to completion.
- Heuristic admissibility for **time** depends on the 90 km/h cap and congestion \(\ge 1\).
- Future: turn costs, time-dependent speeds from an open data feed (still labelled as estimates), multi-ambulance allocation, contraction hierarchies for larger extracts.

## 14. Viva questions (short answers)

**Q. What is the state space?**  
A. The finite set of road-graph nodes. Branching factor is the number of outgoing driveable edges.

**Q. Is BFS optimal here?**  
A. Optimal in number of edges if every edge has equal cost. Not optimal for metres or estimated seconds when costs differ.

**Q. Why is straight-line distance admissible for A\* on length?**  
A. Any walk on the Earth is at least as long as the great-circle chord we use; \(h(n) \le h^*(n)\).

**Q. Why divide by 90 km/h for time?**  
A. \(h\) must not overestimate remaining time. Using a speed **above** every modelled free-flow speed keeps \(h\) optimistic.

**Q. Open vs closed list?**  
A. Open = frontier waiting to be expanded. Closed = already expanded (with stale-heap handling in Dijkstra/A\*).

**Q. What happens if the hospital is in another component?**  
A. Search returns `found: false`. The agent must not report arrival.

**Q. Is this AI or GIS?**  
A. GIS supplies the environment. AI supplies uninformed/informed search, heuristics, and re-planning. Leaflet only displays results.

**Q. Did you use NetworkX shortest_path?**  
A. No. Custom BFS/DFS/Dijkstra/A\* in `algorithms.py`. OSMnx/NetworkX may build the graph from OSM.

## 15. Academic honesty

Do not claim live traffic, named hospitals that OSM did not provide, or runtime speed-ups you did not measure. CPU search time is reported separately from UI animation time.
