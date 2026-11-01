export type MissionStatus = "draft" | "executing" | "paused" | "completed" | "deleted";

export type Mission = {
  id: string;
  title: string;
  goal: { x: number; y: number; [k: string]: any };
  status: MissionStatus;
  created_at: string;
  updated_at?: string | null;
};

export type MissionAuditEntry = {
  id: number;
  mission_id: string;
  ts: string;
  action: "CREATED" | "UPDATED" | "STATUS_CHANGE" | "DELETED" | "REPLAYED";
  actor: string;
  old_values: Record<string, any>;
  new_values: Record<string, any>;
  details: string | null;
};

export type WsMessage =
  | { kind: "telemetry"; data: any }
  | { kind: "event"; data: any }
  | { kind: "alert"; data: any }
  | { kind: "status"; data: any }
  | { kind: "planning_progress"; data: any }
  | { kind: "agent_reasoning"; data: any };
