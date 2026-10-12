'use client'

/** Original DeepSteam addon. Credentials stay in the local bridge, and every
 * success indicator comes from a completed tool result rather than LLM prose. */
import Link from 'next/link'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Check, ExternalLink, KeyRound, Loader2, LogIn, RefreshCw, Unplug, X } from 'lucide-react'
import { FeaturePage, PageHeader, pageActionClass } from '@/components/layout/FeaturePage'
import { invalidateLLMOptionsCache } from '@/lib/llm-options'
import { deepsteamService, deepsteamRequest } from '@/lib/deepsteam-api'
import { safeServiceError } from '@/lib/deepsteam-transport'
import type { ModelConnection } from '@/lib/model-connection'
import { ConnectionSummary } from './ConnectionSummary'
import { UnifiedModelControl } from '@/components/common/UnifiedModelControl'
import { setGlobalDefaultModel } from '@/lib/resolved-model'

const API = `${deepsteamService(3791)}/api/harness`
const panel = 'rounded-xl border border-[var(--border)] bg-[var(--card)] p-5'
const input = 'w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-sm outline-none placeholder:text-[var(--muted-foreground)] focus:border-[var(--ring)] focus:ring-1 focus:ring-[var(--ring)] disabled:opacity-60'
const primary = pageActionClass('primary')
const secondary = pageActionClass('secondary')
type Operation = { id: string; revision: number; status: string; mode?: string; model?: string; credential_set?: boolean; probe?: { ok: boolean; code?: string; vision?: boolean } | null; error_code?: string; applied_targets?: string[] }
type Current = { model: string; route_id: string; targets: string[] }
type Status = { available: boolean; account: { authenticated: boolean; balance_status?: string; error_code?: string }; operation: Operation | null; current: Current | null }
type Model = { id: string; label: string; vision?: boolean }
type Result = { operation: Operation; current?: Current | null; authorization_url?: string; expires_at?: string }
type Intent = { sequence: number; mode: 'account' | 'api'; model: string; operationId: string | null; phase: 'starting' | 'waiting' | 'probing' | 'applying' }
const errors: Record<string, string> = {
  unauthorized: 'Your sign-in or API key has expired. Sign in again or update the key.', credential_invalid: 'Your sign-in or API key has expired. Sign in again or update the key.', invalid_key: 'The API key could not be verified. Update it and try again.', insufficient_balance: 'Insufficient account credits. Check your balance or add credits on the official platform.', balance_query_failed: 'The balance could not be retrieved. Available credits are currently unknown.', timeout: 'The connection timed out. Check your network and reconnect.', cancelled: 'This connection attempt was cancelled.', stale_revision: 'The connection state changed. Refresh before continuing.', unavailable: 'The configuration service is unavailable. Make sure the desktop application is running.', rollback_failed: 'Settings restoration did not finish. Check the current settings first.', probe_required: 'Reconnect to verify the model automatically.', invalid_credentials: 'The API key could not be verified. Update it and try again.', account_not_authenticated: 'Sign in again to DeepSeek,  complete official authorization.', quota_exceeded: 'Insufficient account credits. Check your account on the official platform.', authorization_expired: 'Authorization expired. Sign in again to DeepSeek.', authorization_timed_out: 'Official authorization timed out. Sign in again.', authorization_interrupted: 'Authorization was interrupted. Sign in again to DeepSeek.',
}
const labels: Record<string, string> = { awaiting_authorization: 'Waiting for authorization on the official page', authorizing: 'Waiting for official authorization', awaiting_credential: 'Waiting for an API key', awaiting_model: 'Connection saved; model verification pending', credential_invalid: 'Invalid credentials; update them and retry', probe_failed: 'Connection verification failed', apply_failed: 'Activation did not finish; previous settings were preserved', rollback_required: 'Settings need recovery. Select Restore previous settings', rolling_back: 'Restoring previous settings', awaiting_auth: 'Waiting for authorization on the official page', awaiting_login: 'Waiting for authorization on the official page', authorized: 'Signed in; model verification pending', credential_ready: 'API key saved; model verification pending', ready: 'Waiting for model verification', verifying: 'Verifying the model', probing: 'Verifying the model', validated: 'Verification passed; ready to enable', verified: 'Verification passed; ready to enable', applying: 'Enabling connection', applied: 'Connection enabled', cancelled: 'Connection cancelled', failed: 'Connection did not finish', invalid: 'Invalid credentials', rolled_back: 'Previous settings restored' }
const safeText = (text: string) => safeServiceError(text).replace(/\bsk-[A-Za-z0-9_-]+/g, '[API key redacted]').replace(/Bearer\s+[^\s]+/gi, 'Bearer [redacted]').slice(0, 3000)
const message = (code?: string) => code ? (errors[code] || 'Connection did not finish. Check your sign-in, model and network.') : ''

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(API + path, { cache: 'no-store', signal: AbortSignal.timeout(90000), ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  const value = await response.json().catch(() => ({}))
  if (!response.ok) {
    const code = value.code || value.error_code || (typeof value.detail === 'object' ? value.detail?.code : undefined)
    throw new Error(message(code) || `Operation did not finish (${response.status}), Refresh and try again.`)
  }
  return value as T
}

export function HarnessConnect() {
  const [status, setStatus] = useState<Status | null>(null)
  const [connection, setConnection] = useState<ModelConnection | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [model, setModel] = useState('')
  const [mode, setMode] = useState<'account' | 'api'>('account')
  const [apiKey, setApiKey] = useState('')
  const [authorization, setAuthorization] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const alive = useRef(true)
  const actionSequence = useRef(0)
  const seenCurrent = useRef<string | null | undefined>(undefined)
  const keyRef = useRef<HTMLInputElement>(null)
  const latest = useRef<Status | null>(null)
  const selectedModel = useRef('')
  const modelEdited = useRef(false)
  const flow = useRef<Intent | null>(null)
  const stateEpoch = useRef(0)
  const refreshing = useRef(false)
  const advance = useRef<(value: Status) => void>(() => {})
  const actionPending = useRef(false)
  const operation = status?.operation
  const identity = operation ? { operation_id: operation.id, revision: operation.revision } : {}
  const canCancel = Boolean(flow.current) && flow.current?.phase !== 'applying'
  const canRollback = ['applied', 'rollback_required'].includes(operation?.status || '')
  const applied = status?.current

  const refresh = useCallback(async () => {
    if (refreshing.current) return
    refreshing.current = true
    const epoch = stateEpoch.current
    try {
      const [next, currentConnection] = await Promise.all([request<Status>('/status'), deepsteamRequest<ModelConnection>('/models/connection')])
      if (alive.current && epoch === stateEpoch.current) {
        const previous = latest.current?.operation
        if (previous?.id === next.operation?.id && previous && next.operation && previous.revision > next.operation.revision) return
        const route = next.current?.route_id ?? null
        if (seenCurrent.current !== undefined && seenCurrent.current !== route) invalidateLLMOptionsCache()
        seenCurrent.current = route
        setStatus(next)
        latest.current = next
        setConnection(currentConnection)
        if (!flow.current && !modelEdited.current && next.current?.model) { selectedModel.current = next.current.model; setModel(next.current.model) }
        advance.current(next)
      }
    } catch {
      if (alive.current && epoch === stateEpoch.current) setError('The local configuration service is unavailable. Make sure DeepSteam is running, then refresh.')
    } finally { refreshing.current = false }
  }, [])
  const loadModels = useCallback(async () => {
    try {
      const result = await request<{ models: Model[] }>('/models')
      if (alive.current) {
        const next = result.models || []
        setModels(next)
        if (next.length && !flow.current && !latest.current?.current && !modelEdited.current) {
          const preferred = next.find(item => item.id === 'deepseek-flash') || next[0]
          selectedModel.current = preferred.id; setModel(preferred.id)
        }
      }
    } catch { if (alive.current) setError('Could not load the model list. Refresh the status and reconnect.') }
  }, [])
  useEffect(() => {
    alive.current = true
    void refresh()
    void loadModels()
    let lastPoll = 0
    const interval = setInterval(() => { if (flow.current || Date.now() - lastPoll >= 3000) { lastPoll = Date.now(); void refresh() } }, 1000)
    return () => {
      const abandoned = flow.current
      alive.current = false; flow.current = null; ++actionSequence.current; clearInterval(interval)
      if (abandoned?.operationId && abandoned.phase !== 'applying') void cancelOperation(abandoned.operationId)
    }
  }, [refresh, loadModels])
  useEffect(() => { if (status?.account.authenticated) void loadModels() }, [status?.account.authenticated, loadModels])

  const accept = (result: Result) => {
    if (!alive.current) return
    const previous = latest.current || { available: true, account: { authenticated: false }, operation: null, current: null }
    if (previous.operation?.id === result.operation.id && previous.operation.revision > result.operation.revision) return
    ++stateEpoch.current
    const next = { ...previous, operation: result.operation, current: Object.hasOwn(result, 'current') ? (result.current ?? null) : previous.current }
    latest.current = next; setStatus(next)
  }
  const act = async (name: string, action: () => Promise<void>) => {
    if (actionPending.current || flow.current) return
    actionPending.current = true
    const sequence = ++actionSequence.current
    setBusy(name); setError('')
    try { await action(); if (sequence === actionSequence.current) await refresh() } catch (failure) { if (alive.current && sequence === actionSequence.current) setError(failure instanceof Error ? safeText(failure.message) : 'The operation did not finish. Try again.') }
    finally { actionPending.current = false; if (alive.current && sequence === actionSequence.current) setBusy(null) }
  }
  const isActive = (intent: Intent) => alive.current && flow.current === intent && intent.sequence === actionSequence.current
  const finish = (intent: Intent, failure?: string) => {
    if (!isActive(intent)) return
    flow.current = null; actionPending.current = false; setBusy(null); setAuthorization('')
    setProgress('')
    if (failure) setError(safeText(failure))
  }
  // A poll is allowed to advance only the operation explicitly started here.
  // Claim the phase before awaiting, so repeated status responses cannot probe twice.
  const verifyAndEnable = async (intent: Intent, ready: Operation) => {
    if (!isActive(intent) || intent.operationId !== ready.id || intent.phase !== 'waiting') return
    intent.phase = 'probing'; setBusy('probe'); setAuthorization(''); setProgress('Verifying the model connection...')
    try {
      const verified = await request<Result>('/probe', { operation_id: ready.id, revision: ready.revision, model: intent.model })
      if (!isActive(intent)) return
      accept(verified)
      if (verified.operation.id !== intent.operationId || verified.operation.model !== intent.model || verified.operation.status !== 'verified' || verified.operation.probe?.ok !== true) {
        finish(intent, message(verified.operation.error_code || verified.operation.probe?.code) || 'Connection verification failed; previous settings were preserved.')
        return
      }
      intent.phase = 'applying'; setBusy('apply'); setProgress('Verification passed. Connecting learning and classrooms automatically...')
      const enabled = await request<Result>('/apply', { operation_id: verified.operation.id, revision: verified.operation.revision, confirm: true, targets: ['learning', 'classroom'] })
      if (!isActive(intent)) return
      accept(enabled)
      if (enabled.operation.id !== intent.operationId || enabled.operation.status !== 'applied' || enabled.current?.model !== intent.model || !['learning', 'classroom'].every(target => enabled.current?.targets.includes(target))) {
        finish(intent, message(enabled.operation.error_code) || 'Automatic configuration did not finish. Check the connection or restore previous settings.')
        return
      }
      seenCurrent.current = enabled.current.route_id
      invalidateLLMOptionsCache(); finish(intent); void refresh()
    } catch (failure) {
      finish(intent, failure instanceof Error ? failure.message : 'Connection did not finish. Reconnect to try again.')
    }
  }
  advance.current = (value: Status) => {
    const intent = flow.current
    if (!intent || !isActive(intent) || intent.phase !== 'waiting' || value.operation?.id !== intent.operationId) return
    const candidate = value.operation
    if (candidate.status === 'awaiting_model' && candidate.credential_set) void verifyAndEnable(intent, candidate)
    else if (['failed', 'cancelled', 'credential_invalid', 'probe_failed', 'apply_failed', 'rollback_required', 'rolled_back'].includes(candidate.status)) {
      finish(intent, message(candidate.error_code) || labels[candidate.status] || 'Connection did not finish. Reconnect to try again.')
    }
  }
  // Cancel only the matching operation, using a fresh revision. A late response
  // may never cancel a newer connection started in another tab or after a retry.
  async function cancelOperation(id: string) {
    try {
      const value = await request<Status>('/status')
      const op = value.operation
      if (op?.id === id && !['applied', 'applying', 'rolling_back', 'cancelled', 'rolled_back'].includes(op.status)) {
        return await request<Result>('/account/cancel', { operation_id: id, revision: op.revision })
      }
    } catch { /* Local intent is already invalidated; late completion cannot apply. */ }
  }
  const connect = async (kind: 'account' | 'api' | 'reuse', key?: string) => {
    if (actionPending.current || flow.current || !selectedModel.current) return
    actionPending.current = true; ++stateEpoch.current
    const intent: Intent = { sequence: ++actionSequence.current, mode: kind === 'api' ? 'api' : 'account', model: selectedModel.current, operationId: null, phase: 'starting' }
    flow.current = intent
    setError(''); setAuthorization(''); setBusy('login')
    setProgress(kind === 'account' ? 'Opening the DeepSeek official sign-in...' : kind === 'api' ? 'Saving and connecting the API key...' : 'Switching models...')
    // Reserve the browser tab during the click gesture; opening only after the
    // local service responds would be blocked by common browser popup policies.
    // Desktop uses its native external-browser bridge instead.
    let popup: Window | null = null
    try {
      if (kind === 'account' && !window.deepsteamDesktop?.openOfficial) {
        popup = window.open('about:blank', '_blank')
        if (popup) popup.opener = null
      }
      const result = kind === 'account' ? await request<Result>('/account/start', {})
        : kind === 'api' ? await request<Result>('/credential', { api_key: key, model: intent.model })
          : await request<Result>('/connect', { model: intent.model })
      intent.operationId = result.operation.id
      if (!isActive(intent)) { popup?.close(); await cancelOperation(result.operation.id); return }
      accept(result)
      intent.phase = 'waiting'
      if (kind === 'account') {
        const url = new URL(result.authorization_url || '')
        if (url.protocol !== 'https:' || url.hostname !== 'platform.deepseek.com' || url.pathname !== '/dsh/authorize' || url.username || url.password || (url.port && url.port !== '443') || url.hash) throw new Error('The official authorization URL could not be verified. Reconnect.')
        setProgress('Complete official sign-in. Verification and activation will run automatically when you return.')
        let opened = false
        if (window.deepsteamDesktop?.openOfficial) opened = await window.deepsteamDesktop.openOfficial(url.href).catch(() => false)
        else if (popup && !popup.closed) { popup.location.replace(url.href); opened = true }
        if (!isActive(intent)) return
        if (!opened && intent.phase === 'waiting') setAuthorization(url.href)
      }
      const next = latest.current
      if (next) advance.current(next)
    } catch (failure) {
      popup?.close()
      if (isActive(intent)) {
        if (intent.operationId) void cancelOperation(intent.operationId)
        finish(intent, failure instanceof Error ? failure.message : 'Connection did not finish. Try again.')
      }
    } finally {
      // A cancel during the initial request keeps the button locked until that
      // request settles, avoiding overlapping authorization attempts.
      if (!flow.current && alive.current) { actionPending.current = false; setBusy(null) }
    }
  }
  const saveKey = (event: FormEvent) => {
    event.preventDefault()
    if (!apiKey.trim()) return
    const submitted = apiKey.trim()
    setApiKey('')
    void connect('api', submitted)
  }
  const cancel = async () => {
    const intent = flow.current
    if (!intent || intent.phase === 'applying') return
    flow.current = null; ++actionSequence.current; ++stateEpoch.current
    setAuthorization(''); setApiKey(''); setProgress(''); setError(''); setBusy('cancel')
    if (!intent.operationId) return
    const result = await cancelOperation(intent.operationId)
    if (alive.current && !flow.current) {
      if (result) accept(result)
      actionPending.current = false; setBusy(null); setProgress('This connection attempt was cancelled.')
    }
  }
  const choices = model && !models.some(item => item.id === model) ? [{ id: model, label: model }, ...models] : models
  const running = Boolean(busy)
  const operationError = operation?.error_code ? message(operation.error_code) : ''

  return <FeaturePage>
    <PageHeader title="Connect a model" description="Choose the global default model, sign in to DeepSeek or add your own API endpoint. Conversations and generation tasks can still select a separate model." action={<>
      <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => { void refresh(); void loadModels() }}><RefreshCw size={14} />Refresh status</button>
      <Link href="/settings" className={secondary}>Other model settings</Link>
    </>} />
    {error && <div role="alert" className="mb-4 rounded-lg border border-[var(--destructive)]/30 bg-[var(--destructive)]/5 px-4 py-3 text-sm">{error}</div>}
    <div className="mb-5"><ConnectionSummary connection={connection} /></div>
    <section className={`${panel} mb-5`} aria-label="Global default model"><UnifiedModelControl value={null} surface="chat" placement="bottom" label="Global default model" disabled={running} onChange={selection => {
      if (!selection) return
      void act('default-model', async () => { await setGlobalDefaultModel(selection); await refresh() })
    }} /><p className="mt-2 text-xs text-[var(--muted-foreground)]">Selections are saved immediately. Chats, learning and new tasks that follow the default use this model; explicit selections remain unchanged.</p></section>
    {applied && <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-[var(--success)]/25 bg-[var(--success-surface)] px-4 py-3 text-sm text-[var(--success)]"><Check size={17} />DeepSeek Connection saved · {applied.model}<Link className="ml-auto underline underline-offset-4" href="/chat">Start learning</Link></div>}
    <div className="space-y-5">
      <div className="space-y-4">
        <section className={panel} aria-labelledby="connect-method">
          <h2 id="connect-method" className="mb-4 text-sm font-semibold">Connect DeepSeek</h2>
          <label htmlFor="harness-model" className="mb-2 block text-xs font-medium">DeepSeek model</label>
          <select id="harness-model" className={`${input} mb-4`} value={model} onChange={event => { modelEdited.current = true; selectedModel.current = event.target.value; setModel(event.target.value) }} disabled={running}>
            {!choices.length && <option value="">Loading available models...</option>}
            {choices.map(item => <option key={item.id} value={item.id}>{item.label || item.id}{item.vision ? ' · Vision supported' : ''}</option>)}
          </select>
          <p className="mb-4 text-xs leading-relaxed text-[var(--muted-foreground)]">Connecting sends a small test request using your account or API credits. Successful verification saves and enables the connection automatically.</p>
          {applied && <div className="mb-4 flex flex-wrap items-center gap-3">
            <button type="button" className={primary} disabled={running || !model} onClick={() => void connect('reuse')}>{busy === 'probe' || busy === 'apply' ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{model === applied.model ? 'Reconnect this DeepSeek model' : 'Connect and set as default'}</button>
            <span className="text-xs text-[var(--muted-foreground)]">Use the saved connection without signing in again or entering an API key.</span>
          </div>}
          <div className="mb-4 flex gap-2" role="group" aria-label="Connection method">
            <button type="button" className={mode === 'account' ? primary : secondary} disabled={running || !model} onClick={() => { setMode('account'); void connect('account') }}>{running && mode === 'account' ? <Loader2 className="animate-spin" size={14} /> : <LogIn size={14} />}{status?.account.authenticated ? 'Sign in again to DeepSeek' : 'Sign in to DeepSeek'}</button>
            <button type="button" className={mode === 'api' ? primary : secondary} disabled={running} aria-pressed={mode === 'api'} onClick={() => { setMode('api'); setTimeout(() => keyRef.current?.focus(), 0) }}><KeyRound size={14} />Use API Key</button>
          </div>
          {mode === 'account' ? <div className="space-y-3 text-sm">
            <p className="leading-relaxed text-[var(--muted-foreground)]">Select Sign in to open the  DeepSeek official page. Enter passwords and verification codes there. When you return, the app verifies the model and connects learning and classrooms automatically.</p>
            {authorization && <p className="rounded-lg bg-[var(--muted)] p-3"><span>The official page did not open automatically.</span> <a href={authorization} target="_blank" rel="noreferrer noopener" className="underline underline-offset-4">Continue sign-in here</a></p>}
            {['failed', 'error', 'query_failed'].includes(status?.account.balance_status || '') && <p className="text-xs text-[var(--muted-foreground)]">Could not retrieve your balance. Check credits on the official platform.</p>}
            {status?.account.error_code && <p className="text-xs">{message(status.account.error_code)}</p>}
          </div> : <form onSubmit={saveKey} className="space-y-3">
            <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">Create an API key on the official platform and enter it below. The key is encrypted locally and used only for the selected service.</p>
            <label className="block text-xs font-medium" htmlFor="deepseek-key">DeepSeek API Key</label>
            <input ref={keyRef} id="deepseek-key" type="password" autoComplete="off" spellCheck={false} className={input} value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder="Paste your API Key" disabled={Boolean(busy)} />
            <div className="flex flex-wrap items-center gap-3"><button type="submit" className={primary} disabled={running || !apiKey.trim() || !model}>{running && <Loader2 size={14} className="animate-spin" />}Connect and enable</button><a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs underline underline-offset-4">Create API Key<ExternalLink size={12} /></a><a href="https://platform.deepseek.com/top_up" target="_blank" rel="noreferrer noopener" className="text-xs underline underline-offset-4">View or add credits</a></div>
          </form>}
          <div role="status" aria-live="polite" className="mt-4 flex items-start gap-2 rounded-lg bg-[var(--muted)] px-3 py-3 text-sm">
            {running && <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin" />}
            <span>{progress || (error ? 'Connection did not finish. Follow the guidance above and reconnect.' : applied ? 'Connected. You can start learning.' : operation?.status ? (labels[operation.status] || 'Choose sign-in or an API Key.') : 'Select a model, then sign in or enter an API Key,  to connect automatically.')}</span>
          </div>
          {!error && operationError && <p className="mt-2 text-xs" role="alert">{operationError}</p>}
          <p className="mt-3 text-xs leading-relaxed text-[var(--muted-foreground)]">The current default model appears above. Manage other models, embeddings and speech under Other model settings.</p>
          <div className="mt-4 flex flex-wrap gap-2 border-t border-[var(--border)] pt-3">
            {flow.current && <button type="button" className={secondary} disabled={!canCancel} onClick={() => void cancel()}><X size={14} />Cancel this connection</button>}
            {canRollback && <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => void act('rollback', async () => { const result = await request<Result>('/rollback', { ...identity, confirm: true }); accept(result); if (result.operation.status === 'rolled_back') invalidateLLMOptionsCache(); await refresh() })}>Restore previous settings</button>}
            {status?.account.authenticated && <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => void act('signout', async () => { await request('/account/signout', identity); setAuthorization(''); await refresh() })}><Unplug size={14} />Sign out of  DeepSeek account</button>}
          </div>
        </section>
      </div>
      <section className={panel} aria-labelledby="other-providers">
        <h2 id="other-providers" className="text-sm font-semibold">Use another model service</h2>
        <p className="my-3 text-sm leading-relaxed text-[var(--muted-foreground)]">Already have an API from another provider,  or a model you run locally? Add its endpoint, model name and API key, then select it as the default above.</p>
        <Link href="/settings/llm" className={secondary}>Configure another model API</Link>
      </section>
    </div>
  </FeaturePage>
}
