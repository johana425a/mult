'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, FolderInput, RefreshCw } from 'lucide-react'
import { apiFetch, apiUrl } from '@/lib/api'
import { useChatWorkspaces } from '@/hooks/useChatWorkspaces'
import { activeWorkspaceId } from '@/lib/workspace-scope'

type Feature = {
  feature: string
  label: string
  path: string
  files: number
  bytes: number
  sessions?: number
  error: string
}
type Discovery = { features: Feature[]; historical: { path: string }[]; session_backend: string }
type Preview = {
  features: string[]
  dependencies: string[]
  sessions: number
  files: number
  bytes: number
  blockers: string[]
}
type Operation = {
  id: string
  status: string
  created_at: string
  error?: string
  download_url?: string
  recovery_path?: string
}
const endpoint = '/api/settings/workspace/data'
const labels: Record<string, [string, string]> = {
  chat: ['Conversations', 'Conversations'],
  book: ['Books', 'Books'],
  learning: ['Mastery Path', 'Mastery Path'],
  reading: ['Immersive Reading', 'Immersive Reading'],
  timed_media: ['Immersive Watching', 'Immersive Watching'],
  notebook: ['Notebooks', 'Notebooks'],
  'co-writer': ['Writing', 'Writing'],
  courses: ['Courses', 'Courses'],
  files: ['File library', 'File library'],
  knowledge_bases: ['Knowledge bases', 'Knowledge bases'],
  parse_cache: ['Document cache', 'Document cache'],
  outputs: ['Generated outputs', 'Generated outputs'],
  presentations: ['Presented files', 'Presented files'],
  attachments: ['Conversation attachments', 'Conversation attachments'],
  historical_chat: ['Historical conversation database', 'Historical conversation database'],
  historical_agent: ['Historical agent outputs', 'Historical agent outputs'],
  historical_output: ['Historical output folder', 'Historical output folder'],
  historical_archive: ['Historical archives', 'Historical archives'],
}

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await apiFetch(
    apiUrl(`${endpoint}${path}`),
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : undefined
  )
  const value = await response.json()
  if (!response.ok) throw new Error(value.detail || `Request failed (${response.status})`)
  return value as T
}

