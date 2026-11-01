"use client";

/**
 * Execution authority controls: kill switches (stop robot / stop everything),
 * the spoken stop, reset, and live permit status. Stopping never needs a login;
 * resetting does, and old permits stay void after a reset.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { getAuthorityStatus, killSwitch, resetKillSwitch, voiceStop } from "@/lib/api";
import { startRecording, type Recorder } from "@/lib/wav";
import { Button, KV, Notice, Panel, Pill, cx } from "@/components/ui";

type Lock = { scope: string; id: string; reason: string; actor: string; since: number };
type Status = { enabled: boolean; robot_id: string; epoch: number; kill_locks: Lock[]; world_version: number | null; journal_intact: boolean };

export function AuthorityPanel({ compact = false }: { compact?: boolean }) {
  const [s, setS] = useState<Status | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "warn" | "stop" | "info"; text: string } | null>(null);
  const [recording, setRecording] = useState(false);
  const rec = useRef<Recorder | null>(null);

  const load = useCallback(async () => {
    try { setS(await getAuthorityStatus()); } catch { /* backend offline: keep last state */ }
  }, []);
  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [load]);

  const stop = async (scope: "robot" | "global") => {
    setBusy(scope);
    try {
      const r = await killSwitch(scope, scope === "robot" ? s?.robot_id || "robot-1" : "*",
        scope === "robot" ? "operator stop (robot)" : "operator stop (everything)");
      setMsg({ tone: r.stop_verified ? "ok" : "warn",
        text: `Authority revoked in ${r.authority_revoked_ms} ms. ${r.stop_verified ? `Stop confirmed in ${r.stop_verified_ms} ms.` : "Stop NOT confirmed — check the robot."}` });
    } catch (e: any) { setMsg({ tone: "stop", text: e.message }); }
    setBusy(null);
    load();
  };

  const reset = async (lock: Lock) => {
    setBusy(`reset-${lock.scope}`);
    try {
      const r = await resetKillSwitch(lock.scope as any, lock.id);
      setMsg({ tone: "info", text: r.still_stopped ? "Lock lifted; another lock still holds the robot." : "Lock lifted. New moves need fresh permits." });
    } catch (e: any) { setMsg({ tone: "stop", text: e.message }); }
    setBusy(null);
    load();
  };

  const voice = async () => {
    if (!recording) {
      try {
        rec.current = await startRecording();
        setRecording(true);
        setMsg({ tone: "info", text: "Listening… say “stop the robot” or “stop everything”, then press again." });
      } catch { setMsg({ tone: "stop", text: "Microphone not available" }); }
      return;
    }
    setRecording(false);
    setBusy("voice");
    try {
      const wav = await rec.current!.stop();
      const r = await voiceStop(wav);
      setMsg(r.action === "kill"
        ? { tone: r.stop_verified ? "ok" : "warn", text: `Heard “${r.transcript}” → ${r.scope} stop. Revoked in ${r.authority_revoked_ms} ms; stop ${r.stop_verified ? `confirmed in ${r.stop_verified_ms} ms` : "not confirmed"}.` }
        : { tone: "info", text: `Heard “${r.transcript}”. No stop phrase — voice can only stop the robot.` });
    } catch (e: any) { setMsg({ tone: "stop", text: e.message }); }
    setBusy(null);
    load();
  };

  const locked = (s?.kill_locks?.length || 0) > 0;
  return (
    <Panel title="Execution authority"
      subtitle={compact ? undefined : "Nothing moves without a single-use permit. Stopping never needs a login."}
      actions={s && <Pill tone={!s.enabled ? "stop" : locked ? "stop" : "ok"} dot>{!s.enabled ? "No permit secret" : locked ? "Stopped" : "Permits enforced"}</Pill>}>
      <div className={cx("grid gap-2", compact ? "grid-cols-1" : "sm:grid-cols-3")}>
        <Button variant="danger" disabled={!!busy} onClick={() => stop("robot")}>{busy === "robot" ? "Stopping…" : "Stop robot"}</Button>
        <Button variant="danger" disabled={!!busy} onClick={() => stop("global")}>{busy === "global" ? "Stopping…" : "Stop everything"}</Button>
        <Button variant={recording ? "primary" : "secondary"} disabled={busy === "voice"} onClick={voice}
          title="Muse Voice Transcribe: a spoken stop fires a kill switch">
          {recording ? "● Listening — press to send" : busy === "voice" ? "Transcribing…" : "🎙 Voice stop"}
        </Button>
      </div>

      {msg && <div className="mt-3"><Notice tone={msg.tone}>{msg.text}</Notice></div>}

      {locked && (
        <div className="mt-3 space-y-2">
          {s!.kill_locks.map((l) => (
            <div key={`${l.scope}-${l.id}`} className="flex items-center justify-between gap-2 rounded-lg border border-mc-stop/30 bg-mc-stop/10 px-3 py-2">
              <div className="min-w-0 text-xs">
                <div className="font-semibold text-mc-stop uppercase">{l.scope}{l.id !== "*" ? ` · ${l.id}` : ""}</div>
                <div className="text-mc-mute truncate">{l.reason} · by {l.actor}</div>
              </div>
              <Button disabled={!!busy} onClick={() => reset(l)} className="shrink-0">Reset (operator)</Button>
            </div>
          ))}
        </div>
      )}

      {s && !compact && (
        <div className="mt-3">
          <KV k="Robot" v={s.robot_id} mono />
          <KV k="Authority epoch" v={s.epoch} mono />
          <KV k="World version" v={s.world_version ?? "—"} mono />
          <KV k="Action journal" v={s.journal_intact ? "intact" : "TAMPERED"} />
        </div>
      )}
    </Panel>
  );
}
