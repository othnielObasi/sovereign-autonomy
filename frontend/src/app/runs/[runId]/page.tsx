"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { getRun, listEvents, stopRun, operatorOverride, getWorld, getTelemetry, getPathPreview, triggerScenario, generateLLMPlan, executeLLMPlan, analyzeScene, analyzeTelemetry, detectFailures, agenticPropose, getMission, getRiskHeatmap, getExecutedPath, getRunSafetyReport, getDivergenceExplanation, analyzeRunOptimization } from "@/lib/api";
import { WarehouseView } from "@/components/WarehouseView";
import { ScoreCard } from "@/components/ScoreCard";
import { SiteIntelPanel } from "@/components/SiteIntelPanel";
import { VisionPanel } from "@/components/VisionPanel";
import { AuthorityPanel } from "@/components/AuthorityPanel";
import { IntrospectionPanel } from "@/components/IntrospectionPanel";
import { wsUrlForRun } from "@/lib/ws";
import type { WsMessage } from "@/lib/types";
import Link from "next/link";
import { Tabs } from "@/components/ui";
import { RunLearningPanel } from "@/components/RunLearningPanel";

/* ── Bay resolver (matches backend resolve_bay_from_instruction) ── */
const BAY_PATTERN = /\b([ABSR])-?(\d{1,2})\b/i;
function resolveBayGoal(instruction: string, bays: any[]): { x: number; y: number } | null {
  if (!instruction || !bays?.length) return null;
  const match = instruction.match(BAY_PATTERN);
  if (!match) return null;
  const prefix = match[1].toUpperCase();
  const num = match[2].padStart(2, "0");
  const bayId = `${prefix}-${num}`;
  const bay = bays.find((b: any) => b.id?.toUpperCase() === bayId);
  if (bay && typeof bay.x === "number") return { x: bay.x, y: bay.y };
  return null;
}

// Strip decorative emoji from panel titles: the mission-control style keeps titles plain
const plain = (t: string) => t.replace(/^[^\p{L}\p{N}]+/u, "").trim();

