"use client";

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import styles from './KnowledgeGraph.module.css';

export type KnowledgeFact = {
  event_id: string; event_hash: string; run_id: string; mission_id: string;
  robot_id: string; x: number; y: number; ts: string; cell_id: string;
  decision: string; policy_hits: string[]; receipt_id: number;
  context: { site_id: string; map_version: string; policy_version: string; capability_profile_version: string };
};
type GraphNode = { id: string; kind: string; label: string; detail: string; facts: KnowledgeFact[];
  x: number; y: number; w: number; h: number; color: string; fill: string };
type Edge = { from: string; to: string; label: string };
const VERDICTS: Record<string, string> = { APPROVED: 'Approved', DENIED: 'Blocked', NEEDS_REVIEW: 'Needs review' };
const POLICY_NAMES: Record<string, string> = {
  GEOFENCE_01: 'Facility boundary', SAFE_SPEED_01: 'Speed limit', HUMAN_PROXIMITY_02: 'Person too close',
  HUMAN_CLEARANCE_02: 'Clearance from people', OBSTACLE_CLEARANCE_03: 'Obstacle clearance',
  UNCERTAINTY_04: 'Uncertain perception', HITL_05: 'Human review', WORKER_PROXIMITY_06: 'Worker proximity',
  PATH_CLEARANCE_07: 'Path clearance', HAZARD_EXCLUSION_08: 'Hazard exclusion', HAZARD_SLOW_09: 'Hazard speed limit',
};
const unique = (values: string[]) => [...new Set(values)];
const shorten = (text: string, max: number) => text.length > max ? text.slice(0, max - 1) + '…' : text;
const verdict = (v: string) => VERDICTS[v] || v.replaceAll('_', ' ').toLowerCase();

