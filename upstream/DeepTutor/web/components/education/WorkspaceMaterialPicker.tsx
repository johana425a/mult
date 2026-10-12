'use client'

import { useEffect, useRef, useState } from 'react'
import { deepsteamService } from '@/lib/deepsteam-api'
import { WorkspaceSourceStatus } from '@/components/workspaces/WorkspaceSourceStatus'

interface Entry { path: string; name: string; is_dir: boolean; size_bytes?: number }
interface WindowResult {
  ok: boolean; status: string; text: string; next_cursor?: string | null; truncated?: boolean
  document: { sha256: string; unit_count?: number }; warnings?: string[]
  units?: { locator: Record<string, unknown>; assets?: { id: string }[] }[]
}
export function sourceRangeLabel(locators?: Record<string, unknown>[]): string {
  if (!locators?.length) return 'Current text excerpt'
  return locators.map(locator => {
    if (locator.page) return `PDF page ${locator.page}`
    if (locator.slide) return `Slide ${locator.slide}`
    if (locator.paragraph) return `Paragraph ${locator.paragraph}`
    if (locator.table) return `Table ${locator.table}`
    if (locator.line_start) return `Lines ${locator.line_start}–${locator.line_end ?? locator.line_start}`
    if (locator.sheet) return `Sheet ${locator.sheet}`
    return 'Text excerpt'
  }).join(', ')
}

async function call<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${deepsteamService(3791)}/api${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    signal: AbortSignal.timeout(180000),
  })
  const body = await response.json()
  if (!response.ok || body.ok === false) throw new Error(typeof body.detail === 'string' ? body.detail : body.error?.message || 'Material reading did not finish. Try again.')
  return body as T
}

