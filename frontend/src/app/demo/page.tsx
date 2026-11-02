"use client";

import React, { useState, useEffect, useMemo, useRef } from 'react'
import { WarehouseView } from '@/components/WarehouseView'

// Simulated API responses (same format the planner sends)
const generateApiResponse = (scenario, robotPos, waypointIndex) => ({
  timestamp: new Date().toISOString(),
  run_id: 'run-demo-001',
  robot_state: { position: robotPos, velocity: scenario.status === 'STOP' ? 0 : scenario.status === 'SLOW' ? 0.3 : 1.0, battery: 87, status: 'operational' },
  governance_decision: { approved: scenario.status !== 'STOP', action: scenario.status, risk_score: scenario.risk, violations: scenario.status === 'STOP' ? ['human-presence'] : [], evaluation_time_ms: Math.floor(Math.random() * 20) + 15, policy_version: 'v2.1.0' },
  audit: { hash: Math.random().toString(16).slice(2, 18), previous_hash: Math.random().toString(16).slice(2, 18), chain_length: Math.floor(Math.random() * 1000) + 500 },
  waypoint: { current: waypointIndex, total: scenario.path?.length || 1 }
})

const scenarios = [
  { name: 'Safe Operation', status: 'SAFE', risk: 0.15, humans: [], obstacles: [], description: 'Robot moves freely to target', path: [{ x: 25, y: 50 }, { x: 75, y: 50 }] },
  { name: 'Human Approaching', status: 'SLOW', risk: 0.52, humans: [{ x: 55, y: 50 }], obstacles: [], description: 'Speed reduced, safe distance maintained', path: [{ x: 25, y: 50 }, { x: 40, y: 50 }], stopX: 40 },
  { name: 'Human Too Close', status: 'STOP', risk: 0.85, humans: [{ x: 35, y: 50 }], obstacles: [], description: 'Emergency halt - human in danger zone', path: [{ x: 25, y: 50 }] },
  { name: 'Path Blocked', status: 'REPLAN', risk: 0.45, humans: [], obstacles: [{ x: 50, y: 50 }], description: 'Following alternate route', path: [{ x: 25, y: 50 }, { x: 32, y: 32 }, { x: 50, y: 20 }, { x: 68, y: 32 }, { x: 75, y: 50 }] }
]

