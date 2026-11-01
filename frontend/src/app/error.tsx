"use client";

import React from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="max-w-xl mx-auto px-4 py-24 text-center">
      <div className="text-6xl mb-4">⚠️</div>
      <h1 className="text-3xl font-bold mb-2">Something went wrong</h1>
      <p className="text-mc-mute mb-8">{error.message || "An unexpected error occurred."}</p>
      <button
        onClick={reset}
        className="bg-cyan-500 hover:bg-cyan-600 text-white font-semibold px-6 py-3 rounded-lg transition"
      >
        Try Again
      </button>
    </div>
  );
}
