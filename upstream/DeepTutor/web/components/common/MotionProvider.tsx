"use client";

import { LazyMotion, MotionConfig } from "framer-motion";
import type { ReactNode } from "react";

const loadFeatures = () => import("./motion-features").then((mod) => mod.default);

export default function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.28, ease: [0.32, 0.72, 0, 1] }}>
      <LazyMotion features={loadFeatures} strict>{children}</LazyMotion>
    </MotionConfig>
  );
}
