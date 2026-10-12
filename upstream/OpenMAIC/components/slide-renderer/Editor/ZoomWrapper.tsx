'use client';

import { motion } from 'motion/react';
import type { ReactNode } from 'react';
import type { PercentageGeometry } from '@/lib/types/action';

interface ZoomWrapperProps {
  children: ReactNode;
  zoomTarget: { elementId: string; scale: number } | null;
  geometry: PercentageGeometry | null;
}

/**
 * Zoom wrapper component
 *
 * Features:
 * - Wraps the canvas and scales according to zoomTarget
 * - Uses the element center as the scaling origin
 * - Uses percentage-based coordinates
 */
export function ZoomWrapper({ children, zoomTarget, geometry }: ZoomWrapperProps) {
  if (!zoomTarget || !geometry) {
    return <>{children}</>;
  }

  const { scale } = zoomTarget;
  const { centerX, centerY } = geometry;

  return (
    <motion.div
      className="w-full h-full"
      initial={{ scale: 1 }}
      animate={{ scale }}
      exit={{ scale: 1 }}
      transition={{
        type: 'spring',
        stiffness: 200,
        damping: 25,
      }}
      style={{
        transformOrigin: `${centerX}% ${centerY}%`,
      }}
    >
      {children}
    </motion.div>
  );
}