export function KnowledgeGraph({ facts, missionTitle }: { facts: KnowledgeFact[]; missionTitle?: string }) {
  const container = useRef<HTMLDivElement>(null);
  const markerId = useId().replaceAll(':', '');
  const [compact, setCompact] = useState(false);
  const [mode, setMode] = useState<'overview' | 'decision'>('overview');
  const [filter, setFilter] = useState('all');
  const [eventId, setEventId] = useState(facts[0]?.event_id || '');
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setCompact(entry.contentRect.width < 580));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const visible = useMemo(() => facts.filter(f => filter === 'all' ||
    (filter === 'blocked' ? f.decision !== 'APPROVED' : f.decision === 'APPROVED')), [facts, filter]);
  const current = visible.find(f => f.event_id === eventId) || visible[0];
  const shown = mode === 'decision' && current ? [current] : visible;
  const policyIds = unique(shown.flatMap(f => f.policy_hits));
  const robots = unique(shown.map(f => f.robot_id));
  const locations = unique(shown.map(f => f.cell_id));
  const groups = mode === 'decision' && current
    ? [{ key: 'decision', label: verdict(current.decision), facts: [current] }]
    : unique(visible.map(f => f.decision)).map(key => ({ key, label: verdict(key), facts: visible.filter(f => f.decision === key) }));
  const nodes: GraphNode[] = [], edges: Edge[] = [];
  const add = (id: string, kind: string, label: string, detail: string, members: KnowledgeFact[],
               x: number, y: number, color: string, fill: string) => {
    nodes.push({ id, kind, label, detail, facts: members, x, y, w: compact ? 150 : 164, h: 76, color, fill });
  };
  if (shown.length) {
    add('mission', 'Mission', 'Assigned task', 'Operator instruction', shown,
      compact ? 16 : 20, compact ? 20 : 192, '#1e40af', '#eff6ff');
    add('robot', robots.length === 1 ? 'Robot' : 'Robots', robots.length === 1 ? robots[0] : `${robots.length} robots`, 'Performed this run', shown,
      compact ? 194 : 238, compact ? 20 : 34, '#6d28d9', '#f5f3ff');
    add('run', 'Mission run', 'Execution', `${shown.length} ${shown.length === 1 ? 'observation' : 'observations'}`, shown,
      compact ? 104 : 238, compact ? 150 : 192, '#0f766e', '#f0fdfa');
    edges.push({ from: 'mission', to: 'run', label: 'attempt' }, { from: 'robot', to: 'run', label: 'performed' });
    groups.forEach((group, i) => {
      const approved = group.facts.every(f => f.decision === 'APPROVED');
      const blocked = group.facts.some(f => f.decision === 'DENIED');
      const id = 'decision-' + group.key;
      add(id, mode === 'decision' ? 'Decision' : 'Decision group', group.label,
        mode === 'decision' ? `Receipt ${current.receipt_id}` : `${group.facts.length} observations`, group.facts,
        compact ? 16 : 476, compact ? 280 + i * 118 : 58 + (3 - groups.length) * 66 + i * 132,
        approved ? '#166534' : blocked ? '#b91c1c' : '#92400e', approved ? '#f0fdf4' : blocked ? '#fef2f2' : '#fffbeb');
      edges.push({ from: 'run', to: id, label: 'recorded' });
      edges.push({ from: id, to: 'location', label: 'at' });
      if (group.facts.some(f => f.policy_hits.length)) edges.push({ from: id, to: 'policy', label: 'triggered' });
    });
    add('location', mode === 'decision' ? 'Location' : 'Location group',
      mode === 'decision' ? `(${current.x.toFixed(1)}, ${current.y.toFixed(1)})` : `${locations.length} floor cells`,
      'Recorded positions', shown,
      compact ? 194 : 714, compact ? (policyIds.length ? 438 : 340) : 298, '#475569', '#f8fafc');
    if (policyIds.length) add('policy', policyIds.length === 1 ? 'Policy' : 'Policy group',
      policyIds.length === 1 ? (POLICY_NAMES[policyIds[0]] || policyIds[0]) : `${policyIds.length} policies`,
      'Checks triggered', shown.filter(f => f.policy_hits.length),
      compact ? 194 : 714, compact ? 280 : 90, '#9a3412', '#fff7ed');
  }
  const chosen = nodes.find(n => n.id === selected);
  const connected = new Set<string>(selected ? [selected] : nodes.map(n => n.id));
  edges.forEach(edge => { if (edge.from === selected || edge.to === selected) { connected.add(edge.from); connected.add(edge.to); } });
  const height = compact ? Math.max(478, ...nodes.map(n => n.y + n.h + 28)) : 480;

  function inspect(fact: KnowledgeFact) { setMode('decision'); setEventId(fact.event_id); setSelected('decision-decision'); setZoom(1); }
  function edgePath(edge: Edge) {
    const a = nodes.find(n => n.id === edge.from)!, b = nodes.find(n => n.id === edge.to)!;
    if (compact && edge.from === 'run') {
      return { d: `M ${a.x} ${a.y + 38} H 6 V ${b.y + 38} H ${b.x - 4}`, x: 38, y: b.y - 12 };
    }
    if ((compact && ['mission', 'robot'].includes(edge.from)) || (!compact && edge.from === 'robot')) {
      const sx = a.x + a.w / 2, sy = a.y + a.h, tx = b.x + b.w / 2, ty = b.y - 4;
      return { d: `M ${sx} ${sy} C ${sx} ${sy + 30}, ${tx} ${ty - 30}, ${tx} ${ty}`, x: (sx + tx) / 2, y: (sy + ty) / 2 };
    }
    const sx = a.x + a.w, sy = a.y + 38, tx = b.x - 4, ty = b.y + 38;
    const bend = Math.min(30, Math.max(8, (tx - sx) / 2));
    return { d: `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`, x: (sx + tx) / 2, y: (sy + ty) / 2 - 9 };
  }
  return <div className={styles.explorer}>
    <div className={styles.toolbar}>
      <div className={styles.modes} role="group" aria-label="Graph view">
        <button type="button" aria-pressed={mode === 'overview'} onClick={() => { setMode('overview'); setSelected(null); setZoom(1); }}>Mission overview</button>
        <button type="button" aria-pressed={mode === 'decision'} disabled={!visible.length} onClick={() => inspect(current)}>Inspect a decision</button>
      </div>
      <label>Show decisions<select aria-label="Graph decision filter" value={filter} onChange={e => { setFilter(e.target.value); setSelected(null); setZoom(1); }}>
        <option value="all">All decisions</option><option value="blocked">Blocked & review</option><option value="approved">Approved</option>
      </select></label>
    </div>
    {mode === 'decision' && visible.length > 0 && <label className={styles.decisionPicker}>Decision to inspect
      <select aria-label="Decision to inspect" value={current.event_id} onChange={e => { setEventId(e.target.value); setSelected('decision-decision'); }}>
        {visible.map(f => <option key={f.event_id} value={f.event_id}>{verdict(f.decision)} · {f.ts.slice(11, 19)} UTC · receipt {f.receipt_id} · ({f.x.toFixed(1)}, {f.y.toFixed(1)})</option>)}
      </select>
    </label>}
    <p className={styles.help}>{mode === 'overview' ? 'Follow the arrows from the mission to its recorded outcomes. Select any node to see what connects to it.' : 'One recorded decision, its robot, location and triggered policies. Select a node to inspect the evidence.'}</p>
    <div className={styles.viewport} ref={container} tabIndex={0} aria-label="Scrollable mission graph">
      {shown.length ? <svg className={styles.graph} viewBox={`0 0 ${compact ? 360 : 910} ${height}`}
        style={{ width: `${zoom * 100}%` }} role="group" aria-label="Interactive mission knowledge graph" data-layout={compact ? 'compact' : 'wide'}
        onKeyDown={e => { if (e.key === 'Escape') setSelected(null); }}>
        <title>Verified mission relationships</title>
        <desc>Mission and robot connect to an execution run. The run connects to recorded decisions, which connect to observed locations and any triggered policies. Nodes can be selected with a pointer or keyboard.</desc>
        <defs><marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" /></marker></defs>
        {edges.map(edge => {
          const path = edgePath(edge), active = !selected || edge.from === selected || edge.to === selected;
          return <g key={edge.from + edge.to} opacity={active ? 1 : .23} aria-hidden="true">
            <path data-edge-from={edge.from} data-edge-to={edge.to} d={path.d} fill="none" stroke={active && selected ? '#0f766e' : '#94a3b8'} strokeWidth={selected && active ? 2.5 : 1.6} markerEnd={`url(#${markerId})`} />
            {!(compact && edge.from.startsWith('decision-')) && <text x={path.x} y={path.y} textAnchor="middle" className={styles.edgeLabel}>{edge.label}</text>}
          </g>;
        })}
        {nodes.map(node => <g key={node.id} role="button" tabIndex={0} aria-pressed={selected === node.id}
          aria-label={`${node.kind}: ${node.label}. ${node.detail}`} data-node-kind={node.kind} data-node-id={node.id}
          className={styles.node} transform={`translate(${node.x},${node.y})`} opacity={connected.has(node.id) ? 1 : .35}
          onClick={() => setSelected(selected === node.id ? null : node.id)}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(selected === node.id ? null : node.id); } }}>
          <title>{node.kind}: {node.label} — {node.detail}</title>
          <rect width={node.w} height={node.h} rx="12" fill={node.fill} stroke={node.color} strokeWidth={selected === node.id ? 3 : 1.3} />
          <text x="12" y="19" fill={node.color} className={styles.kind}>{node.kind}</text>
          <text x="12" y="42" fill="#0f172a" className={styles.nodeTitle}>{shorten(node.label, compact ? 16 : 18)}</text>
          <text x="12" y="62" fill="#475569" className={styles.nodeDetail}>{shorten(node.detail, compact ? 18 : 20)}</text>
        </g>)}
      </svg> : <div className={styles.noMatch}><strong>No decisions match this filter.</strong><p>The displayed sample has no {filter === 'blocked' ? 'blocked or review' : 'approved'} decisions.</p><button onClick={() => setFilter('all')}>Show all decisions</button></div>}
    </div>
    <div className={styles.graphFooter}>
      <span>{shown.length} of {facts.length} retrieved observations · {mode === 'overview' ? 'Grouped for clarity' : 'One decision shown'} · Historical evidence</span>
      <div role="group" aria-label="Graph zoom"><button aria-label="Zoom out graph" disabled={zoom <= 1} onClick={() => setZoom(z => Math.max(1, z - .25))}>−</button><span>{Math.round(zoom * 100)}%</span><button aria-label="Zoom in graph" disabled={zoom >= 2} onClick={() => setZoom(z => Math.min(2, z + .25))}>+</button><button onClick={() => setZoom(1)}>Fit view</button></div>
    </div>
    {!policyIds.length && shown.length > 0 && <p className={styles.noPolicy}>No policy hits were recorded in these {shown.length === 1 ? 'selected observations' : 'displayed observations'}. Approved decisions still passed through the policy gate.</p>}
    <div className={styles.inspector} aria-live="polite" aria-atomic="false" data-testid="graph-inspector">
      {chosen ? <>
        <div className={styles.inspectorHeading}><div><span>{chosen.kind}</span><h3>{chosen.id === 'mission' ? missionTitle || 'Assigned mission' : chosen.label}</h3></div><button aria-label="Clear graph selection" onClick={() => setSelected(null)}>Clear selection</button></div>
        {chosen.id === 'mission' && <p>This mission is linked to the selected execution attempt. Mission ID: <code>{chosen.facts[0].mission_id}</code>.</p>}
        {chosen.id === 'run' && <p>Run <code>{chosen.facts[0].run_id}</code> connects {robots.join(', ')} to the {shown.length} displayed observations. Counts describe the retrieved sample.</p>}
        {chosen.id === 'robot' && <p>{robots.join(', ')} performed this mission run. Select a decision to inspect its recorded location and capability context.</p>}
        {chosen.id === 'policy' && <ul>{unique(chosen.facts.flatMap(f => f.policy_hits)).map(id => <li key={id}><strong>{POLICY_NAMES[id] || id}</strong> <code>{id}</code></li>)}</ul>}
        {chosen.id === 'location' && <p>{locations.length} distinct floor cells in the displayed sample. Each observation retains its site, map, policy and robot capability context.</p>}
        <div className={styles.evidenceList}>{chosen.facts.slice(0, mode === 'decision' ? 1 : 3).map(f => <div className={styles.evidence} key={f.event_id}>
          <div><strong>{verdict(f.decision)}</strong> · {f.robot_id} · ({f.x.toFixed(1)}, {f.y.toFixed(1)})<div className={styles.timestamp}>{f.ts.slice(0, 10)} · {f.ts.slice(11, 19)} UTC · receipt {f.receipt_id}</div></div>
          <code>{f.event_id}</code>
          {mode === 'decision' && <><p>{f.policy_hits.length ? f.policy_hits.map(id => POLICY_NAMES[id] || id).join(', ') : 'No policies triggered.'}</p>
            <details><summary>Source context and integrity</summary><dl>{Object.entries({ ...f.context, event_hash: f.event_hash }).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><code>{value}</code></dd></div>)}</dl></details></>}
          <div className={styles.evidenceActions}>{mode === 'overview' && <button onClick={() => inspect(f)}>Inspect this decision</button>}<Link href={`/runs/${f.run_id}`}>Open mission record ↗</Link></div>
        </div>)}</div>
        {mode === 'overview' && chosen.facts.length > 3 && <p className={styles.sampleNote}>Showing 3 of {chosen.facts.length} connected observations. Use “Inspect a decision” to browse the full retrieved sample.</p>}
      </> : <p><strong>Explore the mission.</strong> Select a node to highlight its connections and inspect the supporting records. Use Tab, then Enter or Space, to explore by keyboard.</p>}
    </div>
  </div>;
}
