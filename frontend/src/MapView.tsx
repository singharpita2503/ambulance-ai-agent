import { useEffect, useMemo } from "react";
import { Circle, CircleMarker, GeoJSON, MapContainer, Marker, Polyline, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import type { DeviceLocation, PickMode, SearchEvent, SimulationSnapshot, Snap } from "./types";

type RoadCollection = { type: "FeatureCollection"; features: Array<{ type: string; properties?: Record<string, unknown>; geometry?: unknown }> };

const ambulanceIcon = L.divIcon({
  className: "",
  html: '<div class="amb-dot">A</div>',
  iconSize: [26, 26],
  iconAnchor: [13, 13],
});
const hospitalIcon = L.divIcon({
  className: "",
  html: '<div class="hosp-dot">H</div>',
  iconSize: [26, 26],
  iconAnchor: [13, 13],
});
const startIcon = L.divIcon({
  className: "",
  html: '<div class="start-dot">S</div>',
  iconSize: [26, 26],
  iconAnchor: [13, 13],
});

function ClickCatcher({
  pickMode,
  onMapClick,
}: {
  pickMode: PickMode;
  onMapClick: (lat: number, lon: number) => void;
}) {
  useMapEvents({
    click(e) {
      if (pickMode === "start" || pickMode === "goal") {
        onMapClick(e.latlng.lat, e.latlng.lng);
      }
    },
  });
  return null;
}

function LocationFocus({ position }: { position: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.flyTo(position, Math.max(map.getZoom(), 15));
  }, [map, position]);
  return null;
}

function toLatLngs(geom?: number[][]): [number, number][] {
  if (!geom) return [];
  return geom.map(([lat, lon]) => [lat, lon]);
}

