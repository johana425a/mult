import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ResolvedModelBadge } from '../components/common/ResolvedModelBadge'
import { messageResolvedModel, publicResolvedModel } from '../lib/resolved-model'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const model = { provider: 'deepseek', provider_label: 'DeepSeek', model: 'deepseek-flash', model_name: 'DeepSeek Flash', selection_source: 'override', context_window: 1_000_000 }

describe('historical resolved model identity', () => {
  it('keeps only public fields and never displays credentials or route aliases', () => {
    const safe = publicResolvedModel({ ...model, api_key: 'fixture-only-secret', token: 'fixture-only-token', base_url: 'private-transport' })
    expect(JSON.stringify(safe)).not.toMatch(/secret|token|transport/)
    expect(publicResolvedModel({ ...model, model: 'dsroute_private', model_name: 'dsroute_private' })).toBeNull()
    expect(publicResolvedModel({ ...model, model: 'DsExec_private', model_name: 'Safe-looking label' })).toBeNull()
    expect(publicResolvedModel({ ...model, model_name: 'DSEXEC_private' })).toBeNull()
    const { container } = render(<ResolvedModelBadge value={safe} />)
    expect(container.textContent).toBe('DeepSeek · DeepSeek Flash')
  })
  it('uses a persisted reply snapshot ahead of trace events, and leaves old history unknown', () => {
    const snapshot = { ...model, model: 'previous-model', model_name: 'Previous model' }
    expect(messageResolvedModel({ resolvedModel: snapshot, events: [{ metadata: { resolved_model: model } }] })?.model).toBe('previous-model')
    expect(messageResolvedModel({ events: [{ metadata: { model: 'not-verified' } }] })).toBeNull()
    render(<ResolvedModelBadge value={null} />)
    expect(screen.getByText('Model not recorded')).toBeTruthy()
  })
  it('reads the frozen model from a streamed turn without consulting the global default', () => {
    expect(messageResolvedModel({ events: [{ metadata: {} }, { metadata: { resolved_model: model } }] })?.context_window).toBe(1_000_000)
  })
})
