const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";
const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE || "";

/**
 * WebSocket URL for a run's live feed. The frontend's own host cannot proxy
 * WebSockets in `next dev`, so connect to the backend directly:
 * NEXT_PUBLIC_WS_BASE if set, else the absolute API base, else the backend on
 * :8080 when running locally, else same-origin (a reverse proxy in front).
 */
export function wsUrlForRun(runId: string) {
  const path = `/ws/runs/${runId}`;
  if (WS_BASE) return `${WS_BASE.replace(/\/$/, "")}${path}`;
  if (/^https?:\/\//.test(API_BASE)) return `${API_BASE.replace(/^http/, "ws").replace(/\/$/, "")}${path}`;
  if (typeof window !== "undefined") {
    const { protocol, hostname, port, host } = window.location;
    const proto = protocol === "https:" ? "wss:" : "ws:";
    if ((hostname === "localhost" || hostname === "127.0.0.1") && port === "3000") return `${proto}//${hostname}:8080${path}`;
    return `${proto}//${host}${path}`;
  }
  return path;
}
