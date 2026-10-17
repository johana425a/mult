import type * as React from 'react';
export function read<T>(key: string): T | undefined;
export function has(key: string): boolean;
export function clear(): void;
export function useRetained<T>(react: typeof React, key: string, initial: T): [T, React.Dispatch<React.SetStateAction<T>>];
