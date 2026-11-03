"use client";
import Link from 'next/link';
import { capabilityGroups } from '@/lib/capabilityLinks';
import { Page, PageHeader, Panel } from '@/components/ui';
import { RuntimeCapabilities } from '@/components/RuntimeCapabilities';
export default function CapabilitiesPage() {
  return <Page><PageHeader title="What do you need to accomplish?" eyebrow="Capabilities & tools"
    subtitle="Find the right workflow across planning, execution, adaptation, memory and recovery. Existing specialist screens remain available." />
    <RuntimeCapabilities />
    <div className="grid md:grid-cols-2 gap-4">{capabilityGroups.map(group => <Panel key={group.title} title={group.title} subtitle={group.problem}>
      <ul className="space-y-3">{group.items.map(([title, description, href]) => <li key={title}><Link href={href} className="text-sm font-semibold text-mc-accent underline">{title} ↗</Link><p className="text-sm text-mc-mute mt-1">{description}</p></li>)}</ul>
    </Panel>)}</div>
    <div className="mt-4"><Panel title="How the platform cooperates" subtitle="Intelligence, execution state and memory have separate responsibilities.">
      <p className="text-sm text-mc-mute">Agentic planning proposes and revises. The autonomy runtime maintains mission state, budgets, permits and recovery. NetworkX calculates routes. Signed memory determines eligible experience. Optional Memgraph connects historical evidence for retrieval and investigation. Operators and independent governance control consequential actions.</p>
      <div className="flex flex-wrap gap-4 text-sm mt-3"><Link className="text-mc-accent underline" href="/authority#knowledge-graph">Explore the knowledge graph ↗</Link><Link className="text-mc-accent underline" href="/how-it-works">Read the capability guide ↗</Link></div>
      <p className="text-xs text-mc-mute mt-3">Current demonstration: simulated navigation, stop and wait. No physical manipulation, general fleet scheduler, external ACE/Agentic Kernel integration or hardware safety certification.</p>
    </Panel></div>
  </Page>;
}
