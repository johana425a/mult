import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useLLMOptions } from '../hooks/useLLMOptions'
import { invalidateLLMOptionsCache, type LLMOptionsResponse } from '../lib/llm-options'

const catalog = (model: string): LLMOptionsResponse => ({ active: { profile_id: model, model_id: model }, options: [{ profile_id: model, model_id: model, profile_name: model, model_name: model, model, provider: model === 'qwen' ? 'llama_cpp' : 'openai', is_active_default: true }] })
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }

describe('model configuration invalidation', () => {
  it('refreshes mounted catalog consumers after a committed configuration change', async () => {
    let calls = 0
    const loader = async () => catalog(++calls === 1 ? 'qwen' : 'deepseek')
    const { result } = renderHook(() => useLLMOptions(loader))
    await waitFor(() => expect(result.current.activeDefault?.model_id).toBe('qwen'))
    act(() => invalidateLLMOptionsCache())
    await waitFor(() => expect(result.current.activeDefault?.model_id).toBe('deepseek'))
    expect(calls).toBe(2)
  })
  it('rejects a stale pre-apply catalog that completes after the updated one', async () => {
    const old = deferred<LLMOptionsResponse>()
    const next = deferred<LLMOptionsResponse>()
    let calls = 0
    const loader = () => (++calls === 1 ? old.promise : next.promise)
    const { result } = renderHook(() => useLLMOptions(loader))
    act(() => invalidateLLMOptionsCache())
    await act(async () => next.resolve(catalog('deepseek')))
    expect(result.current.activeDefault?.model_id).toBe('deepseek')
    await act(async () => old.resolve(catalog('qwen')))
    expect(result.current.activeDefault?.model_id).toBe('deepseek')
    expect(calls).toBe(2)
  })
})
