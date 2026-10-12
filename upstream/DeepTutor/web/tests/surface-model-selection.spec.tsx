import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useSurfaceModelSelection } from '../hooks/useSurfaceModelSelection'

const first = { profile_id: 'provider-a', model_id: 'model-a' }
const second = { profile_id: 'provider-b', model_id: 'model-b' }

describe('surface model preferences', () => {
  beforeEach(() => localStorage.clear())
  it('saves a choice immediately and restores null as inherit, not an old explicit model', () => {
    const hook = renderHook(() => useSurfaceModelSelection('classroom-fixture'))
    act(() => hook.result.current[1](first))
    expect(JSON.parse(localStorage.getItem('deepsteam:model-choice:classroom-fixture')!)).toEqual(first)
    hook.unmount()
    const reopened = renderHook(() => useSurfaceModelSelection('classroom-fixture', second))
    expect(reopened.result.current[0]).toEqual(first)
    act(() => reopened.result.current[1](null))
    reopened.unmount()
    const inherited = renderHook(() => useSurfaceModelSelection('classroom-fixture', second))
    expect(inherited.result.current[0]).toBeNull()
  })
  it('keeps workspace sessions independent and restores server choice only without a local draft', () => {
    const hook = renderHook(({ id, saved }) => useSurfaceModelSelection(`workspace:${id}`, saved), { initialProps: { id: 'session-a', saved: first } })
    expect(hook.result.current[0]).toEqual(first)
    act(() => hook.result.current[1](second))
    hook.rerender({ id: 'session-b', saved: first })
    expect(hook.result.current[0]).toEqual(first)
    hook.rerender({ id: 'session-a', saved: first })
    expect(hook.result.current[0]).toEqual(second)
  })
})
