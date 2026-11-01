"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";

/** Sample sustained frame time; background-tab pauses are not GPU load. */
export function FrameBudget({ onSample }: { onSample: (fps: number) => void }) {
  const sample = useRef({ seconds: 0, frames: 0 });
  useFrame((_, dt) => {
    if (document.hidden || dt > 2) { sample.current = { seconds: 0, frames: 0 }; return; }
    sample.current.seconds += dt;
    sample.current.frames++;
    if (sample.current.seconds >= 3) {
      onSample(Math.round(sample.current.frames / sample.current.seconds));
      sample.current = { seconds: 0, frames: 0 };
    }
  });
  return null;
}