export default function DataMigrationSettingsSection() {
  const { i18n } = useTranslation()
  const zh = i18n.language.startsWith('zh')
  const text = (en: string, cn: string) => (zh ? cn : en)
  const { workspaces } = useChatWorkspaces()
  const [source, setSource] = useState(activeWorkspaceId)
  const [target, setTarget] = useState('')
  const [discovery, setDiscovery] = useState<Discovery | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<Preview | null>(null)
  const [operations, setOperations] = useState<Operation[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [historical, setHistorical] = useState(false)
  const label = (key: string) => labels[key]?.[zh ? 1 : 0] ?? key
  const statusLabel = (key: string) => ({
    preparing: text('Preparing', 'Preparing'), copying: text('Copying', 'Copying'),
    transferring: text('Transferring', 'Transferring'), committed: text('Finishing', 'Finishing'),
    completed: text('Completed', 'Completed'), exported: text('Exported', 'Exported'),
    recovered: text('Recovered', 'Recovered'), failed: text('Failed; source retained', 'Failed; source retained'),
    cleanup_required: text('Cleanup required', 'Cleanup required'),
    recovery_required: text('Recovery required', 'Recovery required'),
  }[key] || key)
  const input = {
    source_workspace_id: source,
    target_workspace_id: target,
    features: selected,
    include_historical: historical,
  }
  useEffect(() => {
    setPreview(null)
  }, [source, target, selected])
  useEffect(() => {
    let alive = true
    const timer = window.setInterval(() => {
      request<{ operations: Operation[] }>('/operations')
        .then(value => {
          if (alive) setOperations(value.operations)
        })
        .catch(() => {})
    }, 5000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])
  useEffect(() => {
    let alive = true
    setDiscovery(null)
    setSelected([])
    setError('')
    request<Discovery>(`/discover?source_workspace_id=${encodeURIComponent(source)}`)
      .then(value => {
        if (alive) setDiscovery(value)
      })
      .catch(err => {
        if (alive) setError(String(err.message))
      })
    request<{ operations: Operation[] }>('/operations')
      .then(value => {
        if (alive) setOperations(value.operations)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [source])
  async function run(action: 'preview' | 'migrate' | 'export') {
    setBusy(true)
    setError('')
    try {
      if (action === 'preview') setPreview(await request<Preview>('/preview', input))
      else {
        const result = await request<Operation>(`/${action}`, input)
        setOperations(old => [result, ...old])
        if (action === 'migrate') {
          setPreview(null)
          setSelected([])
          setDiscovery(
            await request<Discovery>(`/discover?source_workspace_id=${encodeURIComponent(source)}`)
          )
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  async function recover(id: string) {
    setBusy(true)
    setError('')
    try {
      const result = await request<Operation>(`/operations/${id}/recover`, {})
      setOperations(old => old.map(row => (row.id === id ? result : row)))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  const options = (
    <>
      <option value="">{text('Default workspace', 'Default workspace')}</option>
      {workspaces
        .filter(row => !row.archived)
        .map(row => (
          <option key={row.workspace_id} value={row.workspace_id}>
            {row.display_name}
          </option>
        ))}
    </>
  )
  return (
    <section className="space-y-5">
      <h2 className="text-lg font-semibold">{text('Data migration', 'Data migration')}</h2>
      <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
        {text(
          'Discover stored learning data, move it with its related conversations, or download an archive. Verified recovery copies are retained after migration.',
          'Discover stored learning data, move it with its related conversations, or download an archive. Verified recovery copies are retained after migration.'
        )}
      </p>
      <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
        {text(
          'Learning data moves as a complete feature bundle. Preview includes related sources and conversations. Choose a destination with no existing data for these features.',
          'Learning data moves as a complete feature bundle. Preview includes related sources and conversations. Choose a destination with no existing data for these features.'
        )}
      </p>
      {selected.some(key => key.startsWith('historical_')) ? (
        <p className="text-sm text-[var(--muted-foreground)]">
          {text(
            'Historical data is retained as an archive inside the destination workspace. It is not automatically merged into current learning records.',
            'Historical data is retained as an archive inside the destination workspace. It is not automatically merged into current learning records.'
          )}
        </p>
      ) : null}
      <fieldset disabled={busy} className="space-y-4 disabled:opacity-60">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-sm">
            <span>{text('Source workspace', 'Source workspace')}</span>
            <select
              value={source}
              onChange={event => setSource(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
            >
              {options}
            </select>
          </label>
          <label className="space-y-2 text-sm">
            <span>{text('Destination workspace', 'Destination workspace')}</span>
            <select
              value={target}
              onChange={event => setTarget(event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2"
            >
              {options}
            </select>
          </label>
        </div>
        <div className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)]">
          {!discovery ? (
            <p className="p-4 text-sm" aria-busy="true">
              {text('Searching stored data…', 'Searching stored data…')}
            </p>
          ) : (
            discovery.features.map(row => (
              <label key={row.feature} className="flex cursor-pointer items-start gap-3 p-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.includes(row.feature)}
                  disabled={!!row.error || (!row.files && !row.sessions)}
                  onChange={event =>
                    setSelected(old =>
                      event.target.checked
                        ? [...old, row.feature]
                        : old.filter(key => key !== row.feature)
                    )
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{label(row.feature)}</span>
                  <span className="block text-xs text-[var(--muted-foreground)]">
                    {row.sessions !== undefined
                      ? `${row.sessions} ${text('conversations', 'conversations')} · `
                      : ''}
                    {row.files} {text('files', 'files')} · {(row.bytes / 1024 / 1024).toFixed(1)}{' '}
                    MB
                  </span>
                  <span className="mt-1 block break-all text-[11px] text-[var(--muted-foreground)]">
                    {row.error || row.path}
                  </span>
                </span>
              </label>
            ))
          )}
        </div>
        {discovery?.historical.length ? (
          <details className="rounded-lg border border-[var(--border)] p-3 text-sm">
            <summary>
              {text('Additional historical data', 'Additional historical data')} ({discovery.historical.length})
            </summary>
            <p className="my-2 text-xs text-[var(--muted-foreground)]">
              {text(
                'Historical archives can be included in exports for recovery and inspection.',
                'Historical archives can be included in exports for recovery and inspection.'
              )}
            </p>
            {discovery.historical.map(row => (
              <p key={row.path} className="break-all text-xs">
                {row.path}
              </p>
            ))}
            <label className="mt-3 flex items-center gap-2">
              <input
                type="checkbox"
                checked={historical}
                onChange={event => setHistorical(event.target.checked)}
              />
              {text('Include in export', 'Include in export')}
            </label>
          </details>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button
            disabled={!selected.length}
            onClick={() => void run('preview')}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
          >
            <RefreshCw size={14} />
            {text('Preview migration', 'Preview migration')}
          </button>
          <button
            disabled={!selected.length}
            onClick={() => void run('export')}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
          >
            <Download size={14} />
            {text('Export selected data', 'Export selected data')}
          </button>
        </div>
        {preview ? (
          <div className="space-y-3 rounded-xl border border-[var(--border)] p-4">
            <p className="text-sm">
              {preview.sessions} {text('conversations', 'conversations')} · {preview.files}{' '}
              {text('files', 'files')} · {(preview.bytes / 1024 / 1024).toFixed(1)} MB
            </p>
            <p className="text-sm">
              {text('Included features', 'Included features')}: {preview.features.map(label).join(', ')}
            </p>
            {preview.dependencies.length ? (
              <p className="text-xs text-[var(--muted-foreground)]">
                {text(
                  'Related source data included to preserve references',
                  'Related source data included to preserve references'
                )}
                : {preview.dependencies.map(label).join(', ')}
              </p>
            ) : null}
            {preview.blockers.map((reason, i) => (
              <p key={i} className="text-sm text-[var(--destructive)]">
                {reason}
              </p>
            ))}
            <button
              disabled={preview.blockers.length > 0}
              onClick={() => void run('migrate')}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-40"
            >
              <FolderInput size={14} />
              {text('Migrate these data', 'Migrate these data')}
            </button>
          </div>
        ) : null}
      </fieldset>
      {busy ? (
        <p role="status" className="text-sm">
          {text(
            'Processing. You can return to this page to view the result.',
            'Processing. You can return to this page to view the result.'
          )}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-[var(--destructive)]">
          {error}
        </p>
      ) : null}
      {operations.length ? (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{text('Recent operations', 'Recent operations')}</h3>
          {operations.slice(0, 10).map(row => (
            <div
              key={row.id}
              className="space-y-1 rounded-lg border border-[var(--border)] p-3 text-xs"
            >
              <p>
                {statusLabel(row.status)} · {new Date(row.created_at).toLocaleString('en-US')}
              </p>
              {row.error ? <p className="text-[var(--destructive)]">{row.error}</p> : null}
              {row.download_url ? (
                <a
                  href={apiUrl(row.download_url)}
                  className="inline-flex items-center gap-1 text-[var(--primary)]"
                >
                  <Download size={12} />
                  {text('Download archive', 'Download archive')}
                </a>
              ) : null}
              {!['completed', 'exported', 'recovered'].includes(row.status) ? (
                <button
                  disabled={busy}
                  onClick={() => void recover(row.id)}
                  className="rounded border border-[var(--border)] px-2 py-1"
                >
                  {text('Recover migration', 'Recover migration')}
                </button>
              ) : null}
              {row.recovery_path ? (
                <p className="break-all text-[var(--muted-foreground)]">
                  {text('Recovery copy', 'Recovery copy')}: {row.recovery_path}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
