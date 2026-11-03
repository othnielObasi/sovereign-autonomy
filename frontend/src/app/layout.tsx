import React from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "./control.css";
import { AppShell } from "@/components/AppShell";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });
export const metadata = {
  title: "Sovereign Autonomy | Mission Control",
  description: "One place to follow autonomous missions, verify every permission, and keep people in control.",
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en" className={`${sans.variable} ${mono.variable}`}><body><AppShell>{children}</AppShell></body></html>;
}