export default function SovereignAutonomyDashboard() {
  const [mapView, setMapView] = useState<'2d' | '3d'>('3d')
  const [showHeatmap, setShowHeatmap] = useState(true)
  const [showTrail, setShowTrail] = useState(true)
  const [hoveredWaypoint, setHoveredWaypoint] = useState<number | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [wsConnecting, setWsConnecting] = useState(true)
  const [messagesPerSec, setMessagesPerSec] = useState(0)
  const [latency, setLatency] = useState(0)

  const [activeScenario, setActiveScenario] = useState(0)
  const [robotPos, setRobotPos] = useState({ x: 25, y: 50 })
  const [waypointIndex, setWaypointIndex] = useState(0)
  const [events, setEvents] = useState([])
  const [arrived, setArrived] = useState(false)
  const [apiResponse, setApiResponse] = useState(null)
  const [showApiPanel, setShowApiPanel] = useState(true)

  const messageCountRef = useRef(0)
  const scenario = scenarios[activeScenario]

  const demoWorld = useMemo(() => ({
    geofence: { min_x: 0, max_x: 100, min_y: 0, max_y: 100 },
    zones: [
      { name: 'loading_bay', rect: { min_x: 0, max_x: 100, min_y: 55, max_y: 100 } },
      { name: 'aisle', rect: { min_x: 0, max_x: 100, min_y: 0, max_y: 55 } }
    ],
    obstacles: (scenario.obstacles || []).map((o) => ({ x: o.x, y: o.y, r: 3.0 })),
    human: scenario.humans?.[0] ? { x: scenario.humans[0].x, y: scenario.humans[0].y, type: 'primary' } : null,
    walking_humans: [],
    idle_robots: [{ x: 84, y: 74, label: 'R-02 (Idle)', status: 'idle' }],
    bays: [
      { id: 'B-01', x: 14, y: 95, type: 'dock' },
      { id: 'B-02', x: 30, y: 95, type: 'dock' },
      { id: 'B-03', x: 46, y: 95, type: 'dock' },
      { id: 'B-04', x: 62, y: 95, type: 'dock' },
      { id: 'B-05', x: 78, y: 95, type: 'dock' }
    ]
  }), [scenario])

  const demoTelemetry = useMemo(() => ({
    x: robotPos.x,
    y: robotPos.y,
    theta: 0,
    speed: scenario.status === 'STOP' ? 0 : scenario.status === 'SLOW' ? 0.3 : 1.0,
    zone: robotPos.y > 55 ? 'loading_bay' : 'aisle',
    nearest_obstacle_m: 2.0,
    human_detected: (scenario.humans?.length || 0) > 0,
    human_conf: 0.88,
    human_distance_m: scenario.humans?.[0] ? Math.hypot(robotPos.x - scenario.humans[0].x, robotPos.y - scenario.humans[0].y) : 999,
    events: [],
    target: scenario.path?.[waypointIndex] || null
  }), [robotPos, scenario, waypointIndex])

  const demoPathPoints = useMemo(() => (scenario.path || []).map((p) => ({ x: p.x, y: p.y })), [scenario])

  useEffect(() => {
    const connectTimer = setTimeout(() => {
      setWsConnecting(false)
      setWsConnected(true)
      addEvent({ ...scenario, description: 'WebSocket connected to governance API' })
    }, 800)
    return () => clearTimeout(connectTimer)
  }, [])

  useEffect(() => {
    const interval = setInterval(() => {
      setMessagesPerSec(messageCountRef.current)
      messageCountRef.current = 0
    }, 1000)
    return () => clearInterval(interval)
  }, [])

  const addEvent = (s) => {
    setEvents((prev) => [{ id: Date.now(), time: new Date().toLocaleTimeString(), type: s.status, message: s.description, risk: s.risk }, ...prev].slice(0, 10))
  }

  const handleScenarioChange = (i) => {
    setActiveScenario(i)
    setRobotPos({ x: 25, y: 50 })
    setWaypointIndex(0)
    setArrived(false)
    addEvent(scenarios[i])
  }

  useEffect(() => {
    if (!wsConnected) return
    const interval = setInterval(() => {
      if (arrived) return
      const startTime = performance.now()

      setRobotPos((prev) => {
        if (scenario.status === 'STOP') return prev
        const path = scenario.path
        if (!path || waypointIndex >= path.length) { setArrived(true); return prev }
        if (scenario.status === 'SLOW' && scenario.stopX && prev.x >= scenario.stopX - 0.5) return prev
        const target = path[waypointIndex]
        const dx = target.x - prev.x; const dy = target.y - prev.y; const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 1.5) { if (waypointIndex < path.length - 1) setWaypointIndex((w) => w + 1); else setArrived(true); return prev }
        const speed = scenario.status === 'SLOW' ? 0.15 : scenario.status === 'REPLAN' ? 0.35 : 0.5
        return { x: prev.x + (dx / dist) * speed, y: prev.y + (dy / dist) * speed }
      })

      const response = generateApiResponse(scenario, robotPos, waypointIndex)
      setApiResponse(response)
      messageCountRef.current++
      setLatency(Math.floor(performance.now() - startTime) + response.governance_decision.evaluation_time_ms)
    }, 40)
    return () => clearInterval(interval)
  }, [wsConnected, scenario, waypointIndex, arrived, robotPos])

  return (
    <div className="min-h-screen p-4 bg-mc-bg text-white">
      <div className="max-w-7xl mx-auto grid grid-cols-12 gap-4">
        <div className="col-span-8 bg-mc-panel rounded-md p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold">Demo — shared warehouse view</h2>
            <div className="space-x-2">
              {scenarios.map((s, i) => (
                <button key={s.name} onClick={() => handleScenarioChange(i)} className={`px-3 py-1 rounded ${i === activeScenario ? 'bg-emerald-500 text-black' : 'bg-mc-raise'}`}>
                  {s.name}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-3 flex flex-wrap gap-3 text-xs">
            {(['3d', '2d'] as const).map(view => <button key={view} aria-pressed={mapView === view} onClick={() => setMapView(view)} className={`rounded px-3 py-1 ${mapView === view ? 'bg-cyan-400 text-slate-950' : 'bg-mc-raise'}`}>{view === '3d' ? '3D warehouse' : 'Floor plan'}</button>)}
            <label><input type="checkbox" checked={showHeatmap} onChange={e => setShowHeatmap(e.target.checked)} /> Heatmap</label>
            <label><input type="checkbox" checked={showTrail} onChange={e => setShowTrail(e.target.checked)} /> Trail</label>
            {demoPathPoints.map((point, i) => <button key={i} onMouseEnter={() => setHoveredWaypoint(i)} onMouseLeave={() => setHoveredWaypoint(null)} onFocus={() => setHoveredWaypoint(i)} onBlur={() => setHoveredWaypoint(null)} className="rounded border border-purple-600 px-2">Waypoint {i + 1}</button>)}
          </div>
          <div style={{ height: 540 }} className="w-full">
            <WarehouseView view={mapView} trailKey={activeScenario} quality="low" world={demoWorld} telemetry={demoTelemetry} pathPoints={demoPathPoints}
              planWaypoints={demoPathPoints.map(p => ({ ...p, max_speed: scenario.status === 'SLOW' ? 0.3 : 1 }))}
              showHeatmap={showHeatmap} showTrail={showTrail} safetyState={scenario.status === 'SAFE' ? 'OK' : scenario.status}
              hoveredWaypointIdx={hoveredWaypoint} missionGoal={demoPathPoints[demoPathPoints.length - 1]} />
          </div>
        </div>

        <div className="col-span-4 space-y-4">
          <div className="bg-mc-panel rounded-md p-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="text-sm text-mc-ink/85">Status</div>
                <div className="text-2xl font-bold">{scenario.status === 'STOP' ? 'STOP' : scenario.status === 'SLOW' ? 'SLOW' : 'SAFE'}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-mc-mute">Risk</div>
                <div className="font-mono text-lg">{scenario.risk}</div>
              </div>
            </div>

            <div className="flex justify-between text-sm text-mc-ink/85">
              <div>Msgs/s: {messagesPerSec}</div>
              <div>Latency: {latency}ms</div>
            </div>
          </div>

          <div className="bg-mc-panel rounded-md p-4 overflow-auto" style={{ maxHeight: 300 }}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm text-mc-ink/85">API/Decision</div>
              <button className="text-xs text-mc-mute" onClick={() => setShowApiPanel((v) => !v)}>{showApiPanel ? 'Hide' : 'Show'}</button>
            </div>
            {showApiPanel && (
              <pre className="text-xs bg-mc-bg p-2 rounded text-mc-ink overflow-auto">{apiResponse ? JSON.stringify(apiResponse, null, 2) : 'No data yet'}</pre>
            )}
          </div>

          <div className="bg-mc-panel rounded-md p-4">
            <div className="text-sm text-mc-ink/85">Events</div>
            <ul className="mt-2 text-xs space-y-1">
              {events.map((e) => (
                <li key={e.id} className="text-mc-ink">[{e.time}] {e.type} — {e.message}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
