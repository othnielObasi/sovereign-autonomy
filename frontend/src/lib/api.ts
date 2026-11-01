/**
 * Sovereign Autonomy frontend API client.
 *
 * Every exported function maps 1–1 to a backend REST endpoint.
 * All calls go through `fetchWithRetry` for automatic retry on
 * network failures and consistent error parsing.
 *
 * Convention: GET calls use `{ cache: "no-store" }` to defeat
 * Next.js server-side caching so the dashboard always shows live data.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

/** Retry wrapper – retries on network failures (TypeError: Failed to fetch) */
async function fetchWithRetry(
  input: RequestInfo,
  init?: RequestInit,
  retries = 2,
  delayMs = 500,
): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    try {
      const r = await fetch(input, init);
      return r;
    } catch (err: any) {
      // Only retry on network-level errors (Failed to fetch), not HTTP errors
      if (attempt >= retries) throw err;
      await new Promise((res) => setTimeout(res, delayMs * (attempt + 1)));
    }
  }
}

async function parseErrorResponse(r: Response, fallback: string): Promise<string> {
  try {
    const body = await r.json();
    if (body.detail) return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    return fallback;
  } catch {
    return fallback;
  }
}

export async function listMissions() {
  const r = await fetchWithRetry(`${API_BASE}/missions`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to list missions"));
  return r.json();
}

export async function createMission(payload: any) {
  const r = await fetchWithRetry(`${API_BASE}/missions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to create mission"));
  return r.json();
}

export async function updateMission(missionId: string, payload: { title?: string; goal?: any }) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to update mission"));
  return r.json();
}

export async function deleteMission(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to delete mission"));
  return r.json();
}

export async function pauseMission(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}/pause`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to pause mission"));
  return r.json();
}

export async function resumeMission(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}/resume`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to resume mission"));
  return r.json();
}

export async function startRun(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}/start`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to start run"));
  return r.json();
}

export async function listRuns(missionId?: string) {
  const params = missionId ? `?mission_id=${missionId}&limit=1` : '';
  const r = await fetchWithRetry(`${API_BASE}/runs${params}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to list runs"));
  return r.json();
}

export async function getRun(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get run"));
  return r.json();
}

export async function listEvents(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/events`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to list events"));
  return r.json();
}

export async function stopRun(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/stop`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to stop run"));
  return r.json();
}

export async function operatorOverride(runId: string, action: string, reason: string) {
  const r = await fetchWithRetry(`${API_BASE}/operator/override`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, action, reason }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to send operator override"));
  return r.json();
}

export async function listPolicies() {
  const r = await fetchWithRetry(`${API_BASE}/policies`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to list policies"));
  return r.json();
}

export async function testPolicy(payload: any) {
  const r = await fetchWithRetry(`${API_BASE}/policies/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to test policy"));
  return r.json();
}


export async function getTelemetry() {
  const r = await fetchWithRetry(`${API_BASE}/sim/telemetry`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get telemetry"));
  return r.json();
}

export async function getWorld() {
  const r = await fetchWithRetry(`${API_BASE}/sim/world`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get world"));
  return r.json();
}

export async function getPathPreview(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/path_preview`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get path preview"));
  return r.json();
}

export async function getMission(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get mission"));
  return r.json();
}

export async function triggerScenario(scenario: string) {
  const r = await fetchWithRetry(`${API_BASE}/sim/scenario`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to trigger scenario"));
  return r.json();
}

// ---- LLM: Models ----

export async function listLLMModels() {
  const r = await fetchWithRetry(`${API_BASE}/llm/models`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to list models"));
  return r.json();
}

export async function generateLLMPlan(instruction: string, goal?: { x: number; y: number }, model?: string) {
  const r = await fetchWithRetry(`${API_BASE}/llm/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction, goal: goal || null, model: model || null }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to generate LLM plan"));
  return r.json();
}

export async function executeLLMPlan(
  instruction: string,
  waypoints: Array<{ x: number; y: number; max_speed: number }>,
  rationale: string = ""
) {
  const r = await fetchWithRetry(`${API_BASE}/llm/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction, waypoints, rationale }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to execute LLM plan"));
  return r.json();
}

// ---- LLM: Telemetry Analysis ----

export async function analyzeTelemetry(events: any[], question?: string, model?: string) {
  const r = await fetchWithRetry(`${API_BASE}/llm/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events, question: question || null, model: model || null }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to analyze telemetry"));
  return r.json();
}

// ---- LLM: Scene Analysis (Multimodal) ----

export async function analyzeScene(sceneDescription: string, includeTelemetry: boolean = true, model?: string) {
  const r = await fetchWithRetry(`${API_BASE}/llm/scene`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scene_description: sceneDescription, include_telemetry: includeTelemetry, model: model || null }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to analyze scene"));
  return r.json();
}

// ---- LLM: Failure Detection ----

export async function detectFailures(events: any[], model?: string) {
  const r = await fetchWithRetry(`${API_BASE}/llm/failure-analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events, model: model || null }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to detect failures"));
  return r.json();
}

// ---- Agentic Planner ----

export async function agenticPropose(instruction: string, goal?: { x: number; y: number }) {
  const r = await fetchWithRetry(`${API_BASE}/llm/agentic/propose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction, goal: goal || null }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Agentic proposal failed"));
  return r.json();
}

// ---- Replay & Audit ----

export async function replayMission(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}/replay`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to replay mission"));
  return r.json();
}

export async function getMissionAudit(missionId: string) {
  const r = await fetchWithRetry(`${API_BASE}/missions/${missionId}/audit`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get mission audit"));
  return r.json();
}

export async function getAllAudit(limit = 100, offset = 0) {
  const r = await fetchWithRetry(`${API_BASE}/audit/missions?limit=${limit}&offset=${offset}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get audit trail"));
  return r.json();
}

// ---- Compliance ----

export async function getComplianceReport(runId: string, framework = "ISO_42001") {
  const r = await fetchWithRetry(`${API_BASE}/compliance/report/${runId}?framework=${encodeURIComponent(framework)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get compliance report"));
  return r.json();
}

export async function getComplianceFrameworks() {
  const r = await fetchWithRetry(`${API_BASE}/compliance/frameworks`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get frameworks"));
  return r.json();
}

export async function verifyAuditChain(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/compliance/verify/${runId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to verify audit chain"));
  return r.json();
}

export async function evaluateGovernance(telemetry: any, proposal: any) {
  const r = await fetchWithRetry(`${API_BASE}/governance/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ telemetry, proposal }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Governance evaluation failed"));
  return r.json();
}

// ---- Scoring (#10) ----

export async function getRunScores(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/scores`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get scores"));
  return r.json();
}

// ---- Risk Heatmap (#21) ----

export async function getRiskHeatmap(runId: string, gridSize = 2.0) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/risk-heatmap?grid_size=${gridSize}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get risk heatmap"));
  return r.json();
}

// ---- Agent Introspection (#20) ----

export async function getRunIntrospection(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/introspection`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get introspection"));
  return r.json();
}

// ---- Optimizer (#7) ----

export async function getOptimizationEnvelope() {
  const r = await fetchWithRetry(`${API_BASE}/optimizer/envelope`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get optimization envelope"));
  return r.json();
}

export async function analyzeRunOptimization(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/optimizer/analyze/${runId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to analyze optimization"));
  return r.json();
}

// ---- Adaptive Tuning (#12, #13) ----

export async function getTuningRecommendations() {
  const r = await fetchWithRetry(`${API_BASE}/tuning/recommendations`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get tuning recommendations"));
  return r.json();
}

// ---- Integrity Monitor (#15) ----

export async function checkRunIntegrity(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/integrity/run/${runId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to check integrity"));
  return r.json();
}

export async function checkCrossRunIntegrity() {
  const r = await fetchWithRetry(`${API_BASE}/integrity/cross-run`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to check cross-run integrity"));
  return r.json();
}

// ---- Agent Memory (#17, #18) ----

export async function getAgentMemory(category?: string) {
  const params = category ? `?category=${category}` : '';
  const r = await fetchWithRetry(`${API_BASE}/agent/memory${params}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get agent memory"));
  return r.json();
}

export async function getAgentMemoryStats() {
  const r = await fetchWithRetry(`${API_BASE}/agent/memory/stats`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get memory stats"));
  return r.json();
}

export async function extractLessons(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/agent/memory/learn/${runId}`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to extract lessons"));
  return r.json();
}

// ---- Policy Classification (#14) ----

export async function getPolicyClassification() {
  const r = await fetchWithRetry(`${API_BASE}/policies/classification`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get policy classification"));
  return r.json();
}

// ---- Policy Version History (#16) ----

export async function getPolicyVersions() {
  const r = await fetchWithRetry(`${API_BASE}/policies/versions`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get policy versions"));
  return r.json();
}

// ---- Safety Report (#14) ----

export async function getRunSafetyReport(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/safety-report`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get safety report"));
  return r.json();
}

// ---- Adversarial Validation (#15) ----

export async function runAdversarialValidation() {
  const r = await fetchWithRetry(`${API_BASE}/adversarial/validate`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to run adversarial validation"));
  return r.json();
}

// ---- Semantic Memory Search (#17) ----

export async function searchAgentMemory(query: string, category?: string) {
  const params = new URLSearchParams({ query });
  if (category) params.set("category", category);
  const r = await fetchWithRetry(`${API_BASE}/agent/memory/search?${params}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to search memory"));
  return r.json();
}

// ---- Cross-Run Learning (#18) ----

export async function getCrossRunLearning() {
  const r = await fetchWithRetry(`${API_BASE}/agent/cross-run-learning`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get cross-run learning"));
  return r.json();
}

// ---- Score Trends (#10) ----

export async function getScoreTrends(limit = 20) {
  const r = await fetchWithRetry(`${API_BASE}/analytics/score-trends?limit=${limit}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get score trends"));
  return r.json();
}

// ---- Divergence Explanation (#20) ----

export async function getDivergenceExplanation(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/divergence-explanation`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get divergence explanation"));
  return r.json();
}

// ---- Executed Path (#3) ----

export async function getExecutedPath(runId: string) {
  const r = await fetchWithRetry(`${API_BASE}/runs/${runId}/executed-path`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to get executed path"));
  return r.json();
}

/* ── Site intelligence (Tavily, untrusted input) ─────────────────────────── */

export async function getSiteIntelStatus() {
  const r = await fetchWithRetry(`${API_BASE}/site-intel/status`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to load site intelligence status"));
  return r.json();
}

export async function getSiteIntelLookups(limit = 5) {
  const r = await fetchWithRetry(`${API_BASE}/site-intel/lookups?limit=${limit}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to load lookups"));
  return r.json();
}

export async function getBulletins(limit = 5) {
  const r = await fetchWithRetry(`${API_BASE}/site-intel/bulletins?limit=${limit}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to load bulletins"));
  return r.json();
}

export async function postBulletin(text: string, source = "noticeboard") {
  const r = await fetchWithRetry(`${API_BASE}/site-intel/bulletin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source }),
  });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to post bulletin"));
  return r.json();
}

/* ── Vision: NVIDIA VLM reads the robot camera, cross-checked with sensors ── */

export async function getPerceptionStatus() {
  const r = await fetchWithRetry(`${API_BASE}/perception/status`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Failed to load vision status"));
  return r.json();
}

export async function runPerceptionCheck() {
  const r = await fetch(`${API_BASE}/perception/check`, { method: "POST" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Vision check failed"));
  return r.json();
}

/* ── Evidence, governance history, learning, receipts ─────────────────────── */

async function getJson(path: string, what: string) {
  const r = await fetchWithRetry(`${API_BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await parseErrorResponse(r, `Failed to load ${what}`));
  return r.json();
}

export const getBenchmarks = () => getJson("/evidence/benchmarks", "benchmark results");
export const getActivePolicies = () => getJson("/policies/active", "active rules");
export const getPolicyActivations = () => getJson("/policies/activations", "rule activations");
export const getPolicyProposals = () => getJson("/policies/proposals", "rule proposals");
export const getLessons = () => getJson("/agent/lessons", "planner lessons");
export const getSigningKey = () => getJson("/governance/signing-key", "signing key");
export const getReceipts = (runId: string) => getJson(`/governance/receipts/${runId}`, "receipts");
export const verifyReceipt = (runId: string, id: string) => getJson(`/governance/receipts/${runId}/${id}/verify`, "receipt check");
export const getDecisionStats = (runId: string) => getJson(`/governance/decisions/${runId}/stats`, "decision stats");
export const getLlmUsage = () => getJson("/llm/usage", "model usage");
export const getLlmModels = () => getJson("/llm/models", "model tiers");
export const getLearningSummary = () => getJson("/evidence/learning", "learning summary");
export async function checkPlanForDrift(body: { start: { x: number; y: number }; goal: { x: number; y: number }; waypoints: Array<{ x: number; y: number }> }) {
  const r = await fetch(`${API_BASE}/plans/check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await parseErrorResponse(r, "Plan check failed"));
  return r.json();
}
