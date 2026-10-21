import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Ambulance,
  CheckCircle2,
  LocateFixed,
  Pause,
  Play,
  RotateCcw,
  Route as RouteIcon,
  Siren,
  X,
} from "lucide-react";
import { AmbuAssist } from "./AmbuAssist";
import type { AmbuAssistContext } from "./assistantLogic";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "./api";
import { MapView } from "./MapView";
import type {
  AlgorithmName,
  CompareResponse,
  DeviceLocation,
  GraphMode,
  MapInfo,
  ObjectiveName,
  PickMode,
  RouteResult,
  SampleWaypoint,
  SearchEvent,
  SimulationSnapshot,
  Snap,
} from "./types";

const NAGPUR_CENTER = { lat: 21.1458, lon: 79.0882 };
const NAGPUR_CITY_RADIUS_M = 12000;
const MAX_MAP_RADIUS_M = 15000;

function fmt(n: number | null | undefined, digits = 1, unit = "") {
  if (n === null || n === undefined || Number.isNaN(n) || !Number.isFinite(n)) return "—";
  return `${n.toFixed(digits)}${unit ? " " + unit : ""}`;
}

function distanceMeters(a: { lat: number; lon: number }, b: { lat: number; lon: number }) {
  const radians = (degrees: number) => (degrees * Math.PI) / 180;
  const lat1 = radians(a.lat);
  const lat2 = radians(b.lat);
  const dLat = lat2 - lat1;
  const dLon = radians(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 6_371_000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function formatSimEvent(e: Record<string, unknown>): string {
  const t = String(e.type || "");
  if (t === "plan") return `plan found=${String(e.found)} cost=${String(e.cost ?? "—")} explored=${String(e.explored)}`;
  if (t === "replan") return `replan #${String(e.count)} from ${String(e.from)} found=${String(e.found)} cost=${String(e.cost ?? "none")}`;
  if (t === "road_event") {
    return `${String(e.event_type)} ${String(e.edge_id)} affected=${String(e.affected_remaining_route)} t_before=${fmtTime(e.remaining_time_before_s as number)} t_after=${fmtTime(e.remaining_time_after_s as number)}`;
  }
  if (t === "stopped" || t === "fail" || t === "arrived") return `${t} ${String(e.reason || e.at || "")}`;
  return JSON.stringify(e);
}

function densify(points: [number, number][], steps: number): [number, number][] {
  if (points.length < 2) return points;
  const out: [number, number][] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [a, b] = [points[i], points[i + 1]];
    for (let s = 0; s < steps; s++) {
      const t = s / steps;
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

function fmtTime(s: number | null | undefined) {
  if (s === null || s === undefined || !Number.isFinite(s)) return "—";
  if (s < 90) return `${s.toFixed(1)} s (estimate)`;
  return `${(s / 60).toFixed(1)} min (estimate)`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

type NotificationLevel = "safe" | "warning" | "danger";

interface RouteNotification {
  id: number;
  level: NotificationLevel;
  title: string;
  message: string;
}

function BaselineResults({ experiment }: { experiment: Record<string, unknown> }) {
  const replanRuns = [
    ["With re-planning", experiment.with_replanning],
    ["Without re-planning", experiment.without_replanning],
  ] as const;

  return (
    <div className="baseline-results">
      <h3>{String(experiment.title || "Baseline result")}</h3>
      {typeof experiment.note === "string" && <p className="hint">{experiment.note}</p>}
      {Array.isArray(experiment.rows) && experiment.rows.length > 0 && (
        <div className="table-scroll">
          <table className="baseline-table">
            <thead>
              <tr><th>Algorithm</th><th>Objective</th><th>Found</th><th>Distance</th><th>Est. time</th><th>Nodes explored</th></tr>
            </thead>
            <tbody>
              {experiment.rows.map((value, index) => {
                if (!isRecord(value)) return null;
                return (
                  <tr key={`${String(value.algorithm)}-${String(value.objective)}-${index}`}>
                    <td>{String(value.algorithm || "—")}</td>
                    <td>{String(value.objective || "—")}</td>
                    <td>{value.found ? "Yes" : "No"}</td>
                    <td>{fmt(typeof value.distance_m === "number" ? value.distance_m : null, 1, "m")}</td>
                    <td>{fmtTime(typeof value.time_s === "number" ? value.time_s : null)}</td>
                    <td>{typeof value.explored === "number" ? value.explored : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {replanRuns.some(([, value]) => isRecord(value)) && (
        <div className="baseline-run-grid">
          {replanRuns.map(([label, value]) => {
            if (!isRecord(value)) return null;
            return (
              <article className="baseline-run" key={label}>
                <h4>{label}</h4>
                <dl className="kv">
                  <dt>Outcome</dt><dd>{String(value.status || (value.completed ? "arrived" : "not completed"))}</dd>
                  <dt>Re-plans</dt><dd>{typeof value.replan_count === "number" ? value.replan_count : "—"}</dd>
                  <dt>Distance travelled</dt><dd>{fmt(typeof value.distance_travelled_m === "number" ? value.distance_travelled_m : null, 1, "m")}</dd>
                  <dt>Distance remaining</dt><dd>{fmt(typeof value.remaining_distance_m === "number" ? value.remaining_distance_m : null, 1, "m")}</dd>
                  <dt>Est. time remaining</dt><dd>{fmtTime(typeof value.remaining_time_s === "number" ? value.remaining_time_s : null)}</dd>
                </dl>
              </article>
            );
          })}
        </div>
      )}
      {typeof experiment.status === "string" && (
        <p className="baseline-status">Outcome: <strong>{experiment.status}</strong>. The agent reports failure rather than claiming arrival when no route exists.</p>
      )}
      {experiment.found === false && !replanRuns.some(([, value]) => isRecord(value)) && (
        <p className="baseline-status">No route was found in this scenario. This demonstrates that the planner does not claim success when the destination cannot be reached.</p>
      )}
    </div>
  );
}

export default function App() {
  const [info, setInfo] = useState<MapInfo | null>(null);
  const [explanations, setExplanations] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>("");
  const [notice, setNotice] = useState<string>("");
  const [notification, setNotification] = useState<RouteNotification | null>(null);
  const [busy, setBusy] = useState(false);

  const [graphMode, setGraphMode] = useState<GraphMode>("nagpur");
  const [algorithm, setAlgorithm] = useState<AlgorithmName>("astar");
  const [objective, setObjective] = useState<ObjectiveName>("distance");
  const [replanEnabled, setReplanEnabled] = useState(true);
  const [autoBlockAfter, setAutoBlockAfter] = useState<number>(2);
  const [useAutoBlock, setUseAutoBlock] = useState(false);
  const [distM, setDistM] = useState(NAGPUR_CITY_RADIUS_M);
  const [congestionMult, setCongestionMult] = useState(3);
  const [pickMode, setPickMode] = useState<PickMode>("start");
  const [start, setStart] = useState<Snap | null>(null);
  const [goal, setGoal] = useState<Snap | null>(null);
  const [deviceLocation, setDeviceLocation] = useState<DeviceLocation | null>(null);
  const [locationFocus, setLocationFocus] = useState<[number, number] | null>(null);
  const [locationStatus, setLocationStatus] = useState("Waiting for device location permission…");
  const [route, setRoute] = useState<RouteResult | null>(null);
  const [compare, setCompare] = useState<CompareResponse | null>(null);
  const [sim, setSim] = useState<SimulationSnapshot | null>(null);
  const [experiment, setExperiment] = useState<Record<string, unknown> | null>(null);
  const [scenarios, setScenarios] = useState<{ id: string; title: string; description: string }[]>([]);
  const [bottomTab, setBottomTab] = useState<"results" | "charts" | "experiments" | "concepts">("results");

  const [searchEvents, setSearchEvents] = useState<SearchEvent[]>([]);
  const [searchIndex, setSearchIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [playMode, setPlayMode] = useState<"search" | "drive" | null>(null);
  const [speedMs, setSpeedMs] = useState(350);
  const playingRef = useRef(false);
  const simIdRef = useRef<string | null>(null);
  const geomQueueRef = useRef<[number, number][]>([]);
  const notificationTimerRef = useRef<number | null>(null);
  const seenSimulationEventsRef = useRef<{ id: string | null; count: number }>({ id: null, count: 0 });
  const autoLocationFocusRef = useRef(false);
  const autoLocationSnapRef = useRef(false);
  const manualEndpointChoiceRef = useRef(false);
  const [ambulancePos, setAmbulancePos] = useState<[number, number] | null>(null);

  function showNotification(level: NotificationLevel, title: string, message: string) {
    if (notificationTimerRef.current !== null) window.clearTimeout(notificationTimerRef.current);
    setNotification({ id: Date.now(), level, title, message });
    notificationTimerRef.current = window.setTimeout(() => {
      setNotification(null);
      notificationTimerRef.current = null;
    }, 7000);
  }

  function dismissNotification() {
    if (notificationTimerRef.current !== null) {
      window.clearTimeout(notificationTimerRef.current);
      notificationTimerRef.current = null;
    }
    setNotification(null);
  }

  const nodeLookup = useMemo(() => {
    const map: Record<string, { lat: number; lon: number }> = {};
    const collections = [info?.roads, info?.toy_roads];
    for (const collection of collections) {
      const features = collection?.features as Array<{
        properties?: { u?: string; v?: string };
        geometry?: { coordinates?: number[][] };
      }> | undefined;
      if (!features) continue;
      for (const f of features) {
        const coords = f.geometry?.coordinates;
        if (!coords?.length) continue;
        const first = coords[0];
        const last = coords[coords.length - 1];
        if (f.properties?.u) map[String(f.properties.u)] = { lat: first[1], lon: first[0] };
        if (f.properties?.v) map[String(f.properties.v)] = { lat: last[1], lon: last[0] };
      }
    }
    if (start) map[start.node_id] = { lat: start.lat, lon: start.lon };
    if (goal) map[goal.node_id] = { lat: goal.lat, lon: goal.lon };
    if (sim?.current) map[sim.current.id] = sim.current;
    return map;
  }, [info, start, goal, sim]);

  const refreshInfo = useCallback(async () => {
    const [m, h] = await Promise.all([api.mapInfo(), api.health()]);
    setInfo(m);
    if (!m.loaded) {
      setNotice(h.map_status?.message || "Nagpur road network is not loaded yet.");
    } else {
      setNotice(m.status.message);
    }
  }, []);

  function formatGeolocationError(error: GeolocationPositionError): string {
    if (error.code === error.PERMISSION_DENIED) return "Location permission was denied. Allow location access in your browser, or choose the start on the map.";
    if (error.code === error.POSITION_UNAVAILABLE) return "Your device could not determine its location. You can still choose a start on the map.";
    if (error.code === error.TIMEOUT) return "Timed out while getting your location. Try again or choose a start on the map.";
    return "Could not get device location. You can still choose a start on the map.";
  }

  function readDeviceLocation(): Promise<DeviceLocation> {
    if (!navigator.geolocation) {
      return Promise.reject(new Error("This browser does not support device location. Choose a start on the map instead."));
    }
    return new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(
        ({ coords }) => resolve({
          lat: coords.latitude,
          lon: coords.longitude,
          accuracy_m: coords.accuracy,
        }),
        (error) => reject(new Error(formatGeolocationError(error))),
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 },
      );
    });
  }

  function invalidateTripForEndpointChange() {
    setPlaying(false);
    setPlayMode(null);
    setSim(null);
    setAmbulancePos(null);
    geomQueueRef.current = [];
    simIdRef.current = null;
    setRoute(null);
    setCompare(null);
    setSearchEvents([]);
    setSearchIndex(0);
  }

  async function applyDeviceLocationAsStart(location: DeviceLocation, automatic = false) {
    if (graphMode !== "nagpur") {
      setLocationStatus("Device GPS is shown on the map; choose a start on the teaching graph manually.");
      return;
    }
    try {
      const mapReady = await ensureNagpurMapForLocation(location);
      if (!mapReady || (automatic && manualEndpointChoiceRef.current)) return;
      const snapped = await api.snap({ lat: location.lat, lon: location.lon, graph_mode: "nagpur" });
      if (automatic && manualEndpointChoiceRef.current) return;
      if (snapped.snap_distance_m > 1200) {
        setLocationStatus("Device GPS is outside the loaded Nagpur road network. Choose a start inside the mapped area.");
        return;
      }
      manualEndpointChoiceRef.current = true;
      invalidateTripForEndpointChange();
      setStart(snapped);
      setPickMode("goal");
      setLocationStatus(`Start set from device GPS (snapped ${Math.round(snapped.snap_distance_m)} m to a road).`);
      setNotice("Device location set as the trip start. Select the destination on the map.");
    } catch (e) {
      setLocationStatus(`GPS is marked, but could not snap it to a road: ${String(e)}`);
    }
  }

  async function ensureNagpurMapForLocation(location: DeviceLocation): Promise<boolean> {
    const metadata = info?.nagpur?.meta;
    const radius = typeof metadata?.dist_m === "number" ? metadata.dist_m : 0;
    const bbox = metadata?.bbox;
    const containsLocation = isRecord(bbox)
      && typeof bbox.north === "number"
      && typeof bbox.south === "number"
      && typeof bbox.east === "number"
      && typeof bbox.west === "number"
      && location.lat <= bbox.north
      && location.lat >= bbox.south
      && location.lon <= bbox.east
      && location.lon >= bbox.west;
    const gpsDistanceFromCenter = distanceMeters(location, NAGPUR_CENTER);
    const requiredRadius = Math.max(NAGPUR_CITY_RADIUS_M, gpsDistanceFromCenter + 1200);
    if (requiredRadius > MAX_MAP_RADIUS_M) {
      setLocationStatus("Your device is outside the supported Nagpur road-network area. This planner can route to hospitals within Nagpur, not from another city.");
      return false;
    }
    const requestedRadius = Math.max(requiredRadius, Math.min(distM, MAX_MAP_RADIUS_M));
    if (radius >= requestedRadius && containsLocation) return true;

    setLocationStatus("Loading the city-wide Nagpur road network from OpenStreetMap. This may take a few minutes the first time…");
    setBusy(true);
    try {
      const res = await api.loadMap({
        dist_m: requestedRadius,
        lat: NAGPUR_CENTER.lat,
        lon: NAGPUR_CENTER.lon,
      });
      setDistM(requestedRadius);
      setInfo({
        ...(info as MapInfo),
        ...res,
        loaded: true,
        roads: res.roads,
        samples: res.samples,
        nagpur: res.stats
          ? { name: "nagpur-osm", node_count: res.stats.node_count, edge_count: res.stats.edge_count, meta: res.stats.meta || {} }
          : info?.nagpur,
        status: res.status,
      } as MapInfo);
      setGraphMode("nagpur");
      setNotice(res.status?.message || `Loaded ${res.stats?.node_count} road intersections across Nagpur.`);
      return true;
    } catch (e) {
      setLocationStatus(`Could not load the city-wide map: ${String(e)}. Check your internet connection and try again.`);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function useDeviceLocationAsStart() {
    manualEndpointChoiceRef.current = true;
    setLocationStatus("Getting current device location…");
    try {
      const location = await readDeviceLocation();
      setDeviceLocation(location);
      setLocationFocus([location.lat, location.lon]);
      autoLocationFocusRef.current = true;
      await applyDeviceLocationAsStart(location);
    } catch (e) {
      setLocationStatus(String(e));
    }
  }

  useEffect(() => {
    refreshInfo().catch((e) => setError(String(e)));
    api.explanations().then(setExplanations).catch(() => undefined);
    api.scenarios().then((s) => setScenarios(s.scenarios)).catch(() => undefined);
  }, [refreshInfo]);

  useEffect(() => {
    if (!navigator.geolocation) {
      setLocationStatus("Device location is not supported by this browser. Choose a start on the map.");
      return;
    }
    const watchId = navigator.geolocation.watchPosition(
      ({ coords }) => {
        const location = {
          lat: coords.latitude,
          lon: coords.longitude,
          accuracy_m: coords.accuracy,
        };
        setDeviceLocation(location);
        setLocationStatus(`Device GPS active (±${Math.round(coords.accuracy)} m).`);
        if (!autoLocationFocusRef.current) {
          autoLocationFocusRef.current = true;
          setLocationFocus([coords.latitude, coords.longitude]);
        }
      },
      (error) => setLocationStatus(formatGeolocationError(error)),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 },
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, []);

  useEffect(() => {
    if (
      !deviceLocation
      || graphMode !== "nagpur"
      || start
      || sim
      || manualEndpointChoiceRef.current
      || autoLocationSnapRef.current
    ) return;
    autoLocationSnapRef.current = true;
    void applyDeviceLocationAsStart(deviceLocation, true);
  }, [deviceLocation, graphMode, start, sim]);

  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);

  useEffect(() => {
    if (!playing || playMode !== "search") return;
    const t = window.setInterval(() => {
      setSearchIndex((i) => {
        if (i >= searchEvents.length - 1) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, speedMs);
    return () => window.clearInterval(t);
  }, [playing, playMode, speedMs, searchEvents.length]);

  useEffect(() => {
    if (!playing || playMode !== "drive" || !simIdRef.current) return;
    const t = window.setInterval(async () => {
      const id = simIdRef.current;
      if (!id || !playingRef.current) return;
      try {
        const queued = geomQueueRef.current;
        if (queued.length > 0) {
          const nextPt = queued.shift()!;
          setAmbulancePos(nextPt);
          return;
        }
        const next = await api.advance(id, 1);
        setSim(next);
        const geom = (next.last_moved_geometry || []).map(([lat, lon]) => [lat, lon] as [number, number]);
        if (geom.length > 1) {
          geomQueueRef.current = densify(geom, 6);
          const first = geomQueueRef.current.shift();
          if (first) setAmbulancePos(first);
        } else if (next.current) {
          setAmbulancePos([next.current.lat, next.current.lon]);
        }
        if (["arrived", "failed", "stopped"].includes(next.status) && geomQueueRef.current.length === 0) {
          setPlaying(false);
        }
      } catch (e) {
        setError(String(e));
        setPlaying(false);
      }
    }, Math.max(40, Math.floor(speedMs / 4)));
    return () => window.clearInterval(t);
  }, [playing, playMode, speedMs]);

  useEffect(() => {
    if (!sim) {
      seenSimulationEventsRef.current = { id: null, count: 0 };
      return;
    }
    if (seenSimulationEventsRef.current.id !== sim.id) {
      seenSimulationEventsRef.current = { id: sim.id, count: sim.events.length };
      return;
    }

    const previousCount = seenSimulationEventsRef.current.count;
    seenSimulationEventsRef.current.count = sim.events.length;
    const roadEvents = sim.events.slice(previousCount).filter((event) => event.type === "road_event");
    const newRoadEvent = roadEvents[roadEvents.length - 1];
    if (!newRoadEvent) return;

    const eventType = String(newRoadEvent.event_type || "");
    const affected = Boolean(newRoadEvent.affected_remaining_route);
    const rerouted = affected && sim.replan_count > 0 && sim.status === "running";
    if (eventType === "block") {
      if (sim.status === "failed" || sim.status === "stopped") {
        showNotification("danger", "Blocked road alert", sim.status === "stopped"
          ? "The road ahead is blocked. The ambulance stopped because re-planning is unavailable."
          : "The road is blocked and no alternative route was found.");
      } else {
        showNotification("warning", "Blocked road alert", affected
          ? rerouted
            ? "The selected route was affected. A new route has been calculated from the ambulance's current junction."
            : "The selected route was affected. Re-planning is not enabled."
          : "The road is blocked, but it does not affect the current route.");
      }
    } else if (eventType === "congestion") {
      const multiplier = Number(newRoadEvent.congestion);
      const detail = Number.isFinite(multiplier) ? ` Simulated congestion: ×${multiplier}.` : "";
      showNotification("warning", "Congestion alert", `${affected && rerouted
        ? "The route was affected and has been recalculated."
        : affected
          ? "The route was affected."
          : "The congestion is not on the current route."}${detail} This is not live traffic data.`);
    } else if (eventType === "unblock") {
      showNotification("safe", "Road reopened", "The selected road is no longer blocked.");
    }
  }, [sim]);

  useEffect(() => () => {
    if (notificationTimerRef.current !== null) window.clearTimeout(notificationTimerRef.current);
  }, []);

  const samples: SampleWaypoint[] = graphMode === "toy" ? info?.toy_samples || [] : info?.samples || [];
  const roads = graphMode === "nagpur" ? info?.roads : info?.toy_roads;
  const center: [number, number] = graphMode === "toy"
    ? [start?.lat || 21.15, start?.lon || 79.08]
    : [start?.lat || info?.center.lat || 21.1458, start?.lon || info?.center.lon || 79.0882];

  async function loadMap(force = false, cacheOnly = false) {
    setBusy(true);
    setError("");
    try {
      const res = await api.loadMap({
        dist_m: distM,
        lat: NAGPUR_CENTER.lat,
        lon: NAGPUR_CENTER.lon,
        force_download: force,
        use_cache_only: cacheOnly,
      });
      setInfo({
        ...(info as MapInfo),
        ...res,
        loaded: true,
        roads: res.roads,
        samples: res.samples,
        nagpur: res.stats
          ? { name: "nagpur-osm", node_count: res.stats.node_count, edge_count: res.stats.edge_count, meta: res.stats.meta || {} }
          : info?.nagpur,
        status: res.status,
      } as MapInfo);
      setNotice(res.status?.message || `Loaded ${res.stats?.node_count} nodes.`);
      setGraphMode("nagpur");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function endpoints() {
    if (!start || !goal) throw new Error("Select a start and a hospital destination first.");
    return {
      graph_mode: graphMode,
      start_node: start.node_id,
      goal_node: goal.node_id,
      algorithm,
      objective,
    };
  }

  async function calculate() {
    setBusy(true);
    setError("");
    try {
      const body = { ...endpoints(), include_events: true, max_events: 2500 };
      const res = await api.calculate(body);
      setRoute(res);
      setCompare(null);
      setSearchEvents(res.events || []);
      setSearchIndex(0);
      setSim(null);
      if (res.start_snap) setStart(res.start_snap);
      if (res.goal_snap) setGoal(res.goal_snap);
      if (!res.found) setError(res.error_hint || "No route found.");
      else {
        setNotice(`${res.algorithm} found a route. Cost ${fmt(res.cost, 2)} ${res.cost_unit}.`);
        showNotification(
          "safe",
          "Clear route found",
          `Estimated distance: ${fmt(res.distance_m, 1, "m")}. Estimated travel time: ${fmtTime(res.time_s)}. Congestion and road safety are not monitored live.`,
        );
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runCompare() {
    setBusy(true);
    setError("");
    try {
      const res = await api.compare({ ...endpoints(), include_events: false });
      setCompare(res);
      setBottomTab("charts");
      setNotice(res.note);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runSimulation() {
    setBusy(true);
    setError("");
    try {
      const res = await api.startSim({
        ...endpoints(),
        replan_enabled: replanEnabled,
        auto_block_after: useAutoBlock ? autoBlockAfter : null,
        include_events: true,
      });
      setSim(res);
      setCompare(null);
      simIdRef.current = res.id;
      geomQueueRef.current = [];
      if (res.current) setAmbulancePos([res.current.lat, res.current.lon]);
      setRoute(res.last_search ? {
        ...res.last_search,
        distance_m: res.remaining_distance_m ?? res.last_search.distance_m ?? null,
        time_s: res.remaining_time_s ?? res.last_search.time_s ?? null,
        objective: res.last_search.objective || res.objective,
      } : null);
      setSearchEvents(res.last_search?.events || []);
      setSearchIndex(Math.max(0, (res.last_search?.events?.length || 1) - 1));
      if (res.start_snap) setStart(res.start_snap);
      if (res.goal_snap) setGoal(res.goal_snap);
      if (res.status === "failed") {
        setError("Initial search found no route.");
        showNotification("danger", "No route available", "The planner could not find a route to the selected destination.");
      }
      else {
        setPlayMode("drive");
        setPlaying(true);
        setNotice("Simulation running along the computed road geometry.");
        showNotification(
          "safe",
          "Clear route found",
          `Estimated remaining distance: ${fmt(res.remaining_distance_m, 1, "m")}. Estimated remaining time: ${fmtTime(res.remaining_time_s)}. Congestion is simulated, not live.`,
        );
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function resetAll() {
    setPlaying(false);
    setPlayMode(null);
    setSim(null);
    setAmbulancePos(null);
    geomQueueRef.current = [];
    setRoute(null);
    setCompare(null);
    setSearchEvents([]);
    setSearchIndex(0);
    dismissNotification();
    simIdRef.current = null;
    setNotice("Reset. Road overlays from a previous simulation are cleared; the OSM graph is unchanged.");
  }

  async function onMapClick(lat: number, lon: number) {
    if (pickMode !== "start" && pickMode !== "goal") return;
    if (pickMode === "start") manualEndpointChoiceRef.current = true;
    try {
      const snapped = await api.snap({ lat, lon, graph_mode: graphMode });
      if (pickMode === "start") {
        invalidateTripForEndpointChange();
        setStart(snapped);
        setPickMode("goal");
        setNotice(`Start snapped to node ${snapped.node_id} (${snapped.snap_distance_m} m from click). Click the map to set the destination.`);
      } else if (pickMode === "goal") {
        invalidateTripForEndpointChange();
        setGoal(snapped);
        setPickMode("idle");
        setNotice(`Goal snapped to node ${snapped.node_id} (${snapped.snap_distance_m} m from click).`);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function onRoadClick(edgeId: string, name: string) {
    if (!sim) {
      setNotice(`Selected road ${name || edgeId}. Start a simulation to apply a block or congestion event.`);
      return;
    }
    try {
      if (pickMode === "block") {
        const already = sim.blocked_edges.includes(edgeId);
        const next = await api.event(sim.id, {
          event_type: already ? "unblock" : "block",
          edge_id: edgeId,
          auto_replan: replanEnabled,
        });
        setSim(next);
        if (next.current) setAmbulancePos([next.current.lat, next.current.lon]);
        setNotice(
          already
            ? `Unblocked ${name}.`
            : `Blocked ${name}. Affected remaining route: ${next.affected ? "yes" : "no"}. Replanned: ${next.replanned ? "yes" : "no"}.`,
        );
      } else if (pickMode === "congestion") {
        const next = await api.event(sim.id, {
          event_type: "congestion",
          edge_id: edgeId,
          congestion: congestionMult,
          auto_replan: replanEnabled,
        });
        setSim(next);
        if (next.current) setAmbulancePos([next.current.lat, next.current.lon]);
        setNotice(`Simulated congestion ×${congestionMult} on ${name}. This is not live traffic.`);
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function runScenario(id: string) {
    setBusy(true);
    setError("");
    try {
      const out = await api.experiment(id, "toy");
      setExperiment(out);
      setBottomTab("experiments");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const ev = searchEvents[searchIndex];
  const agentStatus = sim
    ? sim.status
    : route?.found
      ? "plan ready"
      : info?.loaded
        ? "idle"
        : "waiting for map";

  const eventTimeChart = (sim?.events || [])
    .filter((e) => e.type === "road_event")
    .map((e, i) => ({
      name: `event ${i + 1}`,
      before: typeof e.remaining_time_before_s === "number" ? e.remaining_time_before_s : 0,
      after: typeof e.remaining_time_after_s === "number" ? e.remaining_time_after_s : 0,
    }));

  const chartRows = compare?.rows || (route ? [route] : []);
  const chartData = chartRows.map((r) => ({
    name: r.algorithm,
    cost: r.found && r.cost !== null ? r.cost : 0,
    explored: r.explored,
    timeMs: r.execution_time_s * 1000,
    travel: r.found && Number.isFinite(r.time_s)
      ? r.time_s
      : r.found && r.objective === "time" && Number.isFinite(r.cost)
        ? r.cost
        : 0,
    found: r.found,
  }));

  const assistantContext: AmbuAssistContext = {
    algorithm,
    objective,
    start,
    goal,
    route,
    comparison: compare,
    simulation: sim,
    replanEnabled: sim ? sim.replan_enabled && replanEnabled : replanEnabled,
    playing,
    pickMode,
    congestionMultiplier: congestionMult,
  };

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>AI Emergency Ambulance Route Agent</h1>
          <p className="sub">Nagpur OSM road graph · search-based planner (BFS / DFS / Dijkstra / A*) · not a machine-learning model</p>
        </div>
        <div className="badges">
          <span className={`badge ${sim ? "on" : ""}`}>
            <Activity size={12} /> Agent: {agentStatus}
          </span>
          <span className={`badge ${info?.loaded ? "on" : "warn"}`}>
            Roads: {info?.loaded ? `${info.nagpur?.node_count ?? "cached"} nodes` : "not loaded"}
          </span>
          <span className={`badge ${replanEnabled ? "on" : "off"}`}>
            Re-planning: {replanEnabled ? "enabled" : "disabled"}
          </span>
          <span className="badge warn">Congestion is simulated</span>
        </div>
      </header>

      <div className="workspace">
        <aside className="panel">
          <h2>Mission control</h2>
          {error && <div className="err">{error}</div>}
          {notice && <div className="ok">{notice}</div>}
          <p className="hint">
            Click the map to snap an ambulance origin, then a destination. Coordinates are snapped to real OSM intersections — routes follow road edges, not straight lines.
          </p>

          <div className="field">
            <label>Graph</label>
            <select value={graphMode} onChange={(e) => setGraphMode(e.target.value as GraphMode)}>
              <option value="nagpur">Nagpur OSM network</option>
              <option value="toy">Eight-node teaching graph</option>
            </select>
          </div>
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => loadMap(false, false)}>Load / download map</button>
            <button className="btn secondary" disabled={busy} onClick={() => loadMap(false, true)}>Cache only</button>
            <button className="btn ghost" disabled={busy} onClick={() => loadMap(true, false)}>Force re-download</button>
          </div>
          <div className="field">
            <label>City-wide road coverage radius (m) around Nagpur — first download needs internet</label>
            <input type="number" min={800} max={MAX_MAP_RADIUS_M} value={distM} onChange={(e) => setDistM(Number(e.target.value))} />
          </div>

          <div className="field">
            <label>Sample origins / destinations (approximate public areas, not a hospital registry)</label>
            <select
              defaultValue=""
              onChange={(e) => {
                const s = samples.find((x) => x.id === e.target.value);
                if (!s) return;
                if (s.kind !== "hospital") manualEndpointChoiceRef.current = true;
                invalidateTripForEndpointChange();
                if (s.kind === "hospital") setGoal(s.snap);
                else setStart(s.snap);
              }}
            >
              <option value="">Choose a sample point…</option>
              {samples.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </div>
          <div className="field device-location-control">
            <button className="btn secondary" disabled={busy || graphMode !== "nagpur"} onClick={() => { void useDeviceLocationAsStart(); }}>
              <LocateFixed size={14} /> Use my location as start
            </button>
            <p className="hint" aria-live="polite">{locationStatus}</p>
          </div>

          <div className="field">
            <label>Objective (same weights for every algorithm)</label>
            <select value={objective} onChange={(e) => setObjective(e.target.value as ObjectiveName)}>
              <option value="distance">Shortest distance (metres)</option>
              <option value="time">Fastest estimated time (seconds)</option>
            </select>
          </div>
          <div className="field">
            <label>Search algorithm</label>
            <select value={algorithm} onChange={(e) => setAlgorithm(e.target.value as AlgorithmName)}>
              <option value="astar">A* (heuristic)</option>
              <option value="dijkstra">Dijkstra (uniform-cost)</option>
              <option value="bfs">BFS (fewest edges)</option>
              <option value="dfs">DFS (not optimal)</option>
            </select>
          </div>

          <label className="hint">
            <input type="checkbox" checked={replanEnabled} onChange={(e) => setReplanEnabled(e.target.checked)} /> Enable mid-journey re-planning
          </label>
          <label className="hint">
            <input type="checkbox" checked={useAutoBlock} onChange={(e) => setUseAutoBlock(e.target.checked)} /> Auto-block a road ahead after
            <input
              type="number"
              style={{ width: 64, marginLeft: 6 }}
              value={autoBlockAfter}
              onChange={(e) => setAutoBlockAfter(Number(e.target.value))}
            /> hops
          </label>

          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy} onClick={calculate}><RouteIcon size={14} /> Plan route</button>
            <button className="btn danger" disabled={busy} onClick={runSimulation}><Ambulance size={14} /> Run simulation</button>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn secondary" disabled={busy} onClick={runCompare}>Compare BFS/DFS/Dijkstra/A*</button>
            <button className="btn ghost" onClick={resetAll}><RotateCcw size={14} /> Reset</button>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn ghost" onClick={() => { setPlayMode("search"); setPlaying(true); setSearchIndex(0); }} disabled={!searchEvents.length}>
              <Play size={14} /> Visualise search
            </button>
            <button className="btn ghost" onClick={() => setPlaying((p) => !p)}>
              {playing ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}
            </button>
          </div>
          <div className="field">
            <label>Animation interval (ms) — separate from CPU search time</label>
            <input type="range" min={80} max={1200} value={speedMs} onChange={(e) => setSpeedMs(Number(e.target.value))} />
          </div>
          <div className="field">
            <label>Search step {searchEvents.length ? searchIndex + 1 : 0} / {searchEvents.length}</label>
            <input
              type="range"
              min={0}
              max={Math.max(0, searchEvents.length - 1)}
              value={searchIndex}
              onChange={(e) => { setPlaying(false); setSearchIndex(Number(e.target.value)); }}
            />
          </div>

          <h2>Choose locations on map</h2>
          <p className="hint">Select a start or destination, then click the map. Select either again any time to change it.</p>
          <div className="row">
            {(["start", "goal", "block", "congestion"] as PickMode[]).map((m) => (
              <button
                key={m}
                className={`tab ${pickMode === m ? "active" : ""}`}
                onClick={() => {
                  setPickMode(m);
                  if (m === "start") manualEndpointChoiceRef.current = true;
                }}
              >
                {m === "start" ? "Set start" : m === "goal" ? "Set destination" : m}
              </button>
            ))}
          </div>
          <div className="field">
            <label>Simulated congestion multiplier</label>
            <input type="number" min={1} max={20} step={0.5} value={congestionMult} onChange={(e) => setCongestionMult(Number(e.target.value))} />
          </div>
          <p className="hint">Block / congestion apply to the active simulation. They do not come from a live traffic API.</p>
          {sim && (
            <button className="btn secondary" onClick={async () => { const s = await api.replan(sim.id); setSim(s); if (s.current) setAmbulancePos([s.current.lat, s.current.lon]); }}>
              <Siren size={14} /> Re-plan from current junction
            </button>
          )}
        </aside>

        <MapView
          center={center}
          zoom={graphMode === "toy" ? 18 : 14}
          mapKey={graphMode}
          roads={roads as never}
          pickMode={pickMode}
          start={start}
          goal={goal}
          sim={sim}
          routeGeom={route?.geometry || []}
          searchEvents={searchEvents}
          searchIndex={searchIndex}
          nodeLookup={nodeLookup}
          onMapClick={onMapClick}
          onRoadClick={onRoadClick}
          ambulancePos={ambulancePos}
          deviceLocation={deviceLocation}
          locationFocus={graphMode === "nagpur" ? locationFocus : null}
        />

        <aside className="panel right">
          <h2>Live information</h2>
          <dl className="kv">
            <dt>Start node</dt><dd>{start?.node_id || "—"}</dd>
            <dt>Snap distance</dt><dd>{start ? `${start.snap_distance_m} m` : "—"}</dd>
            <dt>Goal node</dt><dd>{goal?.node_id || "—"}</dd>
            <dt>Goal snap</dt><dd>{goal ? `${goal.snap_distance_m} m` : "—"}</dd>
            <dt>Ambulance node</dt><dd>{sim?.current_node || start?.node_id || "—"}</dd>
            <dt>Travelled</dt><dd>{fmt(sim?.distance_travelled_m, 1, "m")}</dd>
            <dt>Remaining distance</dt><dd>{fmt(sim?.remaining_distance_m, 1, "m")}</dd>
            <dt>Remaining time</dt><dd>{fmtTime(sim?.remaining_time_s)}</dd>
            <dt>Re-plans</dt><dd>{sim?.replan_count ?? 0}</dd>
            <dt>Completion</dt><dd>{sim ? sim.status : (route?.found ? "planned" : "—")}</dd>
          </dl>

          <h2>Current search step</h2>
          {ev ? (
            <dl className="kv">
              <dt>Event</dt><dd>{ev.t}</dd>
              <dt>Node</dt><dd>{ev.n}</dd>
              <dt>g(n)</dt><dd>{ev.g ?? "—"}</dd>
              <dt>h(n)</dt><dd>{ev.h ?? "—"}</dd>
              <dt>f(n)</dt><dd>{ev.f ?? "—"}</dd>
              <dt>Open size</dt><dd>{ev.open ?? "—"}</dd>
              <dt>Closed size</dt><dd>{ev.closed ?? "—"}</dd>
            </dl>
          ) : (
            <p className="hint">Plan a route or start a simulation to inspect the actual algorithm trace (open/closed lists).</p>
          )}
          {route?.open_sample && route.open_sample.length > 0 && (
            <>
              <h2>Open list sample (A* / Dijkstra)</h2>
              <div className="trace">{route.open_sample.map((o) => `${o.n}  g=${o.g} h=${o.h} f=${o.f}`).join("\n")}</div>
            </>
          )}
          {route?.closed_sample && route.closed_sample.length > 0 && (
            <>
              <h2>Closed list sample</h2>
              <div className="trace">{route.closed_sample.join(", ")}</div>
            </>
          )}

          <h2>Re-planning log</h2>
          <div className="trace">
            {(sim?.events || []).slice(-12).map((e) => formatSimEvent(e)).join("\n") || "No events yet."}
          </div>
          {route?.notes && <p className="hint">{route.notes}</p>}
          {route?.fairness_note && <p className="hint">{route.fairness_note}</p>}
        </aside>
      </div>

      <section className="bottom">
        <div className="tabs">
          <button className={`tab ${bottomTab === "results" ? "active" : ""}`} onClick={() => setBottomTab("results")}>Results</button>
          <button className={`tab ${bottomTab === "charts" ? "active" : ""}`} onClick={() => setBottomTab("charts")}>Charts</button>
          <button className={`tab ${bottomTab === "experiments" ? "active" : ""}`} onClick={() => setBottomTab("experiments")}>Baseline demos</button>
          <button className={`tab ${bottomTab === "concepts" ? "active" : ""}`} onClick={() => setBottomTab("concepts")}>AI concepts: how it works</button>
        </div>

        {bottomTab === "results" && (
          <>
            <h2>Algorithm comparison (same graph, start, goal, overlay, objective)</h2>
            <div className="table-scroll">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Algorithm</th>
                    <th>Found</th>
                    <th>Route cost</th>
                    <th>{sim ? "Remaining distance" : "Distance"}</th>
                    <th>{sim ? "Est. time left" : "Est. time"}</th>
                    <th>Explored nodes</th>
                    <th>CPU time (s)</th>
                    <th>Path</th>
                  </tr>
                </thead>
                <tbody>
                  {(compare?.rows || (route ? [route] : [])).map((r) => {
                    const distance = sim
                      ? sim.remaining_distance_m
                      : r.distance_m ?? (r.objective === "distance" ? r.cost : null);
                    const estimatedTime = sim
                      ? sim.remaining_time_s
                      : r.time_s ?? (r.objective === "time" ? r.cost : null);
                    const path = r.path || [];
                    return (
                      <tr key={r.algorithm + String(r.execution_time_s)}>
                        <td>{r.algorithm}</td>
                        <td>{r.found ? "yes" : "no"}</td>
                        <td>{fmt(r.cost, 2)} {r.cost_unit || ""}</td>
                        <td>{fmt(distance, 1, "m")}</td>
                        <td>{fmtTime(estimatedTime)}</td>
                        <td>{r.explored}</td>
                        <td>{fmt(r.execution_time_s, 4)}</td>
                        <td title={path.join(" → ")}>
                          {path.slice(0, 8).join(" → ")}{path.length > 8 ? " …" : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {compare?.optimality_check && (
              <p className="hint">
                A* vs Dijkstra cost difference: {compare.optimality_check.cost_difference}.
                Match: {compare.optimality_check.astar_matches_dijkstra ? "yes" : "no — inspect the graph/heuristic"}.
              </p>
            )}
          </>
        )}

        {bottomTab === "charts" && (
          <>
            <div className="charts-heading">
              <div>
                <h2>Compare route-planning performance</h2>
                <p className="hint">Use “Compare BFS/DFS/Dijkstra/A*” in Mission control to compare all four search methods on the same trip. CPU time is search computation time; travel time is an estimate, not live traffic.</p>
              </div>
              <button className="btn secondary" disabled={busy || !start || !goal} onClick={runCompare}>Compare algorithms</button>
            </div>
            {chartData.length === 0 ? (
              <div className="charts-empty">
                <strong>No route data to chart yet.</strong>
                <span>Select a start and destination, then compare the algorithms or plan one route.</span>
                <button className="btn" disabled={busy || !start || !goal} onClick={runCompare}>Run comparison</button>
              </div>
            ) : (
          <div className="charts">
            <div className="chart-card">
              <h3>Route cost ({compare?.objective === "time" || (!compare && route?.objective === "time") ? "estimated seconds" : "metres"})</h3>
              <div className="chart-plot"><ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value) => [value, "route cost"]} />
                  <Bar dataKey="cost" fill="#132c54" name="route cost" />
                </BarChart>
              </ResponsiveContainer></div>
            </div>
            <div className="chart-card">
              <h3>Explored nodes</h3>
              <div className="chart-plot"><ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value) => [value, "nodes explored"]} />
                  <Bar dataKey="explored" fill="#1c3d6e" name="nodes explored" />
                </BarChart>
              </ResponsiveContainer></div>
            </div>
            <div className="chart-card">
              <h3>CPU execution time (ms)</h3>
              <div className="chart-plot"><ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value) => [typeof value === "number" ? value.toFixed(3) : value, "CPU time (ms)"]} />
                  <Bar dataKey="timeMs" fill="#c62828" name="CPU time (ms)" />
                </BarChart>
              </ResponsiveContainer></div>
            </div>
            <div className="chart-card">
              <h3>Estimated travel time</h3>
              <div className="chart-plot"><ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value) => [typeof value === "number" ? fmtTime(value) : value, "estimated travel time"]} />
                  <Bar dataKey="travel" fill="#c05621" name="estimated travel time (s)" />
                </BarChart>
              </ResponsiveContainer></div>
            </div>
            <div className="chart-card event-chart-card">
              <h3>Remaining estimated time before vs after a road event (s)</h3>
              {eventTimeChart.length ? (
                <div className="chart-plot"><ResponsiveContainer width="100%" height="100%">
                  <BarChart data={eventTimeChart}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="before" fill="#6b7c93" name="before event" />
                    <Bar dataKey="after" fill="#c62828" name="after event / replan" />
                  </BarChart>
                </ResponsiveContainer></div>
              ) : (
                <p className="chart-empty-note">This chart is for changes during a trip. Start a simulation, then block or congest a road. Times are estimates, not live traffic.</p>
              )}
            </div>
          </div>
            )}
          </>
        )}

        {bottomTab === "experiments" && (
          <div className="baseline-panel">
            <div className="baseline-intro">
              <h2>What are baseline demos?</h2>
              <p>These are small, repeatable examples on an eight-junction teaching map. Use them to see how the planner behaves in a known situation before trying the larger Nagpur road map. They run offline and do not change your current route.</p>
              <p><strong>How to use:</strong> choose a scenario below. Its result explains whether a route was found, how much travel remains, or how re-planning handled a road change.</p>
            </div>
            <div className="baseline-grid">
              {scenarios.map((s) => (
                <article className="baseline-card" key={s.id}>
                  <h3>{s.title}</h3>
                  <p>{s.description}</p>
                  <button className="btn secondary" disabled={busy} onClick={() => runScenario(s.id)}>Run this demo</button>
                </article>
              ))}
            </div>
            {experiment && <BaselineResults experiment={experiment} />}
          </div>
        )}

        {bottomTab === "concepts" && (
          <div className="concept-panel">
            <div className="concept-intro">
              <h2>How does the AI route planner work?</h2>
              <p>This section explains the ideas behind the route search. It is useful for understanding or presenting the project; it does not control the map.</p>
              <ol>
                <li>Choose a start and destination on the map. Each click snaps to a road intersection.</li>
                <li>Choose shortest distance or fastest estimated time, then plan or compare algorithms.</li>
                <li>The search explores intersections and road segments, avoiding blocked roads.</li>
                <li>During a simulation, a road event can trigger a fresh search from the ambulance’s current junction.</li>
              </ol>
            </div>
            <div className="concept-grid">
              {Object.entries(explanations).map(([k, v]) => (
                <article className="concept-card" key={k}>
                  <h3>{k.replace(/_/g, " ")}</h3>
                  <p>{v}</p>
                </article>
              ))}
            </div>
            <p className="hint">{info?.traffic_disclaimer}</p>
            <p className="hint">{info?.hospital_disclaimer}</p>
          </div>
        )}
      </section>
      {notification && (
        <div className={`route-notification ${notification.level}`} role="status" aria-live="polite" key={notification.id}>
          {notification.level === "safe"
            ? <CheckCircle2 size={21} aria-hidden="true" />
            : <AlertTriangle size={21} aria-hidden="true" />}
          <div>
            <strong>{notification.title}</strong>
            <p>{notification.message}</p>
          </div>
          <button type="button" aria-label="Dismiss notification" onClick={dismissNotification}>
            <X size={17} />
          </button>
        </div>
      )}
      <AmbuAssist context={assistantContext} />
    </div>
  );
}
