"use client";

import { LazyMotion, MotionConfig } from "framer-motion";
import type { ReactNode } from "react";

const loadFeatures = () => import("./motion-features").then((mod) => mod.default);

export default function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }}>
      <LazyMotion features={loadFeatures} strict>{children}</LazyMotion>
    </MotionConfig>
  );
}
