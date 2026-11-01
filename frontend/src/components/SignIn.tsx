"use client";

/** Sign-in control: shows the signed-in user and role, or a small sign-in form. */
import React, { useEffect, useState } from "react";
import { signIn, signOut, storedSession } from "@/lib/api";
import { Button, cx } from "@/components/ui";

export function SignIn() {
  const [session, setSession] = useState<{ user: string; role: string } | null>(null);
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setSession(storedSession()); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const s = await signIn(user, pw);
      setSession(s); setOpen(false); setPw("");
    } catch (ex: any) { setErr(ex.message); }
    setBusy(false);
  };

  if (session) {
    return (
      <button onClick={() => { signOut(); setSession(null); }} title="Sign out"
        className="hidden sm:flex items-center gap-2 rounded-full border border-mc-line2 bg-mc-raise px-3 py-1 text-xs text-mc-mute hover:text-mc-ink">
        <span className="text-mc-ink">{session.user}</span>
        <span className={cx("font-semibold uppercase", session.role === "admin" ? "text-mc-warn" : "text-mc-accent")}>{session.role}</span>
      </button>
    );
  }
  return (
    <div className="relative hidden sm:block">
      <button onClick={() => setOpen(!open)} className="rounded-full border border-mc-line2 px-3 py-1 text-xs text-mc-mute hover:text-mc-ink">
        Sign in
      </button>
      {open && (
        <form onSubmit={submit} className="absolute right-0 top-full mt-2 w-64 rounded-xl border border-mc-line bg-mc-panel p-3 shadow-xl z-50 space-y-2">
          <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="Username" autoComplete="username"
            className="w-full rounded-lg border border-mc-line2 bg-mc-raise px-2.5 py-1.5 text-sm text-mc-ink outline-none focus:border-mc-accent" />
          <input value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" type="password" autoComplete="current-password"
            className="w-full rounded-lg border border-mc-line2 bg-mc-raise px-2.5 py-1.5 text-sm text-mc-ink outline-none focus:border-mc-accent" />
          {err && <div className="text-xs text-mc-stop">{err}</div>}
          <Button variant="primary" className="w-full" disabled={busy || !user || !pw}>{busy ? "Signing in…" : "Sign in"}</Button>
          <p className="text-[11px] text-mc-dim leading-snug">Stopping the robot never needs a sign-in. Mission control needs an operator; rule changes need an admin.</p>
        </form>
      )}
    </div>
  );
}
