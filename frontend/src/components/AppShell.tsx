"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon, BrandMark } from "./control/Icon";
import { SignIn } from "./SignIn";
import { killSwitch } from '@/lib/api';
import { RuntimeCapabilitiesProvider } from './RuntimeCapabilities';

const navigation = [
  { href: '/mission-control', label: 'Mission control', icon: 'command', match: ['/mission-control', '/twin'] },
  { href: '/missions', label: 'Missions', icon: 'route', match: ['/missions'] },
  { href: '/runs', label: 'Mission history', icon: 'clock', match: ['/runs'] },
  { href: '/authority', label: 'Trust & security', icon: 'shield', match: ['/authority'] },
  { href: '/policies', label: 'Governance', icon: 'layers', match: ['/policies'] },
  { href: '/evidence', label: 'Evidence', icon: 'chart', match: ['/evidence', '/audit', '/compliance'] },
  { href: '/capabilities', label: 'Capabilities & tools', icon: 'layers', match: ['/capabilities', '/operations'] },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || '/';
  const [open, setOpen] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopMessage, setStopMessage] = useState('');
  const drawer = useRef<HTMLElement>(null);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    drawer.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
      if (e.key !== 'Tab') return;
      const nodes = Array.from(drawer.current?.querySelectorAll<HTMLElement>('a[href],button') || []);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    };
    const resize = () => { if (window.innerWidth >= 768) setOpen(false); };
    document.addEventListener('keydown', key); window.addEventListener('resize', resize);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', key); window.removeEventListener('resize', resize); menuTrigger.current?.focus(); };
  }, [open]);
  async function stopFleet() {
    setStopping(true); setStopMessage('Sending stop to the fleet…');
    try { const r = await killSwitch('global', '*', 'Mission control fleet stop'); setStopMessage(r.stop_verified ? 'Fleet stop confirmed by the controller.' : 'Stop not confirmed. Check the robot controller.'); }
    catch { setStopMessage('Stop not confirmed. The controller could not be reached.'); }
    finally { setStopping(false); }
  }
  const current = navigation.find(n => n.match.some(p => pathname.startsWith(p)));
  return <RuntimeCapabilitiesProvider><div className="sa-shell">
    <a href="#main-content" className="sa-skip">Skip to content</a>
    {open && <button className="sa-nav-backdrop" aria-label="Dismiss navigation overlay" tabIndex={-1} onClick={() => setOpen(false)} />}
    <aside ref={drawer} className={`sa-sidebar ${open ? 'is-open' : ''}`} aria-label="Primary navigation">
      <button className="sa-icon-button sa-nav-close" aria-label="Close navigation" onClick={() => setOpen(false)}><Icon name="cross" size={17}/></button>
      <Link href="/mission-control" className="sa-brand" onClick={() => setOpen(false)}><BrandMark /><span>Sovereign<span className="sa-brand-sub">AUTONOMY</span></span></Link>
      <div className="sa-workspace-label"><span className="sa-workspace-monogram">S</span><div>Operations workspace<small>Simulation environment</small></div><Icon name="down" size={14}/></div>
      <p className="sa-nav-caption">WORKSPACE</p>
      <nav className="sa-navigation">{navigation.map(n => <Link key={n.href} href={n.href} onClick={() => setOpen(false)} aria-current={current?.href === n.href ? 'page' : undefined} className={current?.href === n.href ? 'is-active' : ''}><Icon name={n.icon}/><span>{n.label}</span>{current?.href === n.href && <span className="sa-active-dot"/>}</Link>)}</nav>
      <div className="sa-sidebar-guide"><span className="sa-tiny-icon"><Icon name="bolt"/></span><h3>Plan. Adapt.<br/>Learn. Explain.</h3><p>Assign a mission, follow its progress and inspect the experience behind it.</p><Link href="/capabilities" onClick={() => setOpen(false)}>Explore the platform <Icon name="arrow" size={16}/></Link></div>
      <div className="sa-sidebar-bottom"><Link href="/overview" onClick={() => setOpen(false)}><Icon name="info" size={17}/> About the system</Link><div className="sa-sidebar-foot"><span className="sa-orbit-dot"/> Sovereign Autonomy <span>v0.1</span></div></div>
    </aside>
    <div className="sa-workspace">
      <header className="sa-topbar"><div className="sa-breadcrumb"><button ref={menuTrigger} className="sa-icon-button sa-mobile-menu" onClick={() => setOpen(!open)} aria-label="Open navigation" aria-expanded={open}><Icon name="menu"/></button><span>Workspace</span><Icon name="chevron" size={13}/><strong>{current?.label || 'System overview'}</strong></div><div className="sa-topbar-actions"><span className="sa-simulation-label"><span/> SIMULATION</span><button className="sa-stop-fleet" onClick={stopFleet} disabled={stopping}><Icon name="stop" size={15}/>{stopping ? 'Stopping…' : 'Stop fleet'}</button><SignIn/></div></header>
      {stopMessage && <div className="sa-stop-notice" role="status">{stopMessage}<button className="sa-icon-button" aria-label="Dismiss stop message" onClick={() => setStopMessage('')}><Icon name="cross" size={15}/></button></div>}
      <main id="main-content">{children}</main>
      {!pathname.startsWith('/mission-control') && <footer className="sa-footer"><span>Sovereign Autonomy · NOVTIA</span><Link href="/mission-control">Return to mission control <Icon name="arrow" size={14}/></Link></footer>}
    </div>
  </div></RuntimeCapabilitiesProvider>;
}
