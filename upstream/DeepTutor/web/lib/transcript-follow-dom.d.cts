/** Stable DOM transcript following shared with the standalone repair. */
export function visibleListViewport(list: HTMLElement): { offset: number; height: number };
export function followTranscriptRow(list: HTMLElement | null): boolean;
export function observeTranscriptFollow(list: HTMLElement | null): () => void;
