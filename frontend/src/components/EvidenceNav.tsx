"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/components/ui";

const ITEMS = [
  { href: "/evidence", label: "Benchmarks & receipts" },
  { href: "/compliance", label: "Compliance reports" },
  { href: "/audit", label: "Audit trail" },
];

/** Sub-navigation shared by the Evidence, Compliance and Audit pages. */
export function EvidenceNav() {
  const p = usePathname() || "";
  return (
    <div className="flex items-center gap-1 border-b border-mc-line mb-6 overflow-x-auto mc-scroll">
      {ITEMS.map((i) => (
        <Link key={i.href} href={i.href}
          className={cx("px-3 py-2 text-[13px] font-medium whitespace-nowrap border-b-2 -mb-px",
            p.startsWith(i.href) ? "border-mc-accent text-mc-ink" : "border-transparent text-mc-dim hover:text-mc-mute")}>
          {i.label}
        </Link>
      ))}
    </div>
  );
}