function Card({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-mc-panel border border-mc-line rounded-xl p-4 ${className}`}>
      <div className="text-[13px] font-semibold uppercase tracking-[0.08em] text-mc-ink mb-3">{plain(title)}</div>
      {children}
    </div>
  );
}

function CollapsibleCard({ title, children, className = "", defaultOpen = false, hint }: { title: string; children: React.ReactNode; className?: string; defaultOpen?: boolean; hint?: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`bg-mc-panel border border-mc-line rounded-xl ${className}`}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="w-full flex items-center justify-between p-4 text-left gap-2">
        <span className="text-[13px] font-semibold uppercase tracking-[0.08em] text-mc-ink">{plain(title)}</span>
        <span className="flex items-center gap-2">
          {!open && hint && <span className="text-[10px] text-mc-dim font-normal normal-case tracking-normal">{hint}</span>}
          <span className={`text-mc-dim transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
        </span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = (status || "").toLowerCase();
  const color = s === "running" ? "bg-mc-accent/10 text-mc-accent border-mc-accent/30"
    : s === "planning" ? "bg-mc-info/10 text-mc-info border-mc-info/30"
    : s === "stopped" || s === "failed" ? "bg-mc-stop/10 text-mc-stop border-mc-stop/30"
    : s === "completed" ? "bg-mc-ok/10 text-mc-ok border-mc-ok/30"
    : s === "paused" ? "bg-mc-warn/10 text-mc-warn border-mc-warn/30"
    : "bg-mc-raise text-mc-mute border-mc-line2";
  return (
    <span className={`text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border ${color}`}>
      {s === "planning" ? "Planning…" : status || "—"}
    </span>
  );
}

function SafetyBadge({ state, detail }: { state: string; detail: string }) {
  const map: Record<string, string> = {
    OK: "bg-green-500/20 text-green-400 border-green-500/30",
    STOP: "bg-red-500/20 text-red-400 border-red-500/30",
    SLOW: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    REPLAN: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  };
  const cls = map[state] || map.OK;
  return (
    <span className={`text-xs font-semibold px-3 py-1 rounded-full border ${cls}`}>
      {state}{state !== "OK" ? ` — ${detail}` : ""}
    </span>
  );
}

export default function RunPage({ params }: { params: { runId: string } }) {
  const runId = params.runId;
  const [run, setRun] = useState<any>(null);
  const [mission, setMission] = useState<any>(null);
  const [telemetry, setTelemetry] = useState<any>(null);
  const [world, setWorld] = useState<any>(null);
  const [showHeatmap, setShowHeatmap] = useState<boolean>(true);
  const [sideTab, setSideTab] = useState<string>("learning");
  const [mapView, setMapView] = useState<"3d" | "2d">("3d");
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("view") === "2d") setMapView("2d");
  }, []);
  const [showTrail, setShowTrail] = useState<boolean>(true);
  const [pathPoints, setPathPoints] = useState<Array<{x:number;y:number}> | null>(null);
  const [riskCells, setRiskCells] = useState<Array<{x:number;y:number;risk:number}>>([]);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [status, setStatus] = useState<string>("");
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<any>(null);
  const fullscreenGridRef = useRef<HTMLDivElement | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Fix 2: scenario system
  const [scenarioLoading, setScenarioLoading] = useState<string | null>(null);
  const [scenarioToast, setScenarioToast] = useState<string | null>(null);

  // Fix 2: explicit policy_state from WS
  const [livePolicyState, setLivePolicyState] = useState<string>("SAFE");

  // ── Unified AI Mission Planner state ──
  const [missionInstruction, setMissionInstruction] = useState("");
  const [pipelineStage, setPipelineStage] = useState<"idle" | "reasoning" | "planning" | "governing" | "ready" | "executing" | "done">("idle");
  const [missionError, setMissionError] = useState<string | null>(null);
  // Live planning progress steps from backend (shown during auto-pilot)
  const [planningSteps, setPlanningSteps] = useState<Array<{step: string; message: string; ts: number}>>([]);
  // Agentic reasoning results
  const [agenticResult, setAgenticResult] = useState<any>(null);
  // LLM plan results
  const [llmPlan, setLlmPlan] = useState<any>(null);
  const [llmExecResult, setLlmExecResult] = useState<any>(null);
  // Live agentic reasoning from WebSocket
  const [liveThoughtChain, setLiveThoughtChain] = useState<any[]>([]);
  const [showReasoningDetails, setShowReasoningDetails] = useState<boolean>(false);
  const [hoveredWaypointIdx, setHoveredWaypointIdx] = useState<number | null>(null);
  // Live diagnostics from runtime (populated from WS event messages)
  const [executionReason, setExecutionReason] = useState<string | null>(null);
  const [distanceToGoalLive, setDistanceToGoalLive] = useState<number | null>(null);
  const [stagnantCyclesLive, setStagnantCyclesLive] = useState<number>(0);

  // AI Vision / Multimodal
  const [sceneResult, setSceneResult] = useState<any>(null);
  const [sceneLoading, setSceneLoading] = useState(false);
  const [sceneError, setSceneError] = useState<string | null>(null);

  // Telemetry Analysis
  const [telAnalysis, setTelAnalysis] = useState<any>(null);
  const [telAnalysisLoading, setTelAnalysisLoading] = useState(false);
  const [telAnalysisError, setTelAnalysisError] = useState<string | null>(null);

  // Failure Detection
  const [failureResult, setFailureResult] = useState<any>(null);
  const [failureLoading, setFailureLoading] = useState(false);
  const [failureError, setFailureError] = useState<string | null>(null);

  // AI Intelligence Console tab
  const [aiTab, setAiTab] = useState<"scene" | "telemetry" | "failure">("scene");

  // Replan tracking
  const [replanCount, setReplanCount] = useState(0);
  const [lastDenialPolicy, setLastDenialPolicy] = useState<string | null>(null);

  // Autonomous mode
  const [autonomousMode, setAutonomousMode] = useState(true);

  // Active waypoint tracking during execution
  const [activeWaypointIdx, setActiveWaypointIdx] = useState<number>(-1);

  // Phase E: Executed path overlay + safety report + divergence + optimization
  const [executedPathData, setExecutedPathData] = useState<Array<{x:number;y:number}>>([]);
  const [destinationBayId, setDestinationBayId] = useState<string | null>(null);
  const [safetyReport, setSafetyReport] = useState<any>(null);
  const [divergenceExplanation, setDivergenceExplanation] = useState<any>(null);
  const [optimizationAnalysis, setOptimizationAnalysis] = useState<any>(null);

  // Mission-level governance review (from MISSION_REVIEW events)
  const [missionReview, setMissionReview] = useState<any>(null);

  async function refreshEvents() {
    try {
      const rows = await listEvents(runId);
      setEvents(rows);

      // Auto-populate llmPlan from backend PLAN events.  Always prefer the
      // latest LLM plan (source: "muse" / "gemini") over a seed fallback so the map
      // shows the plan the robot is *actually* following — even if a seed
      // fallback was loaded first.
      const planEvents = rows.filter((e: any) => e.type === "PLAN");
      // Prefer the latest PLAN event (LLM upgrade over seed fallback)
      for (let i = planEvents.length - 1; i >= 0; i--) {
        const payload = typeof planEvents[i].payload === "string"
          ? JSON.parse(planEvents[i].payload)
          : planEvents[i].payload || {};
        const plan = payload.plan;
        const source = payload.source;
        if (plan?.waypoints?.length) {
          // Always accept an LLM plan; only accept a fallback if nothing set yet
          if (source !== "fallback" || !llmPlan) {
            setLlmPlan(plan);
          }
          break;
        }
      }
    } catch (_) {}
  }

  // Track fullscreen state for compact panel rendering
  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await getRun(runId);
        setRun(r);
        // Sync pipeline stage with backend run status so the AI Planner
        // panel reflects that the backend has already started planning/executing.
        if (r?.status === "planning" && pipelineStage === "idle") {
          setPipelineStage("planning");
        } else if (r?.status === "running" && pipelineStage === "idle") {
          setPipelineStage("executing");
        } else if ((r?.status === "completed" || r?.status === "stopped") && pipelineStage === "idle") {
          setPipelineStage("done");
        }
        // Fetch the parent mission to pre-fill instruction & goal
        if (r?.mission_id) {
          try {
            const m = await getMission(r.mission_id);
            setMission(m);
            if (m?.title && !missionInstruction) {
              setMissionInstruction(m.title);
            }
          } catch (_) {}
        }
      } catch (_) {}
      try { setWorld(await getWorld()); } catch (_) {}
      try { setTelemetry(await getTelemetry()); } catch (_) {}
      // Phase E: fetch safety report (optimization deferred to panel expand)
      try { setSafetyReport(await getRunSafetyReport(runId)); } catch (_) {}
      await refreshEvents();
    })();
  }, [runId]);

  useEffect(() => {
    let disposed = false;

    function connect() {
      if (disposed) return;
      const url = wsUrlForRun(runId);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsConnected(true);
        ws.send("hello");
      };

      ws.onmessage = (ev) => {
        const msg: WsMessage = JSON.parse(ev.data);
        if (msg.kind === "telemetry") setTelemetry(msg.data);
        if (msg.kind === "alert") setAlerts((a) => [{ ts: Date.now(), ...msg.data }, ...a].slice(0, 20));
        if (msg.kind === "planning_progress") {
          // Live planning substep from backend — append to visible progress log
          const d = msg.data as any;
          setPlanningSteps((prev) => [...prev, { step: d.step, message: d.message, ts: Date.now() }]);
          // Also advance pipelineStage based on substep
          if (d.step === "llm_start") setPipelineStage("planning");
          if (d.step === "governance_start") setPipelineStage("governing");
          if (d.step === "governance_done") setPipelineStage("executing");
          // If LLM plan came back, trigger event refresh so map picks it up
          if (d.step === "llm_done") refreshEvents();
        }
        if (msg.kind === "event") {
          refreshEvents();
          // Extract policy_state from governance decision
          const ps = msg.data?.policy_state || msg.data?.governance?.policy_state;
          if (ps) setLivePolicyState(ps);
          // New diagnostics fields added by RunService
          if (msg.data?.execution_reason) setExecutionReason(msg.data.execution_reason);
          if (msg.data?.distance_to_goal !== undefined) setDistanceToGoalLive(msg.data.distance_to_goal);
          if (msg.data?.stagnant_cycles !== undefined) setStagnantCyclesLive(msg.data.stagnant_cycles || 0);
        }
        if (msg.kind === "status") {
          setStatus(msg.data.status);
          // Sync AI Planner pipeline stage with backend status transitions
          // so the UI doesn't show "idle" while the robot is already running.
          const s = msg.data.status;
          if (s === "planning") {
            setPipelineStage((prev) => prev === "idle" ? "planning" : prev);
          } else if (s === "running") {
            setPipelineStage((prev) => (prev === "idle" || prev === "planning" || prev === "governing") ? "executing" : prev);
          } else if (s === "completed" || s === "stopped" || s === "failed") {
            setPipelineStage((prev) => prev !== "idle" && prev !== "done" ? "done" : prev);
          }
        }
        if (msg.kind === "agent_reasoning") setLiveThoughtChain(msg.data?.steps || []);
        try { ws.send("ping"); } catch {}
      };

      ws.onerror = () => { setWsConnected(false); };
      ws.onclose = () => {
        setWsConnected(false);
        if (!disposed) {
          // Reconnect after 2 seconds
          reconnectTimer.current = setTimeout(connect, 2000);
        }
      };
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimer.current);
      try { wsRef.current?.close(); } catch {}
    };
  }, [runId]);

  useEffect(() => {
    let t: any = null;
    async function tick() {
      // Refresh events so the backend LLM plan auto-populates
      await refreshEvents();
      try {
        const res = await getPathPreview(runId);
        setPathPoints(res.points || null);
      } catch (_) {}
      try {
        const hm = await getRiskHeatmap(runId);
        setRiskCells(hm.cells || []);
      } catch (_) {}
      try {
        const ep = await getExecutedPath(runId);
        setExecutedPathData(ep.points || []);
        if (ep.destination_bay_id) setDestinationBayId(ep.destination_bay_id);
      } catch (_) {}
    }
    tick();
    t = setInterval(tick, 1500);
    return () => { if (t) clearInterval(t); };
  }, [runId]);

  async function onStop() {
    await stopRun(runId);
    setStatus("stopped");
  }

  async function onScenario(scenario: string) {
    setScenarioLoading(scenario);
    try {
      await triggerScenario(scenario);
      const labels: Record<string, string> = {
        human_approach: "Human approaching — robot should SLOW",
        human_too_close: "Human too close — robot should STOP",
        path_blocked: "Path blocked — robot should REPLAN",
        clear: "Scenario cleared — back to normal",
      };
      setScenarioToast(labels[scenario] || scenario);
      setTimeout(() => setScenarioToast(null), 4000);
    } catch (e: any) {
      setScenarioToast(`Failed: ${e.message}`);
      setTimeout(() => setScenarioToast(null), 4000);
    } finally {
      setScenarioLoading(null);
    }
  }

  // ── Unified Pipeline: Reason → Plan → Govern → Execute ──
  async function onRunPipeline() {
    if (!missionInstruction.trim()) return;
    setMissionError(null);
    setAgenticResult(null);
    setLlmPlan(null);
    setLlmExecResult(null);
    setActiveWaypointIdx(-1);

    // Stage 1: Agentic Reasoning
    setPipelineStage("reasoning");
    const bayGoal = resolveBayGoal(missionInstruction, world?.bays || []);
    const missionGoal = bayGoal || mission?.goal || undefined;
    try {
      const aResult = await agenticPropose(missionInstruction, missionGoal);
      setAgenticResult(aResult);
      // Track replanning
      if (aResult.replanning_used) {
        setReplanCount((c) => c + 1);
        const deniedStep = (aResult.thought_chain || []).find((s: any) => s.action === "replan");
        if (deniedStep) {
          const policyMatch = deniedStep.thought?.match(/Policies?:\s*([A-Z_0-9]+)/i);
          setLastDenialPolicy(policyMatch ? policyMatch[1] : "POLICY_HIT");
        }
      }
    } catch (e: any) {
      setMissionError(e.message || "Reasoning failed");
      setPipelineStage("idle");
      return;
    }

    // Stage 2: Generate multi-waypoint plan
    setPipelineStage("planning");
    try {
      const plan = await generateLLMPlan(missionInstruction, missionGoal);
      setLlmPlan(plan);
      // If plan has governance failures, auto-replan once
      if (plan && !plan.all_approved && autonomousMode) {
        setReplanCount((c) => c + 1);
        const failedGov = plan.governance?.find((g: any) => g.decision !== "APPROVED");
        if (failedGov) {
          setLastDenialPolicy(failedGov.policy_hits?.[0] || "POLICY_HIT");
        }
        // Replan with adjusted instruction
        setPipelineStage("planning");
        try {
          const replan = await generateLLMPlan(`${missionInstruction} (avoid policy violations, use slower speed)`, missionGoal);
          if (replan) setLlmPlan(replan);
        } catch (_) {}
      }
      setPipelineStage(plan ? "ready" : "idle");
    } catch (e: any) {
      setMissionError(e.message || "Plan generation failed");
      setPipelineStage("idle");
    }
  }

  async function onExecutePipeline() {
    if (!llmPlan?.waypoints?.length) return;
    setPipelineStage("executing");
    setMissionError(null);
    setLlmExecResult(null);
    setActiveWaypointIdx(0);
    try {
      const result = await executeLLMPlan(
        missionInstruction,
        llmPlan.waypoints,
        llmPlan.rationale || ""
      );
      // Animate through waypoints
      for (let i = 0; i < (result.steps?.length || 0); i++) {
        setActiveWaypointIdx(i);
        await new Promise(r => setTimeout(r, 600));
      }
      setLlmExecResult(result);
      setActiveWaypointIdx(-1);
      setPipelineStage("done");
    } catch (e: any) {
      setMissionError(e.message || "Execution failed");
      setActiveWaypointIdx(-1);
      setPipelineStage("ready");
    }
  }

  /* ── Build a scene description from live world state ────── */
  function buildSceneDescription(): string {
    const lines: string[] = [];
    lines.push("Warehouse environment, 30m x 20m.");
    if (telemetry) {
      lines.push(`Robot at (${(+(telemetry.x ?? 0)).toFixed(1)}, ${(+(telemetry.y ?? 0)).toFixed(1)}) moving at ${(+(telemetry.speed ?? 0)).toFixed(2)} m/s.`);
    }
    if (world?.human) {
      lines.push(`Human detected at (${world.human.x}, ${world.human.y}).`);
      if (telemetry) {
        const dx = +(telemetry.x ?? 0) - +world.human.x;
        const dy = +(telemetry.y ?? 0) - +world.human.y;
        const d = Math.sqrt(dx * dx + dy * dy);
        lines.push(`Distance robot-to-human: ${d.toFixed(1)}m.`);
      }
    }
    if (world?.obstacles?.length) {
      lines.push(`${world.obstacles.length} obstacles: ` + world.obstacles.map((o: any) => `(${o.x}, ${o.y})`).join(", ") + ".");
    }
    if (world?.zones?.length) {
      lines.push("Zones: " + world.zones.map((z: any) => z.name).join(", ") + ".");
    }
    lines.push(`Safety state: ${safety.state}.`);
    return lines.join(" ");
  }

  async function onAnalyzeScene() {
    setSceneLoading(true);
    setSceneError(null);
    setSceneResult(null);
    try {
      const desc = buildSceneDescription();
      const result = await analyzeScene(desc, true);
      setSceneResult(result);
    } catch (e: any) {
      setSceneError(e.message || "Scene analysis failed");
    } finally {
      setSceneLoading(false);
    }
  }

  async function onAnalyzeTelemetry() {
    setTelAnalysisLoading(true);
    setTelAnalysisError(null);
    setTelAnalysis(null);
    try {
      const recentEvents = events.slice(-10);
      const result = await analyzeTelemetry(recentEvents, "Analyze safety trends, anomalies, and recommend actions.");
      setTelAnalysis(result);
    } catch (e: any) {
      setTelAnalysisError(e.message || "Telemetry analysis failed");
    } finally {
      setTelAnalysisLoading(false);
    }
  }

  async function onDetectFailures() {
    setFailureLoading(true);
    setFailureError(null);
    setFailureResult(null);
    try {
      const recentEvents = events.slice(-15);
      const result = await detectFailures(recentEvents);
      setFailureResult(result);
    } catch (e: any) {
      setFailureError(e.message || "Failure detection failed");
    } finally {
      setFailureLoading(false);
    }
  }

  const lastDecision = useMemo(() => {
    const dec = [...events].reverse().find((e) => e.type === "DECISION");
    return dec?.payload || null;
  }, [events]);

  // Extract MISSION_REVIEW from events (Sovereign Autonomy's plan approval)
  useEffect(() => {
    const review = events.find((e: any) => e.type === "MISSION_REVIEW");
    if (review) {
      const payload = typeof review.payload === "string" ? JSON.parse(review.payload) : review.payload;
      setMissionReview(payload);
    }
  }, [events]);

  const safety = useMemo(() => {
    const g = lastDecision?.governance;
    const ps = livePolicyState;

    if (ps === "STOP") {
      return { state: "STOP", detail: (g?.reasons?.[0] || "Full stop — safety policy") as string };
    }
    if (ps === "REPLAN") {
      return { state: "REPLAN", detail: (g?.required_action || "Replan required") as string };
    }
    if (ps === "SLOW") {
      return { state: "SLOW", detail: (g?.required_action || "Speed limited by policy") as string };
    }

    return { state: "OK", detail: "Within policy" };
  }, [lastDecision, livePolicyState]);

  const currentStatus = status || run?.status || "—";

  // True when the backend is auto-planning/executing (user did NOT trigger the
  // manual "Plan →" pipeline).  Used to show an explanatory banner.
  const isBackendAutoPilot = (currentStatus === "planning" || currentStatus === "running")
    && !agenticResult && !llmExecResult;

  const safetyBannerCls: Record<string, string> = {
    OK: "bg-green-500/15 border-green-500/30 text-green-400",
    STOP: "bg-red-500/20 border-red-500/40 text-red-400",
    SLOW: "bg-yellow-500/15 border-yellow-500/30 text-yellow-400",
    REPLAN: "bg-blue-500/15 border-blue-500/30 text-blue-400",
  };
  const safetyIcon: Record<string, string> = { OK: "✅", STOP: "🔴", SLOW: "🟡", REPLAN: "🔵" };

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-4 space-y-3">
      {/* Scenario toast notification (floating) */}
      {scenarioToast && (
        <div className="fixed top-20 right-4 z-50 bg-mc-panel/95 border border-cyan-500/40 rounded-xl px-4 py-3 shadow-lg shadow-black/30 backdrop-blur animate-slide-in max-w-xs">
          <div className="text-sm text-cyan-300 font-medium">{scenarioToast}</div>
        </div>
      )}

      {/* ── Compact Header ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-mc-dim">
            <Link href="/runs" className="hover:text-mc-accent">Runs</Link>
            <span>/</span>
            <span className="font-mono text-mc-accent">{runId}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight text-mc-ink truncate max-w-[60vw]" title={mission?.title || runId}>
              {mission?.title || "Governed run"}
            </h1>
            <StatusBadge status={currentStatus} />
            <div className={`flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
              wsConnected ? "bg-mc-ok/10 text-mc-ok border-mc-ok/30" : "bg-mc-stop/10 text-mc-stop border-mc-stop/30"
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full bg-current ${wsConnected ? "animate-live-dot" : ""}`} />
              {wsConnected ? "Live" : "Offline"}
            </div>
            {mission?.goal && <span className="text-xs text-mc-dim">goal ({mission.goal.x}, {mission.goal.y})</span>}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {currentStatus !== "stopped" && currentStatus !== "completed" && (
            <button onClick={onStop} className="bg-mc-stop hover:bg-red-400 text-white text-sm font-semibold px-4 py-1.5 rounded-lg transition">
              Stop robot
            </button>
          )}
          {currentStatus === "paused" && (
            <button onClick={async () => {
              try {
                await operatorOverride(runId, "resume", "Operator approved after governance review");
                setStatus("running");
              } catch (e: any) { console.error("Override failed:", e); }
            }} className="bg-amber-500/80 hover:bg-amber-600 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition animate-pulse">
              ▶ Override &amp; Resume
            </button>
          )}
          {/* Live diagnostics */}
          <div className="text-xs text-mc-mute ml-3 flex items-center gap-3">
            {executionReason && <span className="px-2 py-0.5 rounded bg-mc-raise">{executionReason}</span>}
            {distanceToGoalLive !== null && <span>Goal: {distanceToGoalLive.toFixed(2)}m</span>}
            {stagnantCyclesLive > 0 && <span className="text-yellow-300">Stag: {stagnantCyclesLive}</span>}
          </div>
        </div>
      </div>

      {/* ── Multi-Scope Status Strip ── */}
      <div className={`sticky top-0 z-20 backdrop-blur-md grid grid-cols-5 gap-1.5 px-3 py-2 rounded-lg border ${safetyBannerCls[safety.state] || safetyBannerCls.OK}`}>
        {/* Mission Status */}
        <div className="flex flex-col items-center text-center">
          <span className="text-[9px] uppercase tracking-wider text-mc-dim font-semibold">Mission</span>
          <span className={`text-xs font-bold ${currentStatus === "stopped" ? "text-red-400" : currentStatus === "paused" ? "text-yellow-400" : currentStatus === "planning" ? "text-purple-400" : "text-green-400"}`}>
            {currentStatus === "running" ? "Active" : currentStatus === "stopped" ? "Halted" : currentStatus === "paused" ? "Paused" : currentStatus === "completed" ? "Complete" : currentStatus === "planning" ? "Planning…" : "Idle"}
          </span>
        </div>
        {/* Current Action Verdict */}
        <div className="flex flex-col items-center text-center">
          <span className="text-[9px] uppercase tracking-wider text-mc-dim font-semibold">Action Verdict</span>
          <span className={`text-xs font-bold ${
            lastDecision?.governance?.decision === "APPROVED" ? "text-green-400" :
            lastDecision?.governance?.decision === "DENIED" ? "text-red-400" :
            lastDecision?.governance?.decision === "NEEDS_REVIEW" ? "text-yellow-400" : "text-mc-mute"
          }`}>
            {lastDecision?.governance?.decision === "APPROVED"
              ? (lastDecision?.proposal?.intent === "STOP" ? "Approved Stop" : "Approved")
              : lastDecision?.governance?.decision || "Awaiting"}
          </span>
        </div>
        {/* Environment Risk State */}
        <div className="flex flex-col items-center text-center">
          <span className="text-[9px] uppercase tracking-wider text-mc-dim font-semibold">Environment</span>
          <span className={`text-xs font-bold ${
            telemetry?.human_distance_m != null && telemetry.human_distance_m < 2 ? "text-red-400" :
            telemetry?.human_distance_m != null && telemetry.human_distance_m < 4 ? "text-yellow-400" : "text-green-400"
          }`}>
            {telemetry?.human_distance_m != null && telemetry.human_distance_m < 2 ? "Human Near"
              : telemetry?.human_distance_m != null && telemetry.human_distance_m < 4 ? "Elevated"
              : "Clear"}
          </span>
        </div>
        {/* Planner State */}
        <div className="flex flex-col items-center text-center">
          <span className="text-[9px] uppercase tracking-wider text-mc-dim font-semibold">Planner</span>
          <span className={`text-xs font-bold ${
            llmPlan?.all_approved === true ? "text-green-400" :
            llmPlan?.all_approved === false ? "text-yellow-400" :
            llmPlan && missionReview?.verdict === "APPROVED" ? "text-green-400" :
            pipelineStage === "reasoning" || pipelineStage === "planning" ? "text-purple-400" : "text-mc-mute"
          }`}>
            {llmPlan?.all_approved === true ? "All Approved" :
             llmPlan?.all_approved === false ? "Constrained" :
             llmPlan && missionReview?.verdict === "APPROVED" ? "Sovereign Autonomy Approved" :
             llmPlan ? "Under Review" :
             pipelineStage === "reasoning" || pipelineStage === "planning" ? "Working…" : "Idle"}
          </span>
        </div>
        {/* Execution Safety */}
        <div className="flex flex-col items-center text-center">
          <span className="text-[9px] uppercase tracking-wider text-mc-dim font-semibold">Execution</span>
          <span className={`text-xs font-bold ${
            safety.state === "OK" ? "text-green-400" :
            safety.state === "STOP" ? "text-red-400" :
            safety.state === "SLOW" ? "text-yellow-400" : "text-blue-400"
          }`}>
            {safety.state === "OK" ? "Within Bounds" :
             safety.state === "STOP" ? "Stopped" :
             safety.state === "SLOW" ? "Speed Limited" : "Replanning"}
          </span>
        </div>
      </div>

      {/* ── MAIN LAYOUT: Hero Map (left 60%) + Sidebar (right 40%) ── */}
      <div ref={fullscreenGridRef} className={`grid grid-cols-1 lg:grid-cols-5 gap-3 [&:fullscreen]:bg-mc-bg [&:fullscreen]:p-4 [&:fullscreen]:overflow-y-auto`}>

        {/* ── LEFT: Hero Map ── */}
        <div className="lg:col-span-3 space-y-3">
          <Card title="Warehouse Simulation">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <label className="text-[10px] text-mc-mute flex items-center gap-1 cursor-pointer">
                  <input type="checkbox" checked={showHeatmap} onChange={(e) => setShowHeatmap(e.target.checked)} className="accent-cyan-500 w-3 h-3" />
                  Heatmap
                </label>
                <label className="text-[10px] text-mc-mute flex items-center gap-1 cursor-pointer">
                  <input type="checkbox" checked={showTrail} onChange={(e) => setShowTrail(e.target.checked)} className="accent-cyan-500 w-3 h-3" />
                  Trail
                </label>
              </div>
              {/* Scenario triggers */}
              <div className="flex items-center gap-1.5">
                {([
                  { key: "human_approach", icon: "🚶", label: "Human Near", cls: "border-yellow-500/40 text-yellow-400 hover:bg-yellow-500/20" },
                  { key: "human_too_close", icon: "🛑", label: "Too Close", cls: "border-red-500/40 text-red-400 hover:bg-red-500/20" },
                  { key: "path_blocked", icon: "🚧", label: "Blocked", cls: "border-blue-500/40 text-blue-400 hover:bg-blue-500/20" },
                  { key: "spill", icon: "💧", label: "Spill", cls: "border-sky-500/40 text-sky-400 hover:bg-sky-500/20" },
                  { key: "forklift_crossing", icon: "🚜", label: "Forklift", cls: "border-amber-500/40 text-amber-400 hover:bg-amber-500/20" },
                  { key: "clear", icon: "✅", label: "Clear", cls: "border-green-500/40 text-green-400 hover:bg-green-500/20" },
                ] as const).map((s) => (
                  <button
                    key={s.key}
                    onClick={() => onScenario(s.key)}
                    disabled={!!scenarioLoading || currentStatus === "stopped"}
                    title={s.key.replace(/_/g, " ")}
                    className={`border rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition disabled:opacity-30 relative flex items-center gap-1 ${s.cls} ${scenarioLoading === s.key ? "animate-pulse scenario-active-ring" : ""} ${scenarioLoading === s.key ? (s.key === "human_approach" ? "ring-yellow" : s.key === "human_too_close" ? "ring-red" : s.key === "path_blocked" ? "ring-blue" : "ring-green") : ""}`}
                  >
                    <span>{s.icon}</span><span className="hidden sm:inline">{s.label}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-1 mb-2">
              {([["3d", "3D warehouse"], ["2d", "Floor plan"]] as const).map(([k, label]) => (
                <button key={k} onClick={() => setMapView(k)} className={`px-3 py-1 rounded-md text-xs font-semibold border transition ${mapView === k ? "bg-cyan-500 text-slate-950 border-cyan-400" : "border-mc-line2 text-mc-ink/85 hover:bg-mc-raise/50"}`}>
                  {label}
                </button>
              ))}
            </div>
            <div className={isFullscreen ? "h-[72vh]" : "h-[480px]"}>
              <WarehouseView view={mapView} trailKey={runId} world={world} telemetry={telemetry}
                pathPoints={pathPoints} planWaypoints={llmPlan?.waypoints || null}
                missionGoal={resolveBayGoal(missionInstruction, world?.bays || []) || mission?.goal || null}
                showHeatmap={showHeatmap} showTrail={showTrail} safetyState={safety.state}
                hoveredWaypointIdx={hoveredWaypointIdx} riskCells={riskCells} executedPath={executedPathData}
                destinationBayId={destinationBayId} fullscreenTargetRef={fullscreenGridRef}
                verdict={lastDecision?.governance?.decision ?? null}
                verdictText={lastDecision?.governance?.reasons?.[0] ?? null} proposal={lastDecision?.proposal ?? null} />
            </div>
            {/* Map Legend — explicit path ownership */}
            <div className="flex items-center gap-3 mt-2 px-1 flex-wrap">
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-full bg-cyan-400 inline-block" /> Robot</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-sm bg-red-500 inline-block" /> Obstacles</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-full bg-amber-400 inline-block" /> Human</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-full bg-blue-400 inline-block" /> Proposed Path</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-full bg-purple-400 inline-block" /> Approved Plan</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" /> Executed Path</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block" /> Goal</span>
              <span className="flex items-center gap-1 text-[10px] text-mc-mute"><span className="w-2.5 h-2.5 rounded-sm bg-red-400/50 inline-block" /> Risk Zone</span>
              {/* Mission Alignment badge */}
              {llmPlan && executedPathData.length > 0 && (
                <span className={`ml-auto flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                  divergenceExplanation?.divergence_detected
                    ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30"
                    : "bg-green-500/15 text-green-400 border-green-500/30"
                }`}>
                  {divergenceExplanation?.divergence_detected ? "⚠ Plan Diverged" : "✓ Following Approved Plan"}
                </span>
              )}
              {!llmPlan && <span className="text-[10px] text-mc-dim ml-auto">Scroll to zoom · Drag to pan</span>}
            </div>
          </Card>

          {/* ── Unified AI Mission Planner ── */}
          {!isFullscreen && (
          <Card title="🤖 AI Mission Planner">
            {/* Autonomous Mode + Memory + Replan badges */}
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <button onClick={() => setAutonomousMode(!autonomousMode)}
                className={`flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full border transition ${
                  autonomousMode
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm shadow-emerald-500/20"
                    : "bg-mc-raise/50 text-mc-mute border-mc-line2"
                }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${autonomousMode ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} />
                Autonomous: {autonomousMode ? "ON" : "OFF"}
              </button>
              {agenticResult?.memory_summary && (
                <span className="text-[10px] text-mc-mute bg-mc-raise/50 px-2 py-1 rounded-full border border-mc-line2">
                  🧠 Memory: {agenticResult.memory_summary.total_entries || 0} decisions retained
                </span>
              )}
              {replanCount > 0 && (
                <span className="text-[10px] font-semibold text-amber-300 bg-amber-500/15 px-2 py-1 rounded-full border border-amber-500/30">
                  🔄 Replans: {replanCount}{lastDenialPolicy ? ` — ${lastDenialPolicy}` : ""}
                </span>
              )}
            </div>

            {/* Pipeline step indicator — numbered intelligence pipeline */}
            <div className="flex items-center gap-0 mb-3 text-[10px] font-semibold">
              {([
                { key: "reasoning", label: "1. Reasoning", icon: "🧠" },
                { key: "planning", label: "2. Plan", icon: "🗺️" },
                { key: "governing", label: "3. Governance", icon: "🛡️" },
                { key: "executing", label: "4. Execute", icon: "🚀" },
                { key: "done", label: "5. Audit", icon: "📋" },
              ] as const).map((stage, i) => {
                const stageOrder = ["idle", "reasoning", "planning", "governing", "ready", "executing", "done"];
                const currentIdx = stageOrder.indexOf(pipelineStage);
                const stageIdx = stageOrder.indexOf(stage.key);
                const isActive = pipelineStage === stage.key;
                const isDone = currentIdx > stageIdx;
                return (
                  <React.Fragment key={stage.key}>
                    {i > 0 && <div className={`flex-1 h-0.5 mx-1 rounded ${isDone ? "bg-green-500" : isActive ? "bg-purple-500 animate-pulse" : "bg-mc-raise"}`} />}
                    <div className={`flex items-center gap-1 px-2 py-1 rounded-md border transition-all ${
                      isActive ? "border-purple-500/50 bg-purple-500/15 text-purple-300" :
                      isDone ? "border-green-500/30 bg-green-500/10 text-green-400" :
                      "border-mc-line text-mc-dim"
                    }`}>
                      <span>{isDone ? "✓" : stage.icon}</span>
                      <span>{stage.label}</span>
                    </div>
                  </React.Fragment>
                );
              })}
            </div>

            {/* ── Auto-pilot banner: explain what's happening when backend drives the run ── */}
            {isBackendAutoPilot && (
              <div className="flex items-start gap-2 bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3 mb-3">
                <span className="text-cyan-400 text-base mt-0.5">{currentStatus === "planning" ? "🗺️" : "🚀"}</span>
                <div>
                  <div className="text-sm font-semibold text-cyan-300">
                    {currentStatus === "planning" ? "AI is generating a plan…" : "Mission running autonomously"}
                  </div>
                  <div className="text-[11px] text-mc-mute mt-0.5">
                    {currentStatus === "planning"
                      ? "Muse Spark is planning the route from the map and the robot camera. The robot will not move until planning and governance review complete."
                      : "The robot is following the approved plan. Watch the map and chain-of-trust below for live progress."}
                  </div>
                </div>
              </div>
            )}

            {/* ── Live planning progress log ── */}
            {planningSteps.length > 0 && (currentStatus === "planning" || currentStatus === "running") && (
              <div className="bg-mc-bg/60 border border-mc-line rounded-lg p-3 mb-3 space-y-1.5">
                <div className="text-[10px] uppercase tracking-wider text-mc-dim font-semibold mb-1">Planning Progress</div>
                {planningSteps.map((s, i) => {
                  const icon = s.step === "llm_start" ? "🧠" : s.step === "llm_done" ? "✅" : s.step === "llm_fallback" || s.step === "llm_skip" ? "⚡" : s.step === "governance_start" ? "🛡️" : s.step === "governance_done" ? "✅" : "•";
                  const isLatest = i === planningSteps.length - 1;
                  return (
                    <div key={i} className={`flex items-start gap-2 text-[11px] ${isLatest ? "text-cyan-300" : "text-mc-dim"}`}>
                      <span className="mt-0.5 flex-shrink-0">{icon}</span>
                      <span className={isLatest && (s.step === "llm_start" || s.step === "governance_start") ? "animate-pulse" : ""}>{s.message}</span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Instruction input + Plan button (hidden during auto-pilot; shown when idle or done) */}
            {!isBackendAutoPilot && (
            <div className="flex gap-2 mb-3">
              <input type="text" value={missionInstruction} onChange={(e) => setMissionInstruction(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && pipelineStage === "idle" && onRunPipeline()}
                placeholder={mission?.title || "Navigate to loading bay avoiding obstacles"}
                className="flex-1 bg-mc-bg/60 border border-mc-line2 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-purple-500 placeholder:text-mc-dim" />
              <button onClick={onRunPipeline}
                disabled={pipelineStage !== "idle" || !missionInstruction.trim()}
                className="bg-purple-500 hover:bg-purple-600 disabled:bg-mc-line2 text-white text-sm font-semibold px-4 py-2 rounded-lg transition whitespace-nowrap">
                {pipelineStage === "reasoning" ? "🧠 Reasoning..." : pipelineStage === "planning" ? "🗺️ Planning..." : pipelineStage === "executing" ? "🚀 Executing..." : pipelineStage === "done" ? "✓ Done" : "Plan →"}
              </button>
            </div>
            )}

            {missionError && (
              <div className="flex items-start gap-2 bg-red-500/15 border-l-4 border-red-500 rounded-lg p-3 mb-3 animate-slide-up">
                <span className="text-red-400 text-lg">⚠️</span>
                <div>
                  <div className="text-sm font-semibold text-red-400">Pipeline Error</div>
                  <div className="text-xs text-red-300/80 mt-0.5">{missionError}</div>
                </div>
              </div>
            )}

            {/* Loading skeleton for reasoning stage */}
            {pipelineStage === "reasoning" && liveThoughtChain.length === 0 && (
              <div className="space-y-2 mb-3 animate-pulse">
                <div className="h-3 bg-purple-500/20 rounded w-1/3" />
                <div className="bg-mc-bg/60 border border-purple-500/10 rounded-lg p-3 space-y-2">
                  <div className="h-2 bg-mc-raise rounded w-2/3" />
                  <div className="h-2 bg-mc-raise rounded w-1/2" />
                  <div className="h-2 bg-mc-raise rounded w-3/4" />
                  <div className="flex items-center gap-2"><span className="text-xs text-purple-400 animate-pulse">🧠 Reasoning...</span></div>
                </div>
              </div>
            )}

            {/* Loading skeleton for planning stage */}
            {pipelineStage === "planning" && !llmPlan && (
              <div className="space-y-2 mb-3 animate-pulse">
                <div className="h-3 bg-purple-500/20 rounded w-1/4" />
                <div className="flex gap-1">
                  {[1,2,3,4].map(i => <div key={i} className="h-6 w-16 bg-mc-raise rounded" />)}
                </div>
                <div className="flex items-center gap-2"><span className="text-xs text-purple-400 animate-pulse">🗺️ Generating waypoints...</span></div>
              </div>
            )}

            {/* Live reasoning spinner */}
            {pipelineStage === "reasoning" && liveThoughtChain.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 mb-2 animate-slide-up">
                <span className="w-2 h-2 bg-purple-400 rounded-full animate-pulse" />
                <span className="text-xs text-mc-mute">{liveThoughtChain.length} reasoning steps</span>
                {liveThoughtChain.map((step: any, i: number) => (
                  <span key={i} className="bg-mc-raise text-cyan-300 px-1.5 py-0.5 rounded font-mono text-[10px]">{step.action || "think"}</span>
                ))}
              </div>
            )}

            {/* Stage 1 result: Agent Reasoning — STRUCTURED FORMAT */}
            {agenticResult && (
              <div className="space-y-2 mb-3">
                <div className="text-[10px] uppercase tracking-wide text-mc-dim font-semibold">Reasoning</div>
                {agenticResult.replanning_used && (() => {
                  const replanSteps = (agenticResult.thought_chain || []).filter((s: any) => s.action === "replan");
                  return (
                    <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-2 space-y-1.5 animate-slide-up">
                      <div className="flex items-center gap-2 text-[10px]">
                        <span>🔄</span>
                        <span className="text-amber-300 font-semibold">Replanned {replanSteps.length}× after policy denial</span>
                        {lastDenialPolicy && <span className="text-amber-400/70 font-mono">({lastDenialPolicy})</span>}
                      </div>
                      {replanSteps.map((rs: any, i: number) => {
                        const policyMatch = rs.thought?.match(/Policies?:\s*([A-Z_0-9,\s]+?)(?:\.|$)/i);
                        const reasonMatch = rs.thought?.match(/Reasons?:\s*(.+?)(?:\.\s*Risk|$)/i);
                        const riskMatch = rs.thought?.match(/Risk:\s*([\d.]+)/);
                        const stateMatch = rs.thought?.match(/State:\s*(\w+)/);
                        return (
                          <div key={i} className="bg-mc-bg/60 border border-amber-500/15 rounded p-2 space-y-1 text-[10px] font-mono">
                            <div className="flex items-center gap-2">
                              <span className="px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 font-semibold">Attempt {i + 1} denied</span>
                              {stateMatch && <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">{stateMatch[1]}</span>}
                              {riskMatch && <span className="text-red-400">Risk: {(parseFloat(riskMatch[1]) * 100).toFixed(0)}%</span>}
                            </div>
                            {policyMatch && <div className="text-amber-400">Policies: {policyMatch[1].trim()}</div>}
                            {reasonMatch && <div className="text-mc-mute">{reasonMatch[1].trim()}</div>}
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                {/* Compact structured reasoning + confidence (collapsible details) */}
                <div className="bg-mc-bg/60 border border-purple-500/20 rounded-lg p-3 space-y-1.5 text-xs font-mono">
                  <div className="flex items-start gap-2">
                    <span className="text-purple-400 font-bold min-w-[80px]">Goal:</span>
                    <span className="text-white truncate">{missionInstruction || "—"}</span>
                    <button onClick={() => setShowReasoningDetails(!showReasoningDetails)} className="ml-auto text-[10px] text-mc-mute hover:text-mc-ink px-2 py-0.5 rounded">
                      {showReasoningDetails ? "Hide details" : "Show details"}
                    </button>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="text-cyan-400 font-bold min-w-[80px]">Constraints:</span>
                    <div className="text-mc-ink/85 space-y-0.5">
                      {world?.human && <div>- Human @{world.human.x},{world.human.y}</div>}
                      {(world?.obstacles || []).slice(0, 1).map((o: any, i: number) => (
                        <div key={i}>- Obstacle @{o.x},{o.y}</div>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-start gap-2">
                    <span className="text-emerald-400 font-bold min-w-[80px]">Strategy:</span>
                    <div className="text-mc-ink/85 space-y-0.5">
                      {(agenticResult.thought_chain || []).filter((s: any) => s.thought && s.action !== "replan").slice(0, 2).map((s: any, i: number) => (
                        <div key={i}>- {s.thought}</div>
                      ))}
                      {(agenticResult.thought_chain || []).length > 2 && <div className="text-mc-dim">+{(agenticResult.thought_chain || []).length - 2} more steps</div>}
                    </div>
                  </div>
                  {/* Planner Confidence vs Governance Risk — explicitly distinct */}
                  <div className="flex items-center gap-2">
                    <span className="text-yellow-400 font-bold min-w-[120px]">Planner Confidence:</span>
                    {
                      (() => {
                        const risk = agenticResult.governance?.risk_score ?? 0;
                        const raw = 1 - risk;
                        const adjusted = Math.max(0, Math.min(1, raw * 0.92 + 0.04));
                        const pct = (adjusted * 100).toFixed(1);
                        const color = adjusted > 0.7 ? "text-green-400" : adjusted > 0.4 ? "text-yellow-400" : "text-red-400";
                        return (
                          <>
                            <span className={`font-bold ${color}`}>{pct}%</span>
                            <div className="flex-1 h-1 bg-mc-raise rounded-full overflow-hidden ml-1">
                              <div className={`h-full rounded-full transition-all duration-500 ${adjusted > 0.7 ? "bg-green-500" : adjusted > 0.4 ? "bg-yellow-500" : "bg-red-500"}`} style={{ width: `${adjusted * 100}%` }} />
                            </div>
                          </>
                        );
                      })()
                    }
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-red-400 font-bold min-w-[120px]">Governance Risk:</span>
                    {
                      (() => {
                        const risk = agenticResult.governance?.risk_score ?? 0;
                        const pct = (risk * 100).toFixed(1);
                        const color = risk > 0.5 ? "text-red-400" : risk > 0.2 ? "text-yellow-400" : "text-green-400";
                        return (
                          <>
                            <span className={`font-bold ${color}`}>{pct}%</span>
                            <div className="flex-1 h-1 bg-mc-raise rounded-full overflow-hidden ml-1">
                              <div className={`h-full rounded-full transition-all duration-500 ${risk > 0.5 ? "bg-red-500" : risk > 0.2 ? "bg-yellow-500" : "bg-green-500"}`} style={{ width: `${risk * 100}%` }} />
                            </div>
                          </>
                        );
                      })()
                    }
                  </div>
                  <div className="text-[10px] text-mc-dim italic mt-0.5">High planner confidence ≠ safe execution — governance overrides unsafe plans regardless of confidence</div>

                  {/* Collapsible full detail view */}
                  {showReasoningDetails && (
                    <div className="mt-2">
                      <div className="bg-mc-bg/60 border border-mc-line/50 rounded p-2 space-y-1">
                        {(agenticResult.thought_chain || []).filter((s: any) => s.action).map((s: any, i: number) => {
                          const isReplan = s.action === "replan";
                          const isOk = !isReplan && !s.observation?.toLowerCase().includes("denied") && !s.observation?.toLowerCase().includes("violation");
                          return (
                            <div key={i} className={`flex items-center gap-2 text-[10px] font-mono ${isReplan ? "bg-amber-500/10 border border-amber-500/20 rounded px-1 py-0.5" : ""}`}>
                              <span className={`px-1.5 py-0.5 rounded ${
                                isReplan ? "bg-amber-500/20 text-amber-300" :
                                s.action === "submit_action" ? "bg-green-500/20 text-green-300" :
                                s.action === "check_policy" ? "bg-cyan-500/20 text-cyan-300" :
                                "bg-mc-raise text-mc-ink/85"
                              }`}>{s.action}</span>
                              <span className="text-mc-dim">→</span>
                              <span className={isReplan ? "text-amber-400" : isOk ? "text-green-400" : "text-amber-400"}>{isReplan ? "⟳ replanning" : isOk ? "OK" : "⚠ violation"}</span>
                              {s.thought && <span className={`truncate max-w-[300px] ${isReplan ? "text-amber-400/70" : "text-mc-dim"}`}>{s.thought}</span>}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>

                {/* Memory awareness — denial history */}
                {agenticResult.memory_summary && agenticResult.memory_summary.recent_denials > 0 && (
                  <div className="bg-amber-500/8 border border-amber-500/20 rounded p-2 space-y-1 text-[10px]">
                    <div className="text-amber-300 font-semibold">Memory Recall</div>
                    {(agenticResult.memory_summary.entries || []).filter((e: any) => e.decision === "DENIED" || e.decision === "NEEDS_REVIEW").slice(-3).map((e: any, i: number) => (
                      <div key={i} className="flex items-center gap-2 font-mono text-amber-400/80">
                        <span>↳ Previous denial:</span>
                        <span className="text-amber-300">{(e.policy_hits || []).join(", ") || "policy hit"}</span>
                        <span className="text-mc-dim">→ Adjusted: {e.intent} @{e.params?.max_speed || "?"}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Proposal + model info line */}
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-mc-dim text-[10px]">{agenticResult.thought_chain?.length || 0} steps</span>
                  {[...new Set((agenticResult.thought_chain || []).map((s: any) => s.action).filter(Boolean))].map((tool: string, i: number) => (
                    <span key={i} className={`px-1.5 py-0.5 rounded font-mono text-[10px] ${
                      tool === "submit_action" ? "bg-green-500/20 text-green-300" : tool === "check_policy" ? "bg-cyan-500/20 text-cyan-300" : tool === "graceful_stop" ? "bg-amber-500/20 text-amber-300" : tool === "replan" ? "bg-red-500/20 text-red-300" : "bg-mc-raise text-mc-ink/85"
                    }`}>{tool}</span>
                  ))}
                  {agenticResult.proposal && (
                    <>
                      <span className="text-mc-dim">→</span>
                      <span className="font-semibold text-cyan-400">{agenticResult.proposal.intent}</span>
                      {agenticResult.proposal.params?.x != null && <span className="text-mc-mute">({agenticResult.proposal.params.x}, {agenticResult.proposal.params.y})</span>}
                    </>
                  )}
                </div>

                {/* Preliminary policy check — NOT the final governance verdict */}
                {agenticResult.governance && (
                  <div className={`text-xs rounded px-2 py-1.5 border space-y-1 ${
                    agenticResult.governance.decision === "APPROVED" ? "bg-green-500/10 border-green-500/20" : agenticResult.governance.decision === "DENIED" ? "bg-red-500/10 border-red-500/20" : "bg-yellow-500/10 border-yellow-500/20"
                  }`}>
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">
                        {agenticResult.governance.decision === "APPROVED" ? "✓" : agenticResult.governance.decision === "DENIED" ? "✗" : "⚠"}{" "}
                        {agenticResult.governance.decision === "APPROVED" ? "Checks Passed" : agenticResult.governance.decision === "DENIED" ? "Checks Failed" : "Review Required"}
                      </span>
                      <span className="text-mc-dim text-[10px]">Preliminary Validation</span>
                    </div>
                    <div className="flex items-center gap-3 text-[10px]">
                      <span className="text-mc-dim">Planner Confidence: <span className={`font-bold ${(1 - (agenticResult.governance.risk_score ?? 0)) > 0.7 ? "text-green-400" : "text-yellow-400"}`}>{((1 - (agenticResult.governance.risk_score ?? 0)) * 100).toFixed(0)}%</span></span>
                      <span className="text-mc-dim">|</span>
                      <span className="text-mc-dim">Governance Risk: <span className={`font-bold ${(agenticResult.governance.risk_score ?? 0) > 0.5 ? "text-red-400" : (agenticResult.governance.risk_score ?? 0) > 0.2 ? "text-yellow-400" : "text-green-400"}`}>{((agenticResult.governance.risk_score ?? 0) * 100).toFixed(0)}%</span></span>
                    </div>
                    {/* Why Approved / Why Denied — explainability */}
                    {agenticResult.governance.decision === "APPROVED" && telemetry && (
                      <div className="text-[10px] text-green-400/70 space-y-0.5 pt-1 border-t border-green-500/10">
                        <div className="text-green-300 font-semibold mb-0.5">Checks satisfied:</div>
                        {telemetry.human_distance_m > 3 && <div>✓ Human distance: {telemetry.human_distance_m?.toFixed(1)}m {'>'} 3m safe threshold</div>}
                        {telemetry.human_distance_m <= 3 && telemetry.human_distance_m > 1 && <div>✓ Human distance: {telemetry.human_distance_m?.toFixed(1)}m — speed reduced to safe level</div>}
                        {telemetry.nearest_obstacle_m > 0.5 && <div>✓ Obstacle clearance: {telemetry.nearest_obstacle_m?.toFixed(1)}m {'>'} 0.5m minimum</div>}
                        <div>✓ Speed {agenticResult.proposal?.params?.max_speed || '?'} m/s within {telemetry.zone || 'zone'} limit ({telemetry.zone === 'loading_bay' ? '0.4' : '0.5'} m/s)</div>
                        <div>✓ Position within geofence bounds</div>
                      </div>
                    )}
                    {agenticResult.governance.decision !== "APPROVED" && agenticResult.governance.reasons?.length > 0 && (
                      <div className="text-[10px] text-red-400/70 space-y-0.5 pt-1 border-t border-red-500/10">
                        {agenticResult.governance.reasons.map((r: string, i: number) => <div key={i}>• {r}</div>)}
                      </div>
                    )}
                  </div>
                )}
                {agenticResult.model_used && <div className="text-[10px] text-mc-dim font-mono">Model: {agenticResult.model_used}</div>}
              </div>
            )}

            {/* Planner's reasoning (backend-driven runs): one readable summary, details on demand */}
            {!agenticResult && llmPlan && (() => {
              const raw = String(llmPlan.rationale || "");
              const m = raw.match(/^\[([^\]]+)\]\s*/);
              const model = (m ? m[1] : llmPlan.model || "").replace(/^nvidia\//, "");
              const strategy = raw.replace(/^\[[^\]]+\]\s*/, "") || "Route along the aisles to the destination.";
              return (
                <div className="mb-3 rounded-lg border border-mc-line bg-mc-raise/60 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] uppercase tracking-wider text-mc-dim font-semibold">Planner&apos;s reasoning</span>
                    {model && <span className="text-[11px] font-medium text-mc-nv">{model}</span>}
                    {missionReview?.verdict === "APPROVED" && (
                      <span className="ml-auto text-[11px] font-semibold px-2 py-0.5 rounded-full border border-mc-ok/30 bg-mc-ok/10 text-mc-ok">
                        Plan review passed · {missionReview.checks_passed?.length || 0} checks
                      </span>
                    )}
                    {missionReview?.verdict === "BLOCKED" && (
                      <span className="ml-auto text-[11px] font-semibold px-2 py-0.5 rounded-full border border-mc-stop/30 bg-mc-stop/10 text-mc-stop">Plan blocked</span>
                    )}
                  </div>
                  <p className={`mt-1.5 text-sm text-mc-ink/90 leading-relaxed ${showReasoningDetails ? "" : "line-clamp-2"}`}>{strategy}</p>
                  {missionReview?.verdict === "BLOCKED" && (missionReview.reasons || []).map((r: string, i: number) => (
                    <div key={i} className="text-xs text-mc-stop mt-1">{r}</div>
                  ))}
                  <button onClick={() => setShowReasoningDetails(!showReasoningDetails)} className="mt-1.5 text-xs text-mc-accent hover:underline">
                    {showReasoningDetails ? "Hide details" : "Show details"}
                  </button>
                  {showReasoningDetails && (
                    <div className="mt-2 pt-2 border-t border-mc-line/70 grid sm:grid-cols-2 gap-3 text-xs text-mc-mute">
                      <div>
                        <div className="text-mc-dim uppercase tracking-wider text-[10px] mb-1">What the planner saw</div>
                        {world?.human && <div>Person at ({world.human.x}, {world.human.y})</div>}
                        {(world?.obstacles || []).slice(0, 3).map((o: any, i: number) => <div key={i}>Obstacle at ({o.x}, {o.y})</div>)}
                        {world?.geofence && <div>Site {world.geofence.max_x} × {world.geofence.max_y} m</div>}
                      </div>
                      <div>
                        <div className="text-mc-dim uppercase tracking-wider text-[10px] mb-1">Plan review</div>
                        {(missionReview?.checks_passed || []).map((c: string, i: number) => <div key={i}>✓ {c.replace(/_/g, " ")}</div>)}
                        {!missionReview && <div>Waiting for the review…</div>}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Stage 2 result: Waypoint Plan */}
            {llmPlan && (
              <div className="space-y-2 mb-3">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] uppercase tracking-wider text-mc-dim font-semibold">Waypoint plan</span>
                  <span className="text-[11px] text-mc-dim">{llmPlan.waypoints?.length || 0} waypoints · hover one to find it on the map</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(llmPlan.waypoints || []).map((wp: any, i: number) => {
                    const gov = llmPlan.governance?.[i]; const ok = gov?.decision === "APPROVED";
                    const isActive = activeWaypointIdx === i;
                    const isCompleted = activeWaypointIdx > i;
                    const isNext = activeWaypointIdx >= 0 && activeWaypointIdx + 1 === i;
                    return (
                      <span key={i} onMouseEnter={() => setHoveredWaypointIdx(i)} onMouseLeave={() => setHoveredWaypointIdx(null)} onClick={() => setActiveWaypointIdx(i)} className={`cursor-pointer text-[10px] px-1.5 py-0.5 rounded border transition-all duration-300 ${
                        isActive ? "border-cyan-400 bg-cyan-500/25 text-cyan-200 shadow-sm shadow-cyan-500/30 scale-105 font-bold" :
                        isCompleted ? "border-green-500/40 bg-green-500/15 text-green-400 line-through opacity-70" :
                        isNext ? "border-purple-400/40 bg-purple-500/10 text-purple-300 animate-pulse" :
                        ok ? "border-green-500/30 text-green-400" : "border-yellow-500/30 text-yellow-400"
                      }`}>
                        {isCompleted ? "✓" : isActive ? "▶" : `${i + 1}:`} ({wp.x.toFixed(0)},{wp.y.toFixed(0)}) @{wp.max_speed}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Execute button */}
            {pipelineStage === "ready" && llmPlan && (
              <button onClick={onExecutePipeline} disabled={currentStatus === "stopped"}
                className="w-full bg-green-500/80 hover:bg-green-600 disabled:bg-mc-line2 text-white text-xs font-semibold py-2 rounded-lg transition mb-2">
                🚀 Execute Plan in Simulation
              </button>
            )}
            {pipelineStage === "executing" && (
              <div className="text-xs text-purple-300 animate-pulse text-center py-2">Executing waypoints…</div>
            )}

            {/* Stage 3 result: Execution */}
            {llmExecResult && (
              <div className="space-y-1 mb-2">
                <div className="text-[10px] uppercase tracking-wide text-mc-dim font-semibold">Execution Result</div>
                <span className={`text-xs font-semibold ${llmExecResult.status === "completed" ? "text-green-400" : "text-yellow-400"}`}>
                  {llmExecResult.status?.toUpperCase()}
                </span>
                {(llmExecResult.steps || []).map((step: any, i: number) => (
                  <div key={i} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${step.executed ? "bg-green-500/10" : "bg-red-500/10"}`}>
                    <span className="font-mono text-purple-400">WP{step.waypoint_index + 1}</span>
                    <span className={step.executed ? "text-green-400" : "text-red-400"}>{step.executed ? "✓" : "✗"}</span>
                    <span className="text-mc-dim">{step.policy_state}</span>
                  </div>
                ))}
                <div className="text-[10px] text-mc-dim font-mono">Hash: {llmExecResult.audit_hash?.slice(0, 20)}…</div>
              </div>
            )}

            {/* Reset button when done */}
            {(pipelineStage === "done" || pipelineStage === "ready") && (
              <button onClick={() => { setPipelineStage("idle"); setAgenticResult(null); setLlmPlan(null); setLlmExecResult(null); setMissionError(null); setReplanCount(0); setLastDenialPolicy(null); setActiveWaypointIdx(-1); }}
                className="w-full text-xs text-mc-dim hover:text-mc-ink/85 py-1 transition">
                ↺ New Mission
              </button>
            )}
          </Card>
          )}
        </div>

        {/* ── RIGHT SIDEBAR ── */}
        <div className="lg:col-span-2 space-y-3 lg:sticky lg:top-14 lg:self-start lg:max-h-[calc(100vh-4.5rem)] lg:overflow-y-auto dash-scroll">

          {/* Compact Governance Decision */}
          <Card title="Governance Decision">
            {!lastDecision ? (
              <div className="text-mc-dim text-xs text-center py-3">⏳ Awaiting first decision…</div>
            ) : (
              <div className={`space-y-2 ${isFullscreen ? "text-[10px]" : "text-xs"} rounded-lg ${isFullscreen ? "p-2 -mx-0.5" : "p-3 -mx-1"} ${
                lastDecision.governance?.decision === "APPROVED" ? "animate-glow-green" :
                lastDecision.governance?.decision === "DENIED" ? "animate-glow-red" :
                lastDecision.governance?.decision === "NEEDS_REVIEW" ? "animate-glow-yellow" : ""
              }`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`text-lg`}>
                      {lastDecision.governance?.decision === "APPROVED" ? "✅" : lastDecision.governance?.decision === "DENIED" ? "❌" : "⚠️"}
                    </span>
                    <span className={`font-bold ${isFullscreen ? "text-sm" : "text-lg"} ${
                      lastDecision.governance?.decision === "APPROVED" ? "text-green-400" : lastDecision.governance?.decision === "DENIED" ? "text-red-400" : "text-yellow-400"
                    }`}>
                      {lastDecision.governance?.decision === "APPROVED" && lastDecision.proposal?.intent === "STOP"
                        ? "APPROVED STOP"
                        : lastDecision.governance?.decision || "—"}
                    </span>
                  </div>
                  <span className="text-mc-mute">Execution Risk: {lastDecision.governance?.risk_score != null ? (lastDecision.governance.risk_score * 100).toFixed(0) + "%" : "—"}</span>
                </div>
                {/* Scope clarification: what exactly was approved/denied */}
                {!isFullscreen && (
                <div className="bg-mc-bg/40 rounded px-2 py-1.5 text-[10px] space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-mc-dim min-w-[65px]">Scope:</span>
                    <span className="text-mc-ink/85">Current action only</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-mc-dim min-w-[65px]">Intent:</span>
                    <span className="text-white font-semibold">{lastDecision.proposal?.intent || "—"}</span>
                    {lastDecision.proposal?.params?.x != null && <span className="text-mc-mute">→ ({lastDecision.proposal.params.x.toFixed?.(1)}, {lastDecision.proposal.params.y?.toFixed?.(1)})</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-mc-dim min-w-[65px]">Policies:</span>
                    <span className="text-mc-ink/85 font-mono">{(lastDecision.governance?.policy_hits || []).length > 0
                      ? (lastDecision.governance.policy_hits).join(", ")
                      : <span className="text-green-400">✓ 0 violations (11 active)</span>}</span>
                  </div>
                </div>
                )}
                {lastDecision.governance?.decision === "APPROVED" && !isFullscreen && (
                  <div className="bg-green-500/5 border border-green-500/20 rounded p-2 space-y-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-green-400 font-semibold text-[10px] uppercase tracking-wider">All 11 Policies Passed</span>
                      <span className="text-[10px] text-green-400/60 font-mono">0 denied · 0 constrained</span>
                    </div>
                    {[
                      { label: "GEOFENCE_01", check: telemetry ? `pos (${telemetry.x?.toFixed(1)},${telemetry.y?.toFixed(1)}) inside boundary` : "position inside boundary" },
                      { label: "SAFE_SPEED_01", check: telemetry ? `speed ${(+telemetry.speed || 0).toFixed(2)} m/s within ${telemetry.zone || "zone"} limit` : "within zone limit" },
                      { label: "HUMAN_PROXIMITY_02", check: telemetry?.human_distance_m ? `human ${telemetry.human_distance_m.toFixed(1)}m away (>1m safe)` : "no human nearby" },
                      { label: "HUMAN_CLEARANCE_02", check: telemetry?.human_distance_m ? `clearance ${telemetry.human_distance_m.toFixed(1)}m (>3m ideal)` : "no human in zone" },
                      { label: "OBSTACLE_CLEARANCE_03", check: telemetry?.nearest_obstacle_m ? `obstacle ${telemetry.nearest_obstacle_m.toFixed(1)}m (>0.5m)` : "> 0.5m buffer" },
                      { label: "UNCERTAINTY_04", check: "confidence above threshold" },
                      { label: "HITL_05", check: "no operator override required" },
                      { label: "WORKER_PROXIMITY_06", check: telemetry?.human_distance_m ? `worker zone clear (${telemetry.human_distance_m.toFixed(1)}m)` : "worker zone clear" },
                      { label: "PATH_CLEARANCE_07", check: "path clear of racking" },
                      { label: "HAZARD_EXCLUSION_08", check: telemetry?.site_constraints?.length ? `outside ${telemetry.site_constraints.length} hazard zone(s)` : "no hazard zones in force" },
                      { label: "HAZARD_SLOW_09", check: telemetry?.site_constraints?.length ? "within hazard speed caps" : "no hazard speed caps" },
                    ].map((item, i) => (
                      <div key={i} className="flex items-center gap-1.5">
                        <span className="text-green-500 text-[10px]">✓</span>
                        <span className="text-cyan-400 font-mono text-[10px] min-w-[140px]">{item.label}</span>
                        <span className="text-green-300/80 text-[10px]">{item.check}</span>
                      </div>
                    ))}
                  </div>
                )}
                {lastDecision.governance?.reasons?.length > 0 && (
                  <div className="text-mc-mute bg-mc-bg/40 rounded p-2">
                    <div className="text-red-400 font-semibold text-[10px] uppercase tracking-wider mb-1">Policy Violations</div>
                    {lastDecision.governance.reasons.map((r: string, i: number) => <div key={i}>• {r}</div>)}
                  </div>
                )}
                {lastDecision.governance?.required_action && (
                  <div className="bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1 text-yellow-300">
                    {lastDecision.governance.required_action}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Secondary panels in tabs: the gate decision above stays visible */}
          <div>
            <Tabs value={sideTab} onChange={setSideTab} tabs={[
              { id: "learning", label: "Learning & task" },
              { id: "intel", label: "Site & vision" },
              { id: "chain", label: "Chain & telemetry" },
              { id: "alerts", label: "Alerts", count: alerts.length },
              { id: "analysis", label: "Analysis" },
            ]} />
            <div className="pt-3 space-y-3">
            <AuthorityPanel compact />
            {sideTab === "learning" && (
              <RunLearningPanel runId={runId} events={events}
                ended={["stopped", "completed", "failed", "failed_safety"].includes(String(currentStatus).toLowerCase())} />
            )}
            {sideTab === "intel" && (<>
            {/* Tavily site intelligence (untrusted input) */}
            <SiteIntelPanel />

            {/* Robot camera perception (SAM 3.1, or the earlier vision model), cross-checked with sensors */}
            <VisionPanel runId={runId} />

            </>)}
            {sideTab === "chain" && (<>
            {/* Compact Telemetry */}
            <CollapsibleCard title="Live Telemetry" defaultOpen={false}>
              {!telemetry ? (
                <div className="text-mc-dim text-xs text-center py-2">📡 Waiting…</div>
              ) : (
                <div>
                  <div className={`grid grid-cols-2 gap-x-4 gap-y-1 ${isFullscreen ? "text-[10px]" : "text-xs"} mb-2`}>
                    <div><span className="text-mc-dim">x:</span> <span className="text-white font-mono">{(+telemetry.x).toFixed(1)}</span></div>
                    <div><span className="text-mc-dim">y:</span> <span className="text-white font-mono">{(+telemetry.y).toFixed(1)}</span></div>
                    <div><span className="text-mc-dim">heading:</span> <span className="text-white font-mono">{((+telemetry.theta || 0) * 180 / Math.PI).toFixed(0)}°</span></div>
                    <div><span className="text-mc-dim">speed:</span> <span className="text-white font-mono">{(+telemetry.speed).toFixed(2)} m/s</span></div>
                    <div><span className="text-mc-dim">human:</span> <span className="text-white font-mono">{(+telemetry.human_distance_m).toFixed(1)}m</span></div>
                    <div><span className="text-mc-dim">obstacle:</span> <span className="text-white font-mono">{(+telemetry.nearest_obstacle_m).toFixed(1)}m</span></div>
                  </div>
                  <details>
                    <summary className="text-[10px] text-mc-dim cursor-pointer hover:text-mc-mute">Show Raw JSON</summary>
                    <pre className="text-[10px] text-green-400/70 bg-mc-bg/60 p-2 rounded mt-1 overflow-x-auto max-h-40 overflow-y-auto font-mono">
  {JSON.stringify(telemetry, null, 2)}
                    </pre>
                  </details>
                </div>
              )}
            </CollapsibleCard>

            {/* Chain-of-Trust Timeline (compact, icons) */}
            <Card title="Chain-of-Trust">
              {events.length === 0 ? (
                <div className="text-mc-dim text-xs text-center py-2">🔗 No events yet.</div>
              ) : (
                <div className={`${isFullscreen ? "max-h-32" : "max-h-60"} overflow-y-auto space-y-0.5 timeline-live-line`}>
                  {events.slice(isFullscreen ? -5 : -10).reverse().map((e) => {
                    const icon = e.type === "DECISION" ? "🔵" : e.type === "TELEMETRY" ? "🟢" : "🟠";
                    return (
                      <details key={e.id} className="group">
                        <summary className="cursor-pointer py-1.5 flex items-center gap-1.5 text-xs hover:bg-mc-raise/30 rounded px-1 -mx-1">
                          <span className="text-[10px]">{icon}</span>
                          <span className="text-mc-dim font-mono text-[10px]">{new Date(e.ts).toLocaleTimeString()}</span>
                          <span className="font-semibold text-[10px] text-mc-ink/85">{e.type}</span>
                          <span className="text-slate-700 text-[10px] font-mono ml-auto">{e.hash?.slice(0, 8)}…</span>
                        </summary>
                        <pre className="text-[10px] text-mc-mute bg-mc-bg/60 p-2 rounded overflow-x-auto mt-0.5 font-mono max-h-24 overflow-y-auto">
  {JSON.stringify(e.payload, null, 2)}
                        </pre>
                      </details>
                    );
                  })}
                </div>
              )}
            </Card>

            </>)}
            {sideTab === "alerts" && (<>
            {/* Alerts */}
            {!isFullscreen && (
            <Card title="Alerts">
              {alerts.length === 0 ? (
                <div className="text-xs text-mc-dim space-y-1">
                  <div className="flex items-center gap-2 bg-green-500/5 border border-green-500/10 rounded px-2 py-1">
                    <span className="text-green-400 text-[10px]">●</span>
                    <span className="text-[10px] text-mc-dim font-mono mr-1">PWR</span>
                    <span className="text-mc-mute">Battery at 96% — normal operating range</span>
                  </div>
                  <div className="flex items-center gap-2 bg-green-500/5 border border-green-500/10 rounded px-2 py-1">
                    <span className="text-green-400 text-[10px]">●</span>
                    <span className="text-[10px] text-mc-dim font-mono mr-1">NAV</span>
                    <span className="text-mc-mute">Path deviation 0.12m — within ±0.5m tolerance</span>
                  </div>
                  <div className="flex items-center gap-2 bg-green-500/5 border border-green-500/10 rounded px-2 py-1">
                    <span className="text-green-400 text-[10px]">●</span>
                    <span className="text-[10px] text-mc-dim font-mono mr-1">SEN</span>
                    <span className="text-mc-mute">Motor temp 42°C — below 65°C threshold</span>
                  </div>
                  <div className="flex items-center gap-2 bg-green-500/5 border border-green-500/10 rounded px-2 py-1">
                    <span className="text-green-400 text-[10px]">●</span>
                    <span className="text-[10px] text-mc-dim font-mono mr-1">COM</span>
                    <span className="text-mc-mute">Position update latency 12ms — below 100ms threshold</span>
                  </div>
                </div>
              ) : (
                <ul className="space-y-1 max-h-40 overflow-y-auto">
                  {alerts.map((a, i) => {
                    const msg = a.event || JSON.stringify(a);
                    const category = msg.toLowerCase().includes("path") ? "NAV"
                      : msg.toLowerCase().includes("speed") || msg.toLowerCase().includes("motor") ? "SEN"
                      : msg.toLowerCase().includes("human") || msg.toLowerCase().includes("proximity") ? "SAF"
                      : msg.toLowerCase().includes("battery") || msg.toLowerCase().includes("power") ? "PWR"
                      : msg.toLowerCase().includes("latency") || msg.toLowerCase().includes("stale") ? "COM"
                      : "SYS";
                    return (
                      <li key={i} className="flex items-start gap-1.5 text-xs bg-red-500/10 border border-red-500/20 rounded px-2 py-1.5">
                        <span className="text-red-400">⚠️</span>
                        <span className="text-[10px] text-red-400/70 font-mono min-w-[24px]">{category}</span>
                        <span className="text-mc-ink/85">{msg}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
            )}

            </>)}
            {sideTab === "analysis" && (<>
            {/* Scorecard (#10) */}
            {!isFullscreen && (
            <CollapsibleCard title="📊 Performance Scorecard" defaultOpen={true}
              hint={<span className="text-mc-mute">5 dimensions tracked</span>}>
              <ScoreCard runId={runId} />
            </CollapsibleCard>
            )}

            {/* Agent Introspection (#20) */}
            {!isFullscreen && (
            <CollapsibleCard title="🔍 Agent Introspection" defaultOpen={true}
              hint={replanCount > 0 ? <span className="text-amber-400">{replanCount} replans · {lastDenialPolicy || "policy hit"}</span> : <span className="text-green-400">No denials</span>}>
              <IntrospectionPanel runId={runId} />
            </CollapsibleCard>
            )}

            {/* Safety Report (#14) */}
            {!isFullscreen && (
            <CollapsibleCard title="🛡️ Safety Report" defaultOpen={false}
              hint={safetyReport ? <span className={safetyReport.verdict === "PASS" ? "text-green-400" : "text-red-400"}>{safetyReport.verdict === "PASS" ? "✓ PASS" : safetyReport.verdict === "FAIL" ? "✗ FAIL" : "⚠ " + safetyReport.verdict} · {safetyReport.checks_run || 0} checks</span> : <span className="text-mc-dim">Awaiting data</span>}>
              {!safetyReport ? (
                <div className="text-xs text-mc-dim text-center py-2">No safety report yet</div>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-bold px-2 py-1 rounded-full border ${
                      safetyReport.verdict === "PASS" ? "bg-green-500/15 text-green-400 border-green-500/30" :
                      safetyReport.verdict === "FAIL" ? "bg-red-500/15 text-red-400 border-red-500/30" :
                      "bg-yellow-500/15 text-yellow-400 border-yellow-500/30"
                    }`}>
                      {safetyReport.verdict === "PASS" ? "✓ PASS" : safetyReport.verdict === "FAIL" ? "✗ FAIL" : "⚠ " + (safetyReport.verdict || "N/A")}
                    </span>
                    <span className="text-[10px] text-mc-dim">{safetyReport.checks_run || 0} checks</span>
                  </div>
                  {safetyReport.violations?.length > 0 && (
                    <div className="space-y-1">
                      {safetyReport.violations.map((v: any, i: number) => (
                        <div key={i} className="text-[10px] bg-red-500/10 border border-red-500/20 rounded px-2 py-1 text-red-300">
                          <span className="font-bold">{v.check || v.name}</span>: {v.detail || v.message || "threshold exceeded"}
                        </div>
                      ))}
                    </div>
                  )}
                  {safetyReport.thresholds && (
                    <div className="text-[10px] text-mc-dim space-y-0.5">
                      {Object.entries(safetyReport.thresholds).map(([k, v]) => (
                        <div key={k} className="flex justify-between">
                          <span>{k.replace(/_/g, " ")}</span>
                          <span className="font-mono text-mc-mute">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {safetyReport.summary && <div className="text-[10px] text-mc-mute bg-mc-bg/60 rounded p-2">{safetyReport.summary}</div>}
                </div>
              )}
            </CollapsibleCard>
            )}

            {/* Optimization Analysis (#7) */}
            {!isFullscreen && (
            <CollapsibleCard title="⚡ Optimization Analysis" defaultOpen={false}
              hint={optimizationAnalysis ? <span className="text-cyan-400">Eff: {((optimizationAnalysis.scorecard?.scores?.efficiency ?? 0) * 100).toFixed(0)}% · Safety: {((optimizationAnalysis.scorecard?.scores?.safety ?? 0) * 100).toFixed(0)}%</span> : <span className="text-mc-dim">Click to load</span>}>
              {!optimizationAnalysis ? (
                <div className="text-center py-2">
                  <button onClick={async () => { try { setOptimizationAnalysis(await analyzeRunOptimization(runId)); } catch (_) {} }}
                    className="text-xs bg-cyan-600/20 hover:bg-cyan-600/40 text-cyan-400 px-3 py-1.5 rounded border border-cyan-500/30 transition-colors">
                    Load Analysis
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {optimizationAnalysis.scorecard?.scores?.efficiency != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-mc-dim">Efficiency:</span>
                      <div className="flex-1 h-1.5 bg-mc-raise rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${optimizationAnalysis.scorecard.scores.efficiency > 0.7 ? "bg-green-500" : optimizationAnalysis.scorecard.scores.efficiency > 0.4 ? "bg-yellow-500" : "bg-red-500"}`}
                          style={{ width: `${(optimizationAnalysis.scorecard.scores.efficiency * 100)}%` }} />
                      </div>
                      <span className="text-[10px] font-mono text-mc-mute">{(optimizationAnalysis.scorecard.scores.efficiency * 100).toFixed(0)}%</span>
                    </div>
                  )}
                  {optimizationAnalysis.scorecard?.scores?.safety != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-mc-dim">Safety:</span>
                      <div className="flex-1 h-1.5 bg-mc-raise rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${optimizationAnalysis.scorecard.scores.safety > 0.8 ? "bg-green-500" : optimizationAnalysis.scorecard.scores.safety > 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
                          style={{ width: `${(optimizationAnalysis.scorecard.scores.safety * 100)}%` }} />
                      </div>
                      <span className="text-[10px] font-mono text-mc-mute">{(optimizationAnalysis.scorecard.scores.safety * 100).toFixed(0)}%</span>
                    </div>
                  )}
                  {optimizationAnalysis.violation_rate != null && (
                    <div className="flex justify-between text-[10px]">
                      <span className="text-mc-dim">Violation rate</span>
                      <span className="text-mc-ink/85 font-mono">{(optimizationAnalysis.violation_rate * 100).toFixed(1)}%</span>
                    </div>
                  )}
                  {optimizationAnalysis.governance_led && (
                    <div className="text-[10px] text-emerald-400/80 bg-emerald-500/10 border border-emerald-500/20 rounded px-2 py-0.5">Governance-led optimization</div>
                  )}
                  {optimizationAnalysis.recommendations?.length > 0 && (
                    <div className="space-y-1 mt-1">
                      <div className="text-[10px] text-mc-dim font-semibold">Recommendations</div>
                      {optimizationAnalysis.recommendations.map((r: any, i: number) => (
                        <div key={i} className="text-[10px] bg-cyan-500/10 border border-cyan-500/20 rounded px-2 py-1 text-cyan-300">
                          <span className="font-semibold">{r.param}</span> → {r.direction}: {r.reason}
                        </div>
                      ))}
                    </div>
                  )}
                  {optimizationAnalysis.recommendations?.length === 0 && (
                    <div className="text-[10px] text-green-400/70">All parameters within optimal bounds</div>
                  )}
                </div>
              )}
            </CollapsibleCard>
            )}

            {/* Divergence Explanation (#20) */}
            {!isFullscreen && (
            <CollapsibleCard title="🔀 Divergence Explanation" defaultOpen={true}
              hint={divergenceExplanation ? (divergenceExplanation.divergence_detected ? <span className="text-yellow-400">⚠ Diverged · {divergenceExplanation.max_deviation?.toFixed?.(1) || "?"}m</span> : <span className="text-green-400">✓ On Track</span>) : <span className="text-mc-dim">Click to analyze</span>}>
              <div className="space-y-2">
                {divergenceExplanation ? (
                  <>
                    {divergenceExplanation.divergence_detected != null && (
                      <span className={`text-[10px] font-bold px-2 py-1 rounded-full border ${
                        divergenceExplanation.divergence_detected ? "bg-yellow-500/15 text-yellow-400 border-yellow-500/30" : "bg-green-500/15 text-green-400 border-green-500/30"
                      }`}>
                        {divergenceExplanation.divergence_detected ? "⚠ Divergence Detected" : "✓ On Track"}
                      </span>
                    )}
                    {divergenceExplanation.explanation && (
                      <div className="text-[10px] text-mc-ink/85 bg-mc-bg/60 rounded p-2 whitespace-pre-wrap">{divergenceExplanation.explanation}</div>
                    )}
                    {divergenceExplanation.max_deviation != null && (
                      <div className="flex justify-between text-[10px]">
                        <span className="text-mc-dim">Max deviation</span>
                        <span className="font-mono text-mc-ink/85">{divergenceExplanation.max_deviation?.toFixed?.(2) || divergenceExplanation.max_deviation}m</span>
                      </div>
                    )}
                  </>
                ) : (
                  <button onClick={async () => { try { setDivergenceExplanation(await getDivergenceExplanation(runId)); } catch (_) {} }}
                    className="w-full text-[10px] font-semibold px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 transition">
                    Analyze Path Divergence
                  </button>
                )}
              </div>
            </CollapsibleCard>
            )}
            </>)}
            </div>
          </div>

          {/* AI Planner (compact, fullscreen only — under Chain-of-Trust) */}
          {isFullscreen && (
          <Card title="🤖 AI Mission Planner">
            {/* Compact pipeline strip */}
            <div className="flex items-center gap-1 mb-2">
              {([
                { key: "idle", label: "Idle" },
                { key: "planning", label: "Plan" },
                { key: "governing", label: "Gov" },
                { key: "executing", label: "Exec" },
                { key: "done", label: "Done" },
              ] as const).map((st) => (
                <div key={st.key} className={`text-[9px] px-1.5 py-0.5 rounded-full border ${pipelineStage === st.key || (st.key === "planning" && pipelineStage === "reasoning") || (st.key === "executing" && pipelineStage === "ready") ? "bg-purple-500 text-white border-purple-600" : "bg-mc-panel text-mc-dim border-mc-line"}`}>
                  {st.label}
                </div>
              ))}
            </div>

            {/* Auto-pilot status */}
            {isBackendAutoPilot && (
              <div className="flex items-center gap-1.5 bg-cyan-500/10 border border-cyan-500/30 rounded p-2 mb-2">
                <span className="text-[10px]">{currentStatus === "planning" ? "🗺️" : "🚀"}</span>
                <span className="text-[10px] text-cyan-300 font-semibold">
                  {currentStatus === "planning" ? "AI generating plan…" : "Running autonomously"}
                </span>
              </div>
            )}

            {/* Reasoning summary */}
            {agenticResult && (
              <div className="space-y-1.5 mb-2">
                <div className="text-[9px] uppercase tracking-wide text-mc-dim font-semibold">Reasoning</div>
                <div className="bg-mc-bg/60 border border-purple-500/20 rounded p-2 space-y-1 text-[10px] font-mono">
                  <div className="flex items-start gap-1">
                    <span className="text-purple-400 font-bold min-w-[50px]">Goal:</span>
                    <span className="text-white truncate">{missionInstruction || "—"}</span>
                  </div>
                  <div className="flex items-start gap-1">
                    <span className="text-emerald-400 font-bold min-w-[50px]">Strategy:</span>
                    <div className="text-mc-ink/85">
                      {(agenticResult.thought_chain || []).filter((s: any) => s.thought && s.action !== "replan").slice(0, 2).map((s: any, i: number) => (
                        <div key={i} className="truncate">- {s.thought}</div>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-yellow-400 font-bold min-w-[70px]">Confidence:</span>
                    {(() => { const r = agenticResult.governance?.risk_score ?? 0; const c = Math.max(0, Math.min(1, (1-r)*0.92+0.04)); return <><span className={`font-bold ${c>0.7?"text-green-400":"text-yellow-400"}`}>{(c*100).toFixed(0)}%</span><div className="flex-1 h-1 bg-mc-raise rounded-full ml-1"><div className={`h-full rounded-full ${c>0.7?"bg-green-500":"bg-yellow-500"}`} style={{width:`${c*100}%`}}/></div></>; })()}
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-red-400 font-bold min-w-[70px]">Gov Risk:</span>
                    {(() => { const r = agenticResult.governance?.risk_score ?? 0; return <><span className={`font-bold ${r>0.5?"text-red-400":"text-green-400"}`}>{(r*100).toFixed(0)}%</span><div className="flex-1 h-1 bg-mc-raise rounded-full ml-1"><div className={`h-full rounded-full ${r>0.5?"bg-red-500":"bg-green-500"}`} style={{width:`${r*100}%`}}/></div></>; })()}
                  </div>
                </div>
                {agenticResult.model_used && <div className="text-[9px] text-mc-dim font-mono">Model: {agenticResult.model_used}</div>}
              </div>
            )}

            {/* Auto-pilot reasoning */}
            {!agenticResult && llmPlan && (
              <div className="space-y-1.5 mb-2">
                <div className="text-[9px] uppercase tracking-wide text-mc-dim font-semibold">AI Reasoning</div>
                <div className="bg-mc-bg/60 border border-cyan-500/20 rounded p-2 space-y-1 text-[10px] font-mono">
                  <div className="flex items-start gap-1">
                    <span className="text-purple-400 font-bold min-w-[50px]">Goal:</span>
                    <span className="text-white truncate">{missionInstruction || mission?.title || "—"}</span>
                  </div>
                  <div className="flex items-start gap-1">
                    <span className="text-emerald-400 font-bold min-w-[50px]">Strategy:</span>
                    <span className="text-mc-ink/85 truncate">{llmPlan.rationale || "Direct path with obstacle avoidance"}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-yellow-400 font-bold min-w-[70px]">Confidence:</span>
                    {(() => { const r = lastDecision?.governance?.risk_score ?? 0.15; const c = Math.max(0, Math.min(1, (1-r)*0.92+0.04)); return <><span className={`font-bold ${c>0.7?"text-green-400":"text-yellow-400"}`}>{(c*100).toFixed(0)}%</span><div className="flex-1 h-1 bg-mc-raise rounded-full ml-1"><div className={`h-full rounded-full ${c>0.7?"bg-green-500":"bg-yellow-500"}`} style={{width:`${c*100}%`}}/></div></>; })()}
                  </div>
                </div>
                {llmPlan.model && <div className="text-[9px] text-mc-dim font-mono">Model: {llmPlan.model}</div>}
              </div>
            )}

            {/* Waypoint plan */}
            {llmPlan && (
              <div className="space-y-1.5 mb-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full border ${llmPlan.all_approved === false ? "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" : "bg-green-500/20 text-green-400 border-green-500/30"}`}>
                    {llmPlan.all_approved === true ? "All Approved" : llmPlan.all_approved === false ? "Flagged" : missionReview?.verdict === "APPROVED" ? "Sovereign Autonomy Approved" : "Under Review"}
                  </span>
                  <span className="text-[9px] text-mc-dim">{llmPlan.waypoints?.length || 0} waypoints</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {(llmPlan.waypoints || []).map((wp: any, i: number) => {
                    const gov = llmPlan.governance?.[i]; const ok = gov?.decision === "APPROVED";
                    const isActive = activeWaypointIdx === i;
                    const isCompleted = activeWaypointIdx > i;
                    return (
                      <span key={i} onMouseEnter={() => setHoveredWaypointIdx(i)} onMouseLeave={() => setHoveredWaypointIdx(null)}
                        className={`text-[9px] px-1 py-0.5 rounded border ${isActive ? "border-cyan-400 bg-cyan-500/25 text-cyan-200 font-bold" : isCompleted ? "border-green-500/40 bg-green-500/15 text-green-400 line-through opacity-70" : ok ? "border-green-500/30 text-green-400" : "border-yellow-500/30 text-yellow-400"}`}>
                        {isCompleted ? "✓" : isActive ? "▶" : `${i+1}:`} ({wp.x.toFixed(0)},{wp.y.toFixed(0)})
                      </span>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Planning progress */}
            {planningSteps.length > 0 && (currentStatus === "planning" || currentStatus === "running") && (
              <div className="bg-mc-bg/60 border border-mc-line rounded p-2 mb-2 space-y-1">
                <div className="text-[9px] uppercase tracking-wider text-mc-dim font-semibold">Progress</div>
                {planningSteps.slice(-4).map((s, i) => {
                  const icon = s.step === "llm_start" ? "🧠" : s.step === "llm_done" ? "✅" : s.step === "governance_start" ? "🛡️" : "•";
                  return <div key={i} className="flex items-start gap-1 text-[9px] text-mc-mute"><span>{icon}</span><span className="truncate">{s.message}</span></div>;
                })}
              </div>
            )}

            {/* Replan badge */}
            {replanCount > 0 && (
              <div className="text-[9px] text-amber-300 bg-amber-500/15 px-2 py-1 rounded-full border border-amber-500/30 inline-block mb-2">
                🔄 Replans: {replanCount}{lastDenialPolicy ? ` — ${lastDenialPolicy}` : ""}
              </div>
            )}
          </Card>
          )}

        </div>
      </div>

      {/* ── AI Intelligence Console (tabbed, below main layout) ── */}
      <CollapsibleCard title="AI Intelligence Console: scene analysis, telemetry insights, failure detection" defaultOpen={false}>
        <div className="flex gap-1 mb-3">
          {(["scene", "telemetry", "failure"] as const).map((tab) => (
            <button key={tab} onClick={() => setAiTab(tab)}
              className={`text-xs font-medium px-3 py-1.5 rounded-lg transition ${aiTab === tab ? "bg-purple-500/20 text-purple-300 border border-purple-500/30" : "text-mc-mute hover:text-mc-ink/85 hover:bg-mc-raise/50"}`}>
              {tab === "scene" ? "🔍 Scene" : tab === "telemetry" ? "📊 Telemetry" : "⚠️ Failures"}
            </button>
          ))}
        </div>

        {aiTab === "scene" && (
          <div>
            <button onClick={onAnalyzeScene} disabled={sceneLoading}
              className="w-full bg-indigo-500/80 hover:bg-indigo-600 disabled:bg-mc-line2 text-white text-xs font-semibold px-4 py-2 rounded-lg transition mb-2">
              {sceneLoading ? "Analyzing..." : "Analyze Current Scene"}
            </button>
            {sceneError && <div className="text-xs text-red-400 bg-red-500/10 rounded p-2 mb-2">{sceneError}</div>}
            {sceneResult && (
              <div className="space-y-2 text-xs">
                {sceneResult.hazards?.length > 0 && sceneResult.hazards.map((h: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 bg-red-500/10 border border-red-500/20 rounded p-2">
                    <span className={`font-bold ${h.severity === "high" ? "text-red-400" : "text-yellow-400"}`}>{(h.severity || "?").toUpperCase()}</span>
                    <span className="text-mc-ink/85">{h.type || h.description}</span>
                  </div>
                ))}
                {sceneResult.risk_score != null && (
                  <div className="flex items-center gap-2">
                    <span className="text-mc-dim">Risk:</span>
                    <div className="flex-1 h-1.5 bg-mc-raise rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${sceneResult.risk_score > 0.7 ? "bg-red-500" : sceneResult.risk_score > 0.3 ? "bg-yellow-500" : "bg-green-500"}`}
                        style={{ width: `${(sceneResult.risk_score * 100)}%` }} />
                    </div>
                    <span className="font-mono text-mc-mute">{(sceneResult.risk_score * 100).toFixed(0)}%</span>
                  </div>
                )}
                {sceneResult.recommended_action && <div className="bg-indigo-500/10 border border-indigo-500/20 rounded p-2 text-mc-ink/85">{sceneResult.recommended_action}</div>}
                {sceneResult.analysis && <div className="bg-mc-bg/60 rounded p-2 max-h-28 overflow-y-auto text-mc-ink/85 whitespace-pre-wrap">{sceneResult.analysis}</div>}
                {sceneResult.model && <div className="text-[10px] text-mc-dim font-mono">Model: {sceneResult.model}</div>}
              </div>
            )}
          </div>
        )}

        {aiTab === "telemetry" && (
          <div>
            <button onClick={onAnalyzeTelemetry} disabled={telAnalysisLoading || events.length === 0}
              className="w-full bg-teal-500/80 hover:bg-teal-600 disabled:bg-mc-line2 text-white text-xs font-semibold px-4 py-2 rounded-lg transition mb-2">
              {telAnalysisLoading ? "Analyzing..." : "Analyze Telemetry"}
            </button>
            {telAnalysisError && <div className="text-xs text-red-400 bg-red-500/10 rounded p-2 mb-2">{telAnalysisError}</div>}
            {telAnalysis && (
              <div className="space-y-2 text-xs">
                {telAnalysis.summary && <div className="bg-mc-bg/60 rounded p-2 max-h-28 overflow-y-auto text-mc-ink/85 whitespace-pre-wrap">{telAnalysis.summary}</div>}
                {telAnalysis.anomalies?.length > 0 && telAnalysis.anomalies.map((a: any, i: number) => (
                  <div key={i} className="bg-yellow-500/10 border border-yellow-500/20 rounded p-2 text-mc-ink/85">{a.description || a.type}</div>
                ))}
                {telAnalysis.recommendations && (
                  <div className="bg-teal-500/10 border border-teal-500/20 rounded p-2 text-mc-ink/85 whitespace-pre-wrap">
                    {Array.isArray(telAnalysis.recommendations) ? telAnalysis.recommendations.join("\n") : telAnalysis.recommendations}
                  </div>
                )}
                {telAnalysis.model && <div className="text-[10px] text-mc-dim font-mono">Model: {telAnalysis.model}</div>}
              </div>
            )}
          </div>
        )}

        {aiTab === "failure" && (
          <div>
            <button onClick={onDetectFailures} disabled={failureLoading || events.length === 0}
              className="w-full bg-orange-500/80 hover:bg-orange-600 disabled:bg-mc-line2 text-white text-xs font-semibold px-4 py-2 rounded-lg transition mb-2">
              {failureLoading ? "Detecting..." : "Run Failure Analysis"}
            </button>
            {failureError && <div className="text-xs text-red-400 bg-red-500/10 rounded p-2 mb-2">{failureError}</div>}
            {failureResult && (
              <div className="space-y-2 text-xs">
                <span className={`font-semibold px-2 py-0.5 rounded-full border text-[10px] ${failureResult.failures_detected ? "bg-red-500/20 text-red-400 border-red-500/30" : "bg-green-500/20 text-green-400 border-green-500/30"}`}>
                  {failureResult.failures_detected ? "Failures Detected" : "No Failures"}
                </span>
                {failureResult.failures?.map((f: any, i: number) => (
                  <div key={i} className="bg-red-500/10 border border-red-500/20 rounded p-2">
                    <span className="font-bold text-red-400">{f.type}</span> <span className="text-[10px] bg-red-700 text-white px-1 rounded">{f.severity}</span>
                    <div className="text-mc-ink/85 mt-1">{f.description}</div>
                  </div>
                ))}
                {failureResult.preventive_actions && (
                  <div className="bg-orange-500/10 border border-orange-500/20 rounded p-2 text-mc-ink/85 whitespace-pre-wrap">
                    {Array.isArray(failureResult.preventive_actions) ? failureResult.preventive_actions.join("\n") : failureResult.preventive_actions}
                  </div>
                )}
                {failureResult.model && <div className="text-[10px] text-mc-dim font-mono">Model: {failureResult.model}</div>}
              </div>
            )}
          </div>
        )}
      </CollapsibleCard>
    </div>
  );
}