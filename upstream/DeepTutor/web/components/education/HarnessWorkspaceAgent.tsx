'use client'

import Link from 'next/link'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Bot, FolderOpen, Loader2, Plus, RefreshCw, Send, ShieldCheck, Square, Terminal, X } from 'lucide-react'
import { FeaturePage, PageHeader, pageActionClass } from '@/components/layout/FeaturePage'
import { canPickWorkspaceDirectory, folderName, openWorkspaceDirectory, pickWorkspaceDirectory } from '@/lib/deepsteam-desktop'
import { inheritedWorkspaceResources, openWorkspaceFolder, saveWorkspace } from '@/lib/workspaces-api'
import { harnessWorkspaceAPI as api, harnessEventImages, harnessEventText, mergeHarnessEvents, type HarnessApproval, type HarnessEvent, type HarnessSession, type HarnessWorkspace } from '@/lib/harness-workspace'
import { deepsteamService } from '@/lib/deepsteam-api'
import { safeServiceError } from '@/lib/deepsteam-transport'
import { UnifiedModelControl } from '@/components/common/UnifiedModelControl'
import { ResolvedModelBadge } from '@/components/common/ResolvedModelBadge'
import { useSurfaceModelSelection } from '@/hooks/useSurfaceModelSelection'
import { WorkspaceContextMenu } from '@/components/ui/WorkspaceContextMenu'
import { Dialog } from '@/shared/ui/Dialog'
import { manageWorkspace } from '@/lib/workspace-management'
import { subscribeSessionChanges } from '@/lib/session-events'

const panel = 'rounded-xl border border-[var(--border)] bg-[var(--card)] p-4'
const input = 'w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-sm outline-none focus:border-[var(--ring)] disabled:opacity-50'
const primary = pageActionClass('primary')
const secondary = pageActionClass('secondary')
const activeStatus = (status: string) => ['running', 'awaiting_approval', 'waiting_approval', 'cancelling'].includes(status)

function WorkspaceImage({ sessionId, attachmentId }: { sessionId: string; attachmentId: string }) {
  const [source, setSource] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    let objectURL = ''
    void fetch(`${deepsteamService(3791)}/api/harness/sessions/${encodeURIComponent(sessionId)}/attachments/${encodeURIComponent(attachmentId)}`, { signal: controller.signal, credentials: 'omit', cache: 'no-store' }).then(async response => {
      if (!response.ok) throw new Error('IMAGE_UNAVAILABLE')
      const blob = await response.blob()
      if (!/^image\/(png|jpeg|webp|gif)$/.test(blob.type) || blob.size > 32 * 1024 * 1024) throw new Error('IMAGE_INVALID')
      if (controller.signal.aborted) return
      objectURL = URL.createObjectURL(blob); setSource(objectURL)
    }).catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => { controller.abort(); if (objectURL) URL.revokeObjectURL(objectURL) }
  }, [sessionId, attachmentId])
  return source ? <img alt="Image read from the workspace" src={source} className="max-h-96 max-w-full rounded-lg object-contain" /> : <p role="status" className="text-xs text-[var(--muted-foreground)]">{failed ? 'The image is unavailable right now; the original tool record was preserved.' : 'Loading the workspace image...'}</p>
}

function EventCard({ event, pending, decision, sessionId }: { event: HarnessEvent; pending?: boolean; decision?: string; sessionId: string }) {
  if (event.approval) return pending ? null : <article className="rounded-lg border border-[var(--border)] p-3 text-xs"><strong>Operation approval record: {decision === 'allowed-once' ? 'Allowed once' : decision === 'rejected' ? 'Rejected' : decision === 'cancelled' ? 'Cancelled' : 'Waiting for a result'}</strong><p className="mt-2 break-all">Directory: {event.approval.exact_action.cwd}</p><pre className="mt-2 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(event.approval.exact_action.arguments, null, 2)}</pre></article>
  const text = harnessEventText(event)
  const images = harnessEventImages(event)
  const tool = Boolean(event.tool_name) || event.type.includes('tool')
  const user = event.type === 'user/message'
  if (!text && !tool && !images.length) return null
  return <article className={`${tool ? 'border border-[var(--border)]' : user ? 'ml-8 bg-[var(--secondary)]' : 'mr-4 bg-[var(--muted)]'} rounded-lg p-3 text-sm`}>
    <p className="mb-1 flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">{tool ? <Terminal size={12} /> : <Bot size={12} />}{tool ? `${event.tool_name || 'Tool'} · ${event.type.includes('result') ? 'Result' : 'Call'}` : user ? 'You' : 'Agent'}{event.is_error ? ' · Operation incomplete' : ''}</p>
    {event.arguments !== undefined && <details className="mb-2 text-xs"><summary className="cursor-pointer">View tool arguments</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(event.arguments, null, 2)}</pre></details>}
    {images.map(image => <WorkspaceImage key={image.attachmentId} sessionId={sessionId} attachmentId={image.attachmentId} />)}
    {text && <pre className={`whitespace-pre-wrap break-words leading-7 ${tool ? 'max-h-80 overflow-auto font-mono text-xs' : 'font-sans'}`}>{text}</pre>}
    {!user && !tool && <ResolvedModelBadge value={event.resolved_model} className="mt-2" />}
  </article>
}

