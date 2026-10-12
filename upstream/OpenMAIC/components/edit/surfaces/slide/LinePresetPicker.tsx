'use client';

import { LINE_LIST, type LinePoolItem } from '@/configs/lines';

interface LinePresetPickerProps {
  readonly onPick: (preset: LinePoolItem) => void;
}

function getPresetLabel(preset: LinePoolItem) {
  if (preset.isCubic) return 'Cubic curve';
  if (preset.isCurve) return 'Curve';
  if (preset.isBroken2) return 'Double elbow line';
  if (preset.isBroken) return 'Elbow line';
  if (preset.points[1] === 'arrow') return 'Arrow line';
  if (preset.points[1] === 'dot') return 'Dot-ended line';
  return preset.style === 'dashed' ? 'Dashed line' : 'Straight line';
}

/** Renderer-editor insert palette for the existing DSL line presets. */
export function LinePresetPicker({ onPick }: LinePresetPickerProps) {
  return (
    <div className="grid grid-cols-5 gap-2" role="group" aria-label="Line presets">
      {LINE_LIST.flatMap((group) => group.children).map((preset, index) => {
        const label = getPresetLabel(preset);
        return (
          <button
            key={`${preset.path}-${index}`}
            type="button"
            aria-label={label}
            className="flex aspect-square items-center justify-center rounded-md border border-transparent p-2 text-zinc-600 hover:border-violet-300 hover:bg-violet-50 hover:text-violet-700 dark:text-zinc-300 dark:hover:border-violet-500/50 dark:hover:bg-violet-500/10"
            onClick={() => onPick(preset)}
          >
            <svg viewBox="0 0 20 20" className="h-7 w-7" aria-hidden="true">
              <path
                d={preset.path}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeDasharray={preset.style === 'dashed' ? '5 2.5' : undefined}
              />
            </svg>
          </button>
        );
      })}
    </div>
  );
}