/** Reads only explicitly selected files in the task's existing workspace. */
export function WorkspaceMaterialPicker({ workspaceId, materialId, onSelected, onCancel }: {
  workspaceId: string; materialId?: string; onSelected: (id: string) => void; onCancel: () => void
}) {
  const [directory, setDirectory] = useState('')
  const [entries, setEntries] = useState<Entry[]>([])
  const [listTruncated, setListTruncated] = useState(false)
  const [path, setPath] = useState('')
  const [preview, setPreview] = useState<WindowResult | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const [history, setHistory] = useState<(string | null)[]>([])
  const [units, setUnits] = useState(10)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  useEffect(() => () => { generation.current += 1 }, [])

  const read = async (file: string, next: string | null, maxUnits = units, hash?: string) => {
    const version = ++generation.current
    setBusy(true); setError('')
    try {
      const result = await call<WindowResult>(materialId ? `/materials/${encodeURIComponent(materialId)}/read`
        : `/workspaces/${encodeURIComponent(workspaceId)}/documents/read`,
      { path: file, cursor: next, document_sha256: hash, max_units: maxUnits })
      if (version === generation.current) { setPreview(result); setPath(file); setCursor(next) }
    } catch (reason) { if (version === generation.current) { setError(reason instanceof Error ? reason.message : 'Could not read the material.'); setPreview(null) } }
    finally { if (version === generation.current) setBusy(false) }
  }

  useEffect(() => {
    if (materialId) { void read('', null); return }
    if (!workspaceId) return
    const version = ++generation.current
    setBusy(true); setError(''); setPreview(null)
    void call<{ entries: Entry[]; truncated?: boolean }>(`/workspaces/${encodeURIComponent(workspaceId)}/documents/list`, { path: directory })
      .then(result => { if (version === generation.current) { setEntries(result.entries || []); setListTruncated(Boolean(result.truncated)) } })
      .catch(reason => { if (version === generation.current) setError(reason instanceof Error ? reason.message : 'Could not load the file list.') })
      .finally(() => { if (version === generation.current) setBusy(false) })
    // The selected workspace and directory own this picker instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, directory, materialId])

  const select = async () => {
    if (!preview || busy) return
    setBusy(true); setError('')
    try {
      const result = await call<{ id: string }>(materialId ? `/materials/${encodeURIComponent(materialId)}/select-range` : '/materials/from-workspace',
        { workspace_id: workspaceId, path, cursor, document_sha256: preview.document.sha256, max_units: units })
      onSelected(result.id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The selected range was not saved. Try again.'); setBusy(false) }
  }
  return <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4" aria-label="Select workspace materials">
    <div className="flex items-center justify-between gap-3"><h3 className="font-medium">{materialId ? 'Select classroom reading range' : 'Choose materials from the current workspace'}</h3>
      <button type="button" disabled={busy} onClick={onCancel}>Close</button></div>
    {!materialId && <WorkspaceSourceStatus workspaceId={workspaceId} compact />}
    {!workspaceId && !materialId && <p className="mt-3 text-sm">Select a workspace linked to a folder in the sidebar, then choose materials from it.</p>}
    {error && <p role="alert" className="mt-3 text-sm text-[var(--destructive)]">{error}</p>}
    {!materialId && workspaceId && <div className="mt-3 max-h-56 overflow-y-auto rounded border border-[var(--border)] p-2" aria-label="Workspace files">
      {directory && <button type="button" disabled={busy} className="block p-2 text-sm" onClick={() => setDirectory(directory.split('/').slice(0, -1).join('/'))}>Up one level</button>}
      {entries.map(entry => <button key={entry.path} type="button" disabled={busy} className="block w-full rounded p-2 text-left text-sm hover:bg-[var(--muted)]"
        onClick={() => { setHistory([]); if (entry.is_dir) setDirectory(entry.path); else void read(entry.path, null) }}>{entry.is_dir ? 'Folder: ' : ''}{entry.name}</button>)}
      {!entries.length && !busy && <p className="p-2 text-sm">No usable materials in this directory.</p>}
      {listTruncated && <p className="p-2 text-xs">Only part of this large directory is shown. Open a more specific subfolder.</p>}
    </div>}
    {busy && <p role="status" className="mt-3 text-sm">Reading materials...</p>}
    {preview && <div className="mt-4 space-y-3">
      <p className="break-words text-sm font-medium">{path || 'Uploaded material'} · {sourceRangeLabel(preview.units?.map(unit => unit.locator))}</p>
      <label className="flex items-center gap-2 text-sm">Range per read
        <select aria-label="Range per read" disabled={busy} value={units} onChange={event => { const value = Number(event.target.value); setUnits(value); setHistory([]); void read(path, null, value, preview.document.sha256) }}>
          <option value={1}>1 page / paragraph / slide</option><option value={5}>5 pages / paragraphs / slides</option><option value={10}>10 pages / paragraphs / slides</option>
        </select></label>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-[var(--muted)] p-3 text-xs leading-relaxed">{preview.text || 'No text could be extracted from this range.'}</pre>
      <p className="text-xs text-[var(--muted-foreground)]">The classroom uses only the displayed range. {preview.truncated || preview.next_cursor ? 'More content follows. Continue browsing before selecting.' : 'End of document.'} The original file stays in its current location.</p>
      {preview.warnings?.map((warning, index) => <p key={index} className="text-xs text-[var(--warning-foreground)]">{warning}</p>)}
      {preview.status === 'needs_ocr' && <p className="text-sm">The scanned content does not yet have usable OCR. Pages with missing text cannot be used as complete source text for a classroom.</p>}
      <div className="flex flex-wrap gap-3">
        <button type="button" disabled={busy || !history.length} onClick={() => { const previous = history[history.length - 1]; setHistory(history.slice(0, -1)); void read(path, previous, units, preview.document.sha256) }}>Previous section</button>
        <button type="button" disabled={busy || !preview.next_cursor} onClick={() => { setHistory([...history, cursor]); void read(path, preview.next_cursor || null, units, preview.document.sha256) }}>Next section</button>
        <button type="button" disabled={busy || !preview.text?.trim() || preview.status === 'needs_ocr'} onClick={() => void select()}>Use the current reading range</button>
      </div>
    </div>}
  </section>
}
