'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useI18n } from '@/lib/hooks/use-i18n';
import { deepSteamWorkspaceHref } from '@/lib/workbench/deepsteam-desktop-return';

/** The full-window classroom must have a visible route back to its desktop host. */
export function DeepSteamWorkspaceLink() {
  const { t } = useI18n();
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => {
    setHref(deepSteamWorkspaceHref(window.location, window.top === window.self));
  }, []);
  if (!href) return null;
  return <a href={href} className="mx-4 mb-3 inline-flex items-center gap-1.5 text-xs underline underline-offset-2">
    <ArrowLeft className="size-3.5" aria-hidden="true" />
    {t('stage.returnToDeepSteam')}
  </a>;
}
