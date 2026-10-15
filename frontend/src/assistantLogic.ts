import type { AlgorithmName, CompareResponse, ObjectiveName, RouteResult, SimulationSnapshot, Snap } from "./types";

export interface AmbuAssistContext {
  algorithm: AlgorithmName;
  objective: ObjectiveName;
  start: Snap | null;
  goal: Snap | null;
  route: RouteResult | null;
  comparison: CompareResponse | null;
  simulation: SimulationSnapshot | null;
  replanEnabled: boolean;
  playing: boolean;
  pickMode: string;
  congestionMultiplier: number;
}

export interface AmbuAssistResponder {
  respond(question: string, context: AmbuAssistContext): string | Promise<string>;
}

function formatNumber(value: number | null | undefined, digits = 1, unit = ""): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "not available";
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

function formatEstimate(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "not available";
  if (seconds < 90) return `${seconds.toFixed(1)} seconds (estimate)`;
  return `${(seconds / 60).toFixed(1)} minutes (estimate)`;
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function activeRoute(context: AmbuAssistContext): RouteResult | null {
  return context.simulation?.last_search || context.route;
}

function contextSummary(context: AmbuAssistContext): string {
  const route = activeRoute(context);
  const routeObjective = context.simulation?.objective || route?.objective || context.objective;
  const lines = [
    "",
    "Current application context:",
    `- Selected algorithm: ${context.algorithm.toUpperCase()}`,
    `- Selected objective: ${context.objective === "distance" ? "shortest distance" : "fastest estimated time"}`,
    `- Start: ${context.start ? `road node ${context.start.node_id}` : "not selected"}`,
    `- Destination: ${context.goal ? `road node ${context.goal.node_id}` : "not selected"}`,
  ];

  if (!route) {
    lines.push("- Route: not calculated yet");
  } else if (route.found) {
    lines.push(
      `- Route: found by ${route.algorithm.toUpperCase()}${route.path.length ? `; ${route.path.length} nodes` : ""}`,
      `- Route cost: ${formatNumber(route.cost, 2, route.cost_unit || (routeObjective === "distance" ? "m" : "estimated seconds"))}`,
      `- Distance: ${formatNumber(route.distance_m, 1, "m")}`,
      `- Estimated travel time: ${formatEstimate(route.time_s)}`,
      `- Search status: ${context.simulation?.status || "planned"}`,
    );
    if (route.path.length) lines.push(`- Path begins: ${route.path.slice(0, 6).join(" → ")}${route.path.length > 6 ? " → …" : ""}`);
  } else {
    lines.push(`- Route: no route found by ${route.algorithm.toUpperCase()}`);
    lines.push(`- Search status: ${context.simulation?.status || "no route found"}`);
    if (route.error_hint) lines.push(`- Planner message: ${route.error_hint}`);
  }

  const simulation = context.simulation;
  if (simulation) {
    lines.push(
      `- Current ambulance node: ${simulation.current_node}`,
      `- Re-planning: ${context.replanEnabled ? "enabled in controls" : "disabled in controls"}`,
      `- Re-plans completed: ${simulation.replan_count}`,
      `- Simulation status: ${simulation.status}`,
      `- Simulation animation: ${context.playing ? "playing" : "paused or stopped"}`,
    );
    if (simulation.distance_travelled_m !== null) {
      lines.push(`- Distance travelled: ${formatNumber(simulation.distance_travelled_m, 1, "m")}`);
    }
    if (simulation.remaining_distance_m !== null) {
      lines.push(`- Remaining distance: ${formatNumber(simulation.remaining_distance_m, 1, "m")}`);
    }
    if (simulation.remaining_time_s !== null) {
      lines.push(`- Remaining travel time: ${formatEstimate(simulation.remaining_time_s)}`);
    }
    lines.push(`- Blocked roads: ${simulation.blocked_edges.length ? simulation.blocked_edges.join(", ") : "none recorded"}`);
    const congested = Object.entries(simulation.congestion);
    lines.push(
      `- Congested roads: ${congested.length ? congested.map(([edge, multiplier]) => `${edge} ×${multiplier}`).join(", ") : "none recorded"}`,
    );
    const events = simulation.events.slice(-4);
    lines.push(`- Recent simulation events: ${events.length ? events.map(summarizeEvent).join("; ") : "none recorded"}`);
  } else {
    lines.push("- Simulation: not started; no ambulance movement or simulation events are available");
  }

  if (context.comparison) {
    const rows = context.comparison.rows.map((row) =>
      `${row.algorithm.toUpperCase()}: ${row.found ? `found, cost ${formatNumber(row.cost, 2, row.cost_unit || "")}, ${formatNumber(row.distance_m, 1, "m")}, ${formatEstimate(row.time_s)}` : "no route"}`,
    );
    lines.push(`- Algorithm comparison: ${rows.length ? rows.join("; ") : "completed with no result rows"}`);
  } else {
    lines.push("- Algorithm comparison: not run");
  }

  return lines.join("\n");
}

function summarizeEvent(event: Record<string, unknown>): string {
  const type = asText(event.type);
  if (type === "road_event") {
    const action = asText(event.event_type) || "road change";
    const edge = asText(event.edge_id) || "unknown road";
    return `${action} on ${edge}${event.affected_remaining_route === true ? " affected the remaining route" : " did not affect the remaining route"}`;
  }
  if (type === "replan") {
    const status = event.found === true ? "found a new route" : "found no alternative route";
    return `re-plan from ${asText(event.from) || "current node"} ${status}${asText(event.reason) ? ` (reason: ${String(event.reason)})` : ""}`;
  }
  if (type === "stopped" || type === "fail" || type === "arrived") {
    return `${type}${asText(event.reason) ? `: ${String(event.reason)}` : ""}`;
  }
  if (type === "plan") return `initial plan ${event.found === true ? "found a route" : "found no route"}`;
  return type || "recorded event";
}

function explainRouteChange(context: AmbuAssistContext): string {
  const events = context.simulation?.events || [];
  if (events.length === 0) {
    return "I can’t determine that a route changed: there is no simulation event log to verify it. Start a simulation and apply a road block or congestion event; if that event affects the remaining route and re-planning is enabled, the log will record the cause and result.";
  }

  let roadEventIndex = -1;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index].type === "road_event") {
      roadEventIndex = index;
      break;
    }
  }
  if (roadEventIndex < 0) {
    const replans = events.filter((event) => event.type === "replan");
    if (!replans.length) return "The simulation log contains no road-change or re-planning event, so I can’t verify a reason for a route change.";
    const latest = replans[replans.length - 1];
    return `The latest recorded re-plan started from node ${asText(latest.from) || "not recorded"}${asText(latest.reason) ? ` for ${String(latest.reason)}` : ""}. The log says it ${latest.found === true ? "found a new route" : "found no alternative route"}.`;
  }

  const roadEvent = events[roadEventIndex];
  const laterReplan = events.slice(roadEventIndex + 1).find((event) => event.type === "replan");
  const edge = asText(roadEvent.edge_id) || "an unnamed road";
  const change = asText(roadEvent.event_type) || "road change";
  if (roadEvent.affected_remaining_route !== true) {
    return `The latest logged event was ${change} on ${edge}, and the simulation recorded that it did not affect the remaining route. No route change can be attributed to that event.`;
  }
  if (laterReplan) {
    if (laterReplan.found === true) {
      return `The simulation log shows ${change} on ${edge} affected the remaining route. It then re-planned from node ${asText(laterReplan.from) || "not recorded"} and found a new route. The logged reason is ${asText(laterReplan.reason) || "not specified"}.`;
    }
    return `The simulation log shows ${change} on ${edge} affected the remaining route. It re-planned from node ${asText(laterReplan.from) || "not recorded"}, but the log reports no alternative route.`;
  }
  return `The simulation log shows ${change} on ${edge} affected the remaining route, but contains no subsequent re-plan event. Re-planning may be disabled or the simulation may have stopped; the log does not establish which.`;
}

