'use client'

import { useTranslation } from 'react-i18next'
import ProviderIcon from './ProviderIcon'
import { publicResolvedModel } from '@/lib/resolved-model'

export function ResolvedModelBadge({ value, className = '', showUnknown = true }: { value: unknown; className?: string; showUnknown?: boolean }) {
  const { t } = useTranslation()
  const model = publicResolvedModel(value)
  if (!model) return showUnknown ? <span className={`text-[11px] text-[var(--muted-foreground)] ${className}`}>{t('Model not recorded', { defaultValue: "Model not recorded" })}</span> : null
  const label = [model.provider_label || model.provider, model.model_name || model.model].filter(Boolean).join(' · ')
  return <span title={label} className={`inline-flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)] ${className}`}><ProviderIcon provider={model.provider} size={12} /><span className="truncate">{label}</span></span>
}
