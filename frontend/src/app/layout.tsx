import React from "react";
import Link from "next/link";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { NavLinks, StatusPill } from "@/components/NavLinks";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata = {
  title: "Sovereign Autonomy",
  description: "Sovereign Autonomy — every robot move, proven safe before it happens. NVIDIA Nemotron proposes; a governance gate decides.",
};

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 shrink-0" aria-label="Sovereign Autonomy home">
      <span className="relative w-8 h-8 rounded-lg bg-mc-raise border border-mc-accent/40 flex items-center justify-center">
        {/* gate mark: a path through a checkpoint */}
        <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="#22d3ee" strokeWidth={2} strokeLinecap="round">
          <path d="M3 17h5l3-10 3 10h7" />
          <path d="M11 4v3M13 4v3" stroke="#22c55e" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-tight text-mc-ink">Sovereign Autonomy</span>
        <span className="block text-[10px] uppercase tracking-[0.16em] text-mc-dim">Runtime governance</span>
      </span>
    </Link>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="bg-mc-bg text-mc-ink min-h-screen font-sans">
        <nav className="border-b border-mc-line bg-mc-bg/85 backdrop-blur-md sticky top-0 z-50">
          <div className="max-w-[1600px] mx-auto px-4 sm:px-6 h-14 flex items-center justify-between relative">
            <div className="flex items-center min-w-0">
              <Logo />
              <NavLinks />
            </div>
            <div className="flex items-center gap-3">
              <StatusPill />
              <Link href="/twin"
                className="hidden sm:inline-flex items-center gap-2 rounded-lg bg-mc-accent text-mc-bg px-3 py-1.5 text-[13px] font-semibold hover:bg-cyan-300">
                <span className="w-1.5 h-1.5 rounded-full bg-mc-bg animate-live-dot" />
                Live warehouse
              </Link>
            </div>
          </div>
        </nav>

        <main>{children}</main>

        <footer className="border-t border-mc-line mt-10">
          <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-5 flex flex-col sm:flex-row gap-2 justify-between text-xs text-mc-dim">
            <span>Sovereign Autonomy · NOVTIA · MIT licensed</span>
            <span>
              Planning by <span className="text-mc-nv">NVIDIA Nemotron</span> on Nebius Token Factory · hosted on Nebius AI Cloud
            </span>
          </div>
        </footer>
      </body>
    </html>
  );
}