function answerQuestion(question: string, context: AmbuAssistContext): string {
  const text = question.trim().toLowerCase();
  const route = activeRoute(context);

  if (/\b(start|begin|first|getting started)\b/.test(text) || text === "how do i start?") {
    return [
      "To plan your first route:",
      "1. In Mission control, leave the map click mode on “start” and click the ambulance’s starting road on the map.",
      "2. The mode changes to “goal”; click a destination road. Both clicks snap to nearby road intersections.",
      "3. Choose an algorithm and either shortest distance or fastest estimated time.",
      "4. Select “Plan route” to calculate a route. Use “Run simulation” only when you want to animate the trip.",
    ].join("\n");
  }
  if (/\b(destination|hospital|goal)\b/.test(text) && /\b(select|choose|set|pick|click|where)\b/.test(text)) {
    return "To select a destination:\n1. First choose the start by clicking its road; the map click mode then changes to “goal”.\n2. Click the destination road or intersection. The app snaps it to the nearest road-network junction.\n3. You can also choose an approximate sample destination from the sample-points list. These are not a verified live hospital registry.\n4. Confirm the goal node in Live information, then click “Plan route”.";
  }
  if (/\b(select|choose|change|switch)\b/.test(text) && /\b(algorithm|bfs|dfs|dijkstra|a\*)\b/.test(text)) {
    return "To choose a search algorithm:\n1. In Mission control, open the “Search algorithm” menu.\n2. Select BFS, DFS, Dijkstra, or A*.\n3. Choose the distance or estimated-time objective.\n4. Click “Plan route” to run the selected algorithm, or “Compare BFS/DFS/Dijkstra/A*” to compare all four on the same endpoints.";
  }
  if (/\b(plan|calculate|compute)\b/.test(text) && /\b(route|path)\b/.test(text)) {
    return "To calculate a route:\n1. Select a start and destination by clicking the map, or use the sample-point list.\n2. Select the distance or estimated-time objective and a search algorithm.\n3. Click “Plan route”. The Results tab shows the search result and the map displays the route.\n4. To animate travel, choose “Run simulation” instead.";
  }
  if (/\ba\*|a-star|astar\b/.test(text)) {
    return [
      "A* is a path-search algorithm. It ranks candidate intersections using f(n) = g(n) + h(n): g(n) is the cost already travelled, and h(n) estimates the remaining cost to the destination.",
      "Here, h is straight-line distance (or an estimated-time equivalent). With the project’s non-negative road costs and admissible heuristic, A* finds an optimal route for the selected objective.",
      "A* is a search algorithm, not a generative AI model.",
    ].join("\n");
  }
  if (/\b(block|blocked|road closure)\b/.test(text)) {
    return [
      "To simulate a blocked road:",
      "1. Select the start and destination, then choose “Run simulation”.",
      "2. In “Map click mode”, choose “block” and click the road segment on the map.",
      "3. If re-planning is enabled and the blocked road affects the remaining route, the agent searches again from its current junction. With re-planning off, it stops if the next road is blocked.",
      "This only changes the simulation overlay; it does not change real road conditions.",
    ].join("\n");
  }
  if (/\bwhy\b/.test(text) && /\b(route|path)\b/.test(text) && /\b(change|changed|different|replan)\b/.test(text)) {
    return explainRouteChange(context);
  }
  if (/\b(no route|unreachable|route available|can't reach|cannot reach)\b/.test(text)) {
    if (context.simulation?.status === "failed" || route?.found === false) {
      const failedReplan = [...(context.simulation?.events || [])].reverse().find((event) => event.type === "replan" && event.found === false);
      const detail = asText(failedReplan?.message) || route?.error_hint;
      return `The latest available result reports no route${detail ? `: ${detail}` : "."} This can happen when the destination is unreachable because of road direction, disconnected graph sections, or blocked roads. Check the selected endpoints and blocked-road list, then choose a reachable destination or remove a blocking overlay. I won’t assume a specific cause unless it appears in the application state.`;
    }
    if (!route) {
      return "No route has been calculated yet, so I can’t tell whether this trip is reachable. Select a start and destination on the map, then choose “Plan route”. The search result will report whether a path exists.";
    }
    return route.found
      ? "The current route result says a route was found. If you mean a different trip, select its endpoints and calculate again."
      : "The application has no successful route result for the current trip. Select endpoints and plan again after checking road direction and any blocked-road overlay.";
  }
  if (/\bcongestion|multiplier\b/.test(text)) {
    const requested = text.match(/\bmultiplier\s*(?:of\s*)?(\d+(?:\.\d+)?)\b/);
    const multiplier = requested ? Number(requested[1]) : context.congestionMultiplier;
    return [
      `A congestion multiplier of ${multiplier} means the affected road’s estimated travel time is multiplied by ${multiplier} compared with its base estimate. For example, ×2 doubles that road’s estimated time; it does not necessarily double the entire trip time.`,
      "To apply a multiplier:\n1. Start a simulation.\n2. Choose “congestion” in Map click mode and enter the multiplier.\n3. Click the road segment to apply the simulated slowdown.",
      `The currently selected control value is ×${context.congestionMultiplier}. That value alone does not mean congestion has already been applied.`,
      "Congestion is simulated; this app has no dependable live traffic feed.",
    ].join("\n");
  }
  if (/\b(compare|comparison|algorithms?)\b/.test(text)) {
    return "To compare algorithms:\n1. Select a start and destination.\n2. Set the objective (distance or estimated time).\n3. Click “Compare BFS/DFS/Dijkstra/A*” in Mission control.\n4. Review the Results table or Charts tab. BFS and DFS are not guaranteed to minimize weighted distance/time; Dijkstra and A* optimize the selected non-negative cost.";
  }
  if (/\b(chart|results?|interpret|cost|distance|estimated time)\b/.test(text)) {
    return "Results show whether a route was found, its objective cost, distance in metres, estimated travel time, expanded nodes, and CPU search time. Charts visualize route cost, explored nodes, CPU computation time, and estimated travel time. CPU time is not ambulance travel time. Travel times are model estimates, not live measurements. Compare algorithms only after selecting both endpoints and running the comparison.";
  }
  if (/\b(pause|resume|reset|simulation|run|animate)\b/.test(text)) {
    return "To control a trip:\n1. Select a start and destination, then click “Run simulation” to animate travel.\n2. Click “Pause” or “Resume” in Mission control to pause or continue the animation.\n3. Click “Reset” to clear the current route and simulation overlay.\n\n“Plan route” searches without animating the trip.";
  }
  if (/\breplan|re-planning|dynamic\b/.test(text)) {
    return "To enable dynamic re-planning:\n1. Turn on “Enable mid-journey re-planning” in Mission control.\n2. Start the simulation.\n3. Choose block or congestion in Map click mode, then click a road ahead.\n4. If that event affects the remaining route, the planner searches again from the ambulance’s current junction. Check the Live information event log for the recorded result.\n\nAmbuAssist itself never changes the route.";
  }
  if (/\b(bfs|dfs|dijkstra)\b/.test(text)) {
    return "BFS searches by fewest road segments, while DFS explores a branch deeply; neither generally minimizes weighted distance or estimated time. Dijkstra expands the lowest known accumulated cost first and finds a minimum-cost route for the selected objective. Choose the algorithm in Mission control, then click “Plan route” or “Compare BFS/DFS/Dijkstra/A*”.";
  }

  return "I can guide you through selecting locations, choosing BFS/DFS/Dijkstra/A*, planning routes, running simulations, blocking roads, simulating congestion, re-planning, and interpreting results. Try one of the suggested questions below. I use local rules and application state; I’m not a generative AI model.";
}

export const localRuleAssistant: AmbuAssistResponder = {
  respond(question, context) {
    if (!question.trim()) return "Type a question about using the route planner.";
    return `${answerQuestion(question, context)}\n${contextSummary(context)}\n\nTravel times shown here are estimates, not live traffic measurements.`;
  },
};