export function MapView({
  center,
  zoom = 14,
  mapKey = "map",
  roads,
  pickMode,
  start,
  goal,
  sim,
  routeGeom,
  searchEvents,
  searchIndex,
  nodeLookup,
  onMapClick,
  onRoadClick,
  ambulancePos,
  deviceLocation,
  locationFocus,
}: {
  center: [number, number];
  zoom?: number;
  mapKey?: string;
  roads?: RoadCollection;
  pickMode: PickMode;
  start: Snap | null;
  goal: Snap | null;
  sim: SimulationSnapshot | null;
  routeGeom: number[][];
  searchEvents: SearchEvent[];
  searchIndex: number;
  nodeLookup: Record<string, { lat: number; lon: number }>;
  onMapClick: (lat: number, lon: number) => void;
  onRoadClick: (edgeId: string, name: string) => void;
  ambulancePos?: [number, number] | null;
  deviceLocation?: DeviceLocation | null;
  locationFocus?: [number, number] | null;
}) {
  const blocked = new Set(sim?.blocked_edges || []);
  const congestion = sim?.congestion || {};
  const overlayKey = `${[...blocked].join(",")}|${Object.entries(congestion).join(";")}`;

  const styleFn = (feature?: { properties?: Record<string, unknown> }) => {
    const id = String(feature?.properties?.id || "");
    const cong = congestion[id] || 1;
    if (blocked.has(id)) return { color: "#c62828", weight: 4, opacity: 0.95 };
    if (cong > 1) return { color: "#c05621", weight: 3.5, opacity: 0.9 };
    return { color: "#8aa0b8", weight: 1.4, opacity: 0.55 };
  };

  const onEach = (feature: { properties?: Record<string, unknown> }, layer: L.Layer) => {
    layer.on("click", (e) => {
      L.DomEvent.stopPropagation(e as L.LeafletMouseEvent);
      const id = String(feature.properties?.id || "");
      const name = String(feature.properties?.name || id);
      if (pickMode === "block" || pickMode === "congestion") {
        onRoadClick(id, name);
      }
    });
  };

  const visibleEvents = searchEvents.slice(0, searchIndex + 1);
  const closedPts = useMemo(() => {
    const pts: [number, number][] = [];
    for (const ev of visibleEvents) {
      if (ev.t === "expand" && nodeLookup[ev.n]) {
        pts.push([nodeLookup[ev.n].lat, nodeLookup[ev.n].lon]);
      }
    }
    return pts;
  }, [visibleEvents, nodeLookup]);
  const openPts = useMemo(() => {
    const pts: [number, number][] = [];
    for (const ev of visibleEvents) {
      if (ev.t === "enqueue" && nodeLookup[ev.n]) {
        pts.push([nodeLookup[ev.n].lat, nodeLookup[ev.n].lon]);
      }
    }
    return pts;
  }, [visibleEvents, nodeLookup]);
  const currentEv = searchEvents[searchIndex];
  const currentNode = currentEv && nodeLookup[currentEv.n];

  const amb = ambulancePos
    ? ambulancePos
    : sim?.current
      ? [sim.current.lat, sim.current.lon] as [number, number]
      : start
        ? [start.lat, start.lon] as [number, number]
        : null;

  return (
    <div className="map-wrap">
      <MapContainer
        key={mapKey}
        center={center}
        zoom={zoom}
        preferCanvas
        style={{ height: "100%", width: "100%" }}
      >
        <LocationFocus position={locationFocus || null} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickCatcher pickMode={pickMode} onMapClick={onMapClick} />
        {roads && (
          <GeoJSON
            key={overlayKey + String(roads.features?.length || 0)}
            data={roads as never}
            style={styleFn}
            onEachFeature={onEach}
          />
        )}
        {openPts.slice(-80).map((p, i) => (
          <CircleMarker key={`o-${i}`} center={p} radius={4} pathOptions={{ color: "#3d7ea6", fillOpacity: 0.5, weight: 1 }} />
        ))}
        {closedPts.slice(-120).map((p, i) => (
          <CircleMarker key={`c-${i}`} center={p} radius={4} pathOptions={{ color: "#6b7c93", fillOpacity: 0.35, weight: 1 }} />
        ))}
        {currentNode && (
          <CircleMarker
            center={[currentNode.lat, currentNode.lon]}
            radius={8}
            pathOptions={{ color: "#c62828", fillColor: "#ff8a80", fillOpacity: 0.9, weight: 2 }}
          />
        )}
        {sim?.previous_geometry?.length ? (
          <Polyline positions={toLatLngs(sim.previous_geometry)} pathOptions={{ color: "#6b7c93", weight: 5, dashArray: "8 8", opacity: 0.85 }} />
        ) : null}
        {sim?.travelled_geometry?.length ? (
          <Polyline positions={toLatLngs(sim.travelled_geometry)} pathOptions={{ color: "#1b7f4e", weight: 5, opacity: 0.9 }} />
        ) : null}
        {(sim?.remaining_geometry?.length ? sim.remaining_geometry : routeGeom).length ? (
          <Polyline
            positions={toLatLngs(sim?.remaining_geometry?.length ? sim.remaining_geometry : routeGeom)}
            pathOptions={{ color: "#1a56a8", weight: 5, opacity: 0.95 }}
          />
        ) : null}
        {start && <Marker position={[start.lat, start.lon]} icon={startIcon} />}
        {goal && <Marker position={[goal.lat, goal.lon]} icon={hospitalIcon} />}
        {amb && <Marker position={amb} icon={ambulanceIcon} />}
        {deviceLocation && (
          <>
            <Circle
              center={[deviceLocation.lat, deviceLocation.lon]}
              radius={deviceLocation.accuracy_m}
              interactive={false}
              pathOptions={{ color: "#1676d2", fillColor: "#58a6ff", fillOpacity: 0.12, weight: 1 }}
            />
            <CircleMarker
              center={[deviceLocation.lat, deviceLocation.lon]}
              radius={7}
              interactive={false}
              pathOptions={{ color: "#fff", fillColor: "#1676d2", fillOpacity: 1, weight: 3 }}
            />
          </>
        )}
      </MapContainer>
      <div className="map-legend">
        <span><i className="location-swatch" /> Device location (GPS)</span>
        <span><i className="swatch" style={{ background: "#8aa0b8" }} /> OSM roads (cached extract)</span>
        <span><i className="swatch" style={{ background: "#1a56a8" }} /> Current planned route</span>
        <span><i className="swatch" style={{ background: "#6b7c93", height: 0, borderTop: "2px dashed #6b7c93" }} /> Previous remaining route</span>
        <span><i className="swatch" style={{ background: "#1b7f4e" }} /> Travelled</span>
        <span><i className="swatch" style={{ background: "#c62828" }} /> Simulated block</span>
        <span><i className="swatch" style={{ background: "#c05621" }} /> Simulated congestion</span>
      </div>
    </div>
  );
}