export function HarnessWorkspaceAgent() {
  const [workspaces, setWorkspaces] = useState<HarnessWorkspace[]>([])
  const [workspaceId, setWorkspaceId] = useState('')
  const [sessions, setSessions] = useState<HarnessSession[]>([])
  const [session, setSession] = useState<HarnessSession | null>(null)
  const [events, setEvents] = useState<HarnessEvent[]>([])
  const [approvals, setApprovals] = useState<HarnessApproval[]>([])
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [management, setManagement] = useState<{ workspace: HarnessWorkspace; mode: 'rename' | 'archive' } | null>(null)
  const [newName, setNewName] = useState('')
  const [managementError, setManagementError] = useState('')
  const sequence = useRef(-1)
  const generation = useRef(0)
  const eventGeneration = useRef(0)
  const preparedSessions = useRef<{ workspaceId: string; sessions: HarnessSession[] } | null>(null)
  const actionPending = useRef(false)
  const mounted = useRef(false)
  const refreshGeneration = useRef(0)
  const selectedWorkspaceId = useRef(workspaceId)
  selectedWorkspaceId.current = workspaceId
  const selected = workspaces.find(item => item.id === workspaceId && !item.archived)
  const activeWorkspaces = workspaces.filter(item => !item.archived)
  const archivedWorkspaces = workspaces.filter(item => item.archived)
  const running = Boolean(session && activeStatus(session.status))
  const [modelSelection, setModelSelection] = useSurfaceModelSelection(`workspace:${session?.id || workspaceId || 'draft'}`, session?.llm_selection)

  const refresh = useCallback(async () => {
    const request = ++refreshGeneration.current
    try {
      const list = await api.list()
      if (!mounted.current || refreshGeneration.current !== request) return
      const previous = selectedWorkspaceId.current
      const next = list.workspaces.some(item => item.id === previous && !item.archived) ? previous : list.workspaces.find(item => !item.archived)?.id || ''
      setWorkspaces(list.workspaces)
      if (next !== previous) {
        // An external archive must also invalidate in-flight session/event
        // reads before switching, so a late approval cannot reappear.
        ++generation.current; ++eventGeneration.current
        preparedSessions.current = null; sequence.current = -1
        setSessions([]); setSession(null); setEvents([]); setApprovals([]); setPrompt('')
        selectedWorkspaceId.current = next; setWorkspaceId(next)
        setManagement(null)
      }
    } catch (failure) {
      if (mounted.current && refreshGeneration.current === request) throw failure
    }
  }, [])
  useEffect(() => {
    mounted.current = true
    const reload = () => { void refresh().catch(failure => { if (mounted.current) setError(failure.message) }) }
    const unsubscribe = subscribeSessionChanges(reload)
    reload()
    return () => { mounted.current = false; ++refreshGeneration.current; ++generation.current; ++eventGeneration.current; unsubscribe() }
  }, [refresh])
  useEffect(() => {
    const current = ++generation.current
    setSessions([]); setSession(null); setEvents([]); setApprovals([]); sequence.current = -1
    if (!workspaceId) return
    if (preparedSessions.current?.workspaceId === workspaceId) {
      const prepared = preparedSessions.current.sessions
      preparedSessions.current = null
      setSessions(prepared); setSession(prepared[0] || null)
      return
    }
    void api.sessions(workspaceId).then(value => { if (mounted.current && generation.current === current) { setSessions(value.sessions); setSession(value.sessions[0] || null) } }).catch(failure => { if (mounted.current && generation.current === current) setError(failure.message) })
    return () => { if (generation.current === current) ++generation.current }
  }, [workspaceId])
  useEffect(() => {
    const current = ++eventGeneration.current
    sequence.current = -1; setEvents([]); setApprovals([])
    if (!session?.id) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const value = await api.events(session.id, sequence.current)
        if (stopped || eventGeneration.current !== current) return
        sequence.current = value.next_seq
        setEvents(previous => mergeHarnessEvents(previous, value.events))
        setSession(value.session)
        setApprovals(value.pending_approvals || [])
        timer = setTimeout(poll, activeStatus(value.session.status) || value.pending_approvals?.length ? 900 : 3000)
      } catch (failure) {
        if (!stopped && eventGeneration.current === current) { setError(failure instanceof Error ? failure.message : 'The workspace service is currently unavailable.'); timer = setTimeout(poll, 4000) }
      }
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [session?.id])

  const act = async (action: string, work: () => Promise<void>) => {
    if (actionPending.current) return
    actionPending.current = true
    setBusy(action); setError(''); setNotice('')
    try { await work() } catch (failure) { setError(failure instanceof Error ? failure.message : 'The operation did not finish.') }
    finally { actionPending.current = false; setBusy('') }
  }
  const chooseFolder = () => act('folder', async () => { const selectedPath = await pickWorkspaceDirectory(); if (selectedPath) { setPath(selectedPath); if (!name.trim()) setName(folderName(selectedPath)); setCreating(true) } })
  const registerFolder = async (directory: string, title: string) => {
    // Native learning and Harness use one canonical, existing directory.
    const native = await saveWorkspace({ name: title, path: directory, resources: inheritedWorkspaceResources() })
    try {
      return native.harness_workspace_id
        ? { id: native.harness_workspace_id, path: native.path }
        : (await api.create(native.path, native.display_name)).workspace
    } catch (failure) {
      throw new Error(`The learning workspace is registered at ${native.path}; Agent registration did not finish. Retry with the same folder. ${failure instanceof Error ? failure.message : ''}`)
    }
  }
  const openFolder = () => act('open-folder', async () => {
    const directory = await pickWorkspaceDirectory()
    if (!directory) return
    const native = await openWorkspaceFolder(directory)
    if (!native.harness_workspace_id) throw new Error(`The agent workspace could not be loaded. Retry: ${native.path}`)
    const registered = { id: native.harness_workspace_id, path: native.path }
    const list = await api.list()
    if (!list.workspaces.some(item => item.id === registered.id)) throw new Error(`The folder is registered, but the workspace could not be loaded. Retry: ${registered.path}`)
    if (list.workspaces.find(item => item.id === registered.id)?.archived) {
      const restored = await manageWorkspace(registered.id, { archived: false })
      if (restored.workspace.archived) throw new Error('The workspace has not been restored. Retry under Removed workspaces.')
      list.workspaces = list.workspaces.map(item => item.id === registered.id ? { ...item, archived: restored.workspace.archived, title: restored.workspace.title || restored.workspace.name, path: restored.workspace.path } : item)
    }
    const history = await api.sessions(registered.id)
    const restored = history.sessions.length ? history.sessions : [(await api.newSession(registered.id)).session]
    // Commit only after registration and a real session are ready. Cancelling or
    // failing the operation leaves the previously active workspace untouched.
    ++generation.current; ++refreshGeneration.current
    setWorkspaces(list.workspaces)
    if (workspaceId === registered.id) {
      preparedSessions.current = null
      setSessions(restored); setSession(restored[0])
    } else {
      preparedSessions.current = { workspaceId: registered.id, sessions: restored }
      ++eventGeneration.current
      setWorkspaceId(registered.id)
    }
    setCreating(false); setPath(''); setName(''); setPrompt('')
    setNotice(`Opened folder: ${registered.path}`)
  })
  const create = (event: FormEvent) => {
    event.preventDefault()
    void act('create', async () => {
      if (!path.trim()) throw new Error('Select an existing local folder first.')
      const result = await registerFolder(path.trim(), name.trim() || folderName(path))
      await refresh(); setWorkspaceId(result.id); setCreating(false); setPath(''); setName('')
      setNotice(`Using folder: ${result.path}`)
    })
  }
  const startSession = () => act('session', async () => {
    if (!selected) return
    const value = await api.newSession(selected.id)
    setSessions(previous => [value.session, ...previous]); setSession(value.session)
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!session || !prompt.trim() || running) return
    const sessionId = session.id
    void act('turn', async () => {
      const value = await api.turn(sessionId, prompt.trim(), modelSelection)
      setPrompt(''); setSession(previous => previous?.id === sessionId ? { ...previous, status: value.status, llm_selection: modelSelection, resolved_model: value.resolved_model } : previous)
    })
  }
  const decide = (approval: HarnessApproval, decision: 'allow' | 'deny') => act(`approval-${approval.id}`, async () => {
    if (approval.session_id !== session?.id) return
    await api.approve(approval, decision)
    setApprovals(previous => previous.filter(item => item.id !== approval.id))
  })
  const beginManagement = (workspace: HarnessWorkspace, mode: 'rename' | 'archive') => {
    if (busy) return
    if (mode === 'archive' && workspace.id === workspaceId && running) {
      setError('A task is running in this workspace. Stop it before removing the workspace.')
      return
    }
    setManagement({ workspace, mode }); setNewName(workspace.title || folderName(workspace.path)); setManagementError('')
  }
  const submitManagement = () => act('manage', async () => {
    if (!management) return
    const { workspace, mode } = management
    if (mode === 'rename' && !newName.trim()) { setManagementError('Enter a workspace name.'); return }
    if (mode === 'archive' && workspace.id === workspaceId && running) { setManagementError('The task is still running. Stop it first.'); return }
    try {
      const result = await manageWorkspace(workspace.id, mode === 'rename' ? { name: newName.trim() } : { archived: true })
      const updated = { ...workspace, title: result.workspace.title || result.workspace.name, path: result.workspace.path, archived: result.workspace.archived }
      setWorkspaces(previous => previous.map(item => item.id === workspace.id ? updated : item))
      if (updated.archived && workspace.id === workspaceId) {
        ++generation.current; ++eventGeneration.current; preparedSessions.current = null; sequence.current = -1
        setSessions([]); setSession(null); setEvents([]); setApprovals([]); setPrompt('')
        setWorkspaceId(workspaces.find(item => item.id !== workspace.id && !item.archived)?.id || '')
      }
      setManagement(null)
      setNotice(mode === 'rename' ? `Workspace renamed: ${updated.title}` : 'Workspace moved to Removed workspaces. Files and sessions were preserved; you can restore it anytime.')
    } catch (failure) {
      setManagementError(failure instanceof Error ? failure.message : 'The workspace update did not finish.')
    }
  })
  const restoreWorkspace = (workspace: HarnessWorkspace) => act('restore', async () => {
    const result = await manageWorkspace(workspace.id, { archived: false })
    setWorkspaces(previous => previous.map(item => item.id === workspace.id ? { ...item, title: result.workspace.title || result.workspace.name, path: result.workspace.path, archived: result.workspace.archived } : item))
    setNotice(`Workspace restored: ${result.workspace.title || result.workspace.name}`)
  })

  return <FeaturePage>
    <PageHeader title="Workspace agent" description="Select a local folder for the agent to read, search and process files. Sessions and tool execution records are saved." action={<><button className={secondary} disabled={Boolean(busy)} onClick={() => void act('refresh', refresh)}><RefreshCw size={14} />Refresh</button><Link className={secondary} href="/settings/workspace">Learning workspace</Link></>} />
    <div className={`${panel} mb-5 flex flex-wrap items-center justify-between gap-3`}><UnifiedModelControl value={modelSelection} onChange={setModelSelection} surface="workspace" placement="bottom" label="Model for this session" disabled={Boolean(busy)} /><Link href="/settings" className="text-xs underline">Full model and API settings</Link></div>
    {error && <p role="alert" className="mb-4 rounded-lg border border-[var(--destructive)]/30 p-3 text-sm">{safeServiceError(error)}</p>}
    {notice && <p role="status" className="mb-4 break-all text-xs text-[var(--muted-foreground)]">{notice}</p>}
    <div className="grid items-start gap-5 lg:grid-cols-[250px_minmax(0,1fr)]">
      <aside className="space-y-4">
        <section className={panel}>
          <h2 className="mb-3 text-sm font-semibold">Folder workspaces</h2>
          {canPickWorkspaceDirectory() && <button className={`${primary} w-full justify-center`} disabled={Boolean(busy) || running} onClick={() => void openFolder()}>{busy === 'open-folder' ? <Loader2 className="animate-spin" size={14} /> : <FolderOpen size={14} />}Open folder</button>}
          <button className={`${secondary} mt-2`} disabled={Boolean(busy) || running} onClick={() => canPickWorkspaceDirectory() ? void chooseFolder() : setCreating(true)}><Plus size={14} />Create from a folder</button>
          {creating && <form onSubmit={create} className="mt-4 space-y-3">
            <label className="block text-xs">Workspace name<input className={`${input} mt-1`} value={name} onChange={event => setName(event.target.value)} maxLength={100} /></label>
            <label className="block text-xs">Existing folder path<input required className={`${input} mt-1 font-mono text-xs`} value={path} onChange={event => setPath(event.target.value)} placeholder="Enter the full local folder path" /></label>
            {canPickWorkspaceDirectory() && <button type="button" className="text-xs underline" disabled={Boolean(busy)} onClick={() => void chooseFolder()}>Choose another folder</button>}
            <p className="break-all text-[11px] text-[var(--muted-foreground)]">{path || 'Uses the original folder without automatically moving or copying files.'}</p>
            <div className="flex gap-2"><button className={primary} disabled={Boolean(busy) || !path.trim()} type="submit">Create </button><button className={secondary} type="button" onClick={() => setCreating(false)}>Cancel</button></div>
          </form>}
          <div className="mt-4 space-y-1">{activeWorkspaces.map(item => <WorkspaceContextMenu key={item.id} label={`Workspace actions: ${item.title || folderName(item.path)}`} disabled={Boolean(busy)} items={[
            { id: 'rename', label: 'Rename', onSelect: () => beginManagement(item, 'rename') },
            { id: 'open', label: 'Show in folder', disabled: !canPickWorkspaceDirectory(), onSelect: () => void act('explorer', async () => { if (!(await openWorkspaceDirectory(item.path, item.id))) setNotice('Opening was cancelled.') }) },
            { id: 'archive', label: 'Remove', danger: true, onSelect: () => beginManagement(item, 'archive') },
          ]}><button disabled={running || Boolean(busy)} onClick={() => setWorkspaceId(item.id)} className={`w-full rounded-lg p-2 pr-9 text-left text-xs ${item.id === workspaceId ? 'bg-[var(--accent)]' : 'hover:bg-[var(--muted)]'}`}><strong className="block">{item.title || folderName(item.path)}</strong><span className="mt-1 block break-all text-[10px] text-[var(--muted-foreground)]">{item.path}</span></button></WorkspaceContextMenu>)}</div>
          {archivedWorkspaces.length > 0 && <details className="mt-4 border-t border-[var(--border)] pt-3"><summary className="cursor-pointer text-xs text-[var(--muted-foreground)]">Removed workspaces ({archivedWorkspaces.length})</summary><div className="mt-2 space-y-2">{archivedWorkspaces.map(item => <div key={item.id} className="rounded-lg bg-[var(--muted)] p-2 text-xs"><strong className="block">{item.title || folderName(item.path)}</strong><p className="mt-1 break-all text-[10px] text-[var(--muted-foreground)]">{item.path}</p><button className="mt-2 underline underline-offset-4" disabled={Boolean(busy)} onClick={() => void restoreWorkspace(item)}>Restore workspace</button></div>)}</div></details>}
        </section>
        {selected && <section className={panel}><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Saved sessions</h2><button aria-label="New agent session" className={secondary} disabled={Boolean(busy) || running} onClick={() => void startSession()}><Plus size={14} /></button></div><div className="space-y-1">{sessions.map((item, index) => <button key={item.id} disabled={Boolean(busy) || running} onClick={() => setSession(item)} className={`w-full rounded-lg p-2 text-left text-xs ${session?.id === item.id ? 'bg-[var(--accent)]' : 'hover:bg-[var(--muted)]'}`}>{item.title || `Session ${sessions.length - index}`}</button>)}</div></section>}
      </aside>
      <section className={`${panel} min-w-0`}>
        <h2 className="flex items-center gap-2 text-sm font-semibold"><Bot size={18} />{selected?.title || 'Select a folder first'}</h2>
        {selected && <><p className="mt-2 break-all font-mono text-xs text-[var(--muted-foreground)]">Workspace location: {session?.cwd || selected.path}</p>{canPickWorkspaceDirectory() && <button className={`${secondary} mt-2`} disabled={Boolean(busy)} onClick={() => void act('explorer', async () => { if (!(await openWorkspaceDirectory(session?.cwd || selected.path, selected.id))) setNotice('Opening was cancelled.') })}><FolderOpen size={13} />Show in folder</button>}</>}
        <div className="my-5 max-h-[56vh] min-h-48 space-y-3 overflow-y-auto" aria-live="polite" aria-relevant="additions text">
          {events.map(event => <EventCard key={event.seq} event={event} sessionId={session?.id || ''} pending={Boolean(event.approval && approvals.some(item => item.id === event.approval!.id))} decision={event.approval ? events.findLast(item => item.approval_id === event.approval!.id && item.type === 'approval/decided')?.outcome : undefined} />)}
          {!events.length && <div className="py-8 text-sm leading-relaxed text-[var(--muted-foreground)]"><p>{!selected ? 'Open a local folder to start working there.' : !session ? 'Select New agent session to start working in this folder.' : 'Ask the agent to read materials, search files, edit content or run commands. Terminal commands are shown for your approval before execution.'}</p>{!selected && canPickWorkspaceDirectory() && <button className={`${primary} mt-4`} disabled={Boolean(busy)} onClick={() => void openFolder()}><FolderOpen size={14} />Open folder</button>}</div>}
          {running && <p role="status" className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]"><Loader2 className="animate-spin" size={13} />{approvals.length ? 'Waiting for you to confirm the operation below.' : 'Working; files and tool results will appear as they become available.'}</p>}
        </div>
        {approvals.map(approval => <article key={approval.id} className="mb-4 rounded-xl border border-[var(--warning-foreground)]/30 p-4" aria-label="Operation awaiting approval"><h3 className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck size={16} />{approval.tool_name} requests execution</h3><p className="my-2 break-all text-xs">Directory: {approval.exact_action.cwd}</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[var(--muted)] p-3 text-xs">{JSON.stringify(approval.exact_action.arguments, null, 2)}</pre>{approval.warning && <p className="mt-2 text-xs leading-relaxed">{approval.warning}</p>}<div className="mt-3 flex flex-wrap gap-2"><button className={primary} disabled={Boolean(busy)} onClick={() => void decide(approval, 'allow')}>Allow once</button><button className={secondary} disabled={Boolean(busy)} onClick={() => void decide(approval, 'deny')}><X size={13} />Deny</button></div></article>)}
        <form onSubmit={submit} className="flex items-end gap-2"><label htmlFor="workspace-agent-prompt" className="sr-only">Workspace task</label><textarea id="workspace-agent-prompt" className={`${input} min-h-24 resize-y`} value={prompt} onChange={event => setPrompt(event.target.value)} maxLength={30000} placeholder="Tell the agent what to do in this folder" disabled={!session || Boolean(busy) || running} /><button type="submit" className={primary} disabled={!session || !prompt.trim() || Boolean(busy) || running} aria-label="Send workspace task"><Send size={16} /></button>{running && <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => void act('cancel', async () => { if (session) { await api.cancel(session.id); setNotice('Cancellation requested. Waiting for the tool to finish.') } })}><Square size={13} />Stop</button>}</form>
        <p className="mt-3 text-[11px] leading-relaxed text-[var(--muted-foreground)]">Tasks are sent to the model selected above. Terminal operations use your current computer permissions; review the full command before approving. Learning chats and course records remain in their original features.</p>
      </section>
    </div>
    <Dialog open={Boolean(management)} title={management?.mode === 'rename' ? 'Rename workspace' : 'Remove workspace'} onClose={() => setManagement(null)} size="sm" busy={busy === 'manage'} alert={management?.mode === 'archive'} closeLabel="Close" footer={<><button data-autofocus={management?.mode === 'archive' || undefined} className={secondary} disabled={busy === 'manage'} onClick={() => setManagement(null)}>Cancel</button><button className={primary} disabled={busy === 'manage' || (management?.mode === 'rename' && !newName.trim())} onClick={() => void submitManagement()}>{busy === 'manage' ? 'Saving...' : management?.mode === 'rename' ? 'Save name' : 'Remove workspace'}</button></>}>
      {management && <><p className="mb-3 break-all text-xs text-[var(--muted-foreground)]">{management.workspace.path}</p>{management.mode === 'rename' ? <form onSubmit={event => { event.preventDefault(); void submitManagement() }}><label className="text-sm">New workspace name<input data-autofocus aria-label="New workspace name" className={`${input} mt-2`} maxLength={100} value={newName} onChange={event => setNewName(event.target.value)} disabled={busy === 'manage'} /></label></form> : <p className="text-sm leading-relaxed">The workspace will move to Removed workspaces. Folders, learning records and agent sessions are preserved and can be restored anytime.</p>}{managementError && <p role="alert" className="mt-3 text-sm text-[var(--destructive)]">{managementError}</p>}</>}
    </Dialog>
  </FeaturePage>
}
