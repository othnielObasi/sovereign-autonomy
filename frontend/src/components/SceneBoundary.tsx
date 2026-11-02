"use client";
import React from "react";

/** Keep mission controls available when WebGL or an optional asset fails. */
export class SceneBoundary extends React.Component<React.PropsWithChildren, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div role="status" className="h-full flex flex-col items-center justify-center gap-3 p-6 text-slate-300 text-sm">
      <p>3D view unavailable. Mission and stop controls remain available.</p>
      <a href="/" className="underline text-cyan-300">Open the 2D dashboard</a>
    </div>;
    return this.props.children;
  }
}
