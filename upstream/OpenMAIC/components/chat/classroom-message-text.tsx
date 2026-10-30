'use client';

import type { ReactNode } from 'react';

/** Keep ordinary teaching text unchanged; expose only verified delivery routes. */
export function ClassroomMessageText({ text }: { readonly text: string }) {
  const parts: ReactNode[] = [];
  const links = /\[([^\]\r\n]+)\]\((https?:\/\/[^\s)]+|\/api\/[^\s)]+)\)/g;
  let cursor = 0;
  for (const match of text.matchAll(links)) {
    const href = match[2];
    let url: URL;
    try {
      url = new URL(href, 'https://relative.invalid');
    } catch {
      continue;
    }
    if (
      !['http:', 'https:'].includes(url.protocol) ||
      !/^\/api\/harness\/sessions\/[^/]+\/deliverables\/\d+\/files\/\d+$/.test(url.pathname)
    ) continue;
    parts.push(text.slice(cursor, match.index));
    parts.push(
      <a
        key={match.index}
        href={href}
        download={match[1]}
        referrerPolicy="no-referrer"
        className="underline underline-offset-2 break-all"
        onClick={(event) => event.stopPropagation()}
      >
        {match[1]}
      </a>,
    );
    cursor = match.index! + match[0].length;
  }
  parts.push(text.slice(cursor));
  return <>{parts}</>;
}
