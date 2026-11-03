"use client";
import { useEffect, useRef, useState } from 'react';
import { signIn, signOut, storedSession } from '@/lib/api';
import { Icon } from './control/Icon';

export function SignIn() {
  const [session, setSession] = useState<{ user: string; role: string } | null>(null);
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => { setSession(storedSession()); }, []);
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.querySelector<HTMLInputElement>('input')?.focus();
    function key(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
      if (e.key !== 'Tab') return;
      const nodes = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),a[href]') || []);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', key);
    return () => { document.body.style.overflow = previous; document.removeEventListener('keydown', key); trigger.current?.focus(); };
  }, [open]);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try { setSession(await signIn(username, password)); setPassword(''); setOpen(false); }
    catch (err: any) { setError(err.message || 'Sign-in failed. Check your credentials.'); }
    finally { setBusy(false); }
  }
  return <>
    {session ? <button className="sa-account" aria-label={`Sign out ${session.user}`} title={`Signed in as ${session.role}. Select to sign out.`} onClick={() => { signOut(); setSession(null); }}><span className="sa-avatar">{session.user.slice(0, 1).toUpperCase()}</span><span>{session.user}<small>{session.role} · Sign out</small></span></button> : <button ref={trigger} aria-label="Operator access" onClick={() => { setError(''); setOpen(true); }} className="sa-account"><Icon name="user" size={17}/><span>Operator access</span></button>}
    {open && <div className="sa-modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !busy) setOpen(false); }}>
      <div className="sa-modal" role="dialog" aria-modal="true" aria-labelledby="operator-title" aria-describedby="operator-description" ref={dialog}>
        <button className="sa-icon-button sa-modal-close" aria-label="Close sign-in" disabled={busy} onClick={() => setOpen(false)}><Icon name="cross"/></button>
        <span className="sa-modal-symbol"><Icon name="shield" size={28}/></span><p className="sa-eyebrow">SOVEREIGN AUTONOMY</p><h2 id="operator-title">Your workspace.<br/>Your authority.</h2><p id="operator-description">Sign in to manage missions and operator approvals. Viewing the workspace and stopping robots never require an account.</p>
        <form onSubmit={submit} className="sa-form"><label>Username<input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" required disabled={busy}/></label><label>Password<input value={password} onChange={e => setPassword(e.target.value)} type="password" autoComplete="current-password" required disabled={busy}/></label>{error && <p className="sa-error" role="alert">{error}</p>}<button className="sa-button sa-button-primary" disabled={busy || !username || !password}>{busy ? 'Signing in…' : 'Enter workspace'}<Icon name="arrow" size={17}/></button></form><p className="sa-modal-note">Use your Sovereign Autonomy operator account. Access is separate from other projects.</p>
      </div>
    </div>}
  </>;
}
