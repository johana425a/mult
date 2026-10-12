'use client'

/** Original competition addon. The native DeepTutor shell, chat, learning tools
 * and settings remain upstream features. Only explicit actions call models.
 * Modified for DeepSteam on 2026-10-10: user-facing settings names, concise AI
 * attribution, and a shared model / custom API switch. Upstream licenses retained. */
import Link from 'next/link'
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpen,
  Check,
  Download,
  FileText,
  Film,
  Loader2,
  Plus,
  Presentation,
  RefreshCw,
  Send,
  Settings2,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { FeaturePage, PageHeader, pageActionClass } from '@/components/layout/FeaturePage'
import { deepsteamService } from '@/lib/deepsteam-api'
import { safeServiceError } from '@/lib/deepsteam-transport'
import { classroomForm, languageSettingsPatch, narrationSettingsPatch, type ClassroomSettings, type ModelConnection } from '@/lib/model-connection'
import { ConnectionSummary } from './ConnectionSummary'
import { UnifiedModelControl } from '@/components/common/UnifiedModelControl'
import { ResolvedModelBadge } from '@/components/common/ResolvedModelBadge'
import type { LLMSelection } from '@/features/chat/model/protocol'
import type { ResolvedModel } from '@/lib/resolved-model'
import { useSurfaceModelSelection } from '@/hooks/useSurfaceModelSelection'
import { useLLMOptions } from '@/hooks/useLLMOptions'
import { sameLLMSelection } from '@/lib/llm-options'
import { PermanentDeleteMenu } from '@/components/ui/PermanentDeleteMenu'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { activeWorkspaceId } from '@/lib/workspace-scope'
import { WorkspaceMaterialPicker, sourceRangeLabel } from './WorkspaceMaterialPicker'

const API = `${deepsteamService(3791)}/api`
const inputClass =
  'w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-sm text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)] focus:border-[var(--ring)] focus:ring-1 focus:ring-[var(--ring)] disabled:opacity-50'
const panelClass = 'rounded-xl border border-[var(--border)] bg-[var(--card)]'
const secondary = pageActionClass('secondary')
const primary = pageActionClass('primary')

interface Material {
  id: string
  title: string
  filename: string
  char_count: number
  page_count?: number
  text_preview: string
  preview_truncated?: boolean
  sync_error?: string
  source_kind?: string
  workspace_id?: string
  source_status?: string
  source_locators?: Record<string, unknown>[]
  warnings?: string[]
}
interface MaterialDeleteResult {
  id: string
  deleted: boolean
  error?: string
  retained_shared?: boolean
}
interface Lesson {
  resolved_model?: ResolvedModel
  id: string
  title: string
  material_id: string
  goal: string
  status: string
  progress?: string
  error?: string
  warning?: string
  tts_coverage?: string
  classroom_id?: string
  review_required?: boolean | number
  source_fidelity?: string
  dt_course_id?: string
  job_id?: string
  job_attempt_id?: string
  retryable?: boolean | number
  recovery_message?: string
  created_at: string
}
interface Attempt {
  id: string
  lesson_id: string
  lesson_title: string
  question: string
  answer: string
  feedback?: string
  status: string
  error?: string
  dt_session_id?: string
  created_at: string
}
type Provider = ClassroomSettings
type Tab = 'classroom' | 'materials' | 'records' | 'settings'
type Items<T> = { items: T[] }
const emptyProvider: Provider = {
  connection_mode: 'current',
  base_url: '',
  model: '',
  tts_enabled: true,
  tts_mode: 'local',
  tts_base_url: '',
  tts_model: '',
  tts_voice: '',
}
const statusLabels: Record<string, string> = {
  queued: 'Queued',
  generating: 'Generating',
  ready: 'Ready to learn',
  failed: 'Generation failed',
  awaiting_reconnect: 'Waiting to reconnect',
  interrupted: 'Interrupted',
  grading: 'Preparing feedback',
  completed: 'Feedback ready',
  saved: 'Answer saved',
  deleting: 'Deleting · Retry if incomplete',
}
const pending = (status: string) => ['queued', 'generating', 'grading'].includes(status)
const retainedReview = (lesson: Lesson) => lesson.status === 'failed'
  && Boolean(lesson.review_required) && lesson.source_fidelity === 'needs_review'
  && Boolean(lesson.classroom_id && /^[a-zA-Z0-9_-]+$/.test(lesson.classroom_id))

function ErrorDetails({ message }: { message: string }) {
  return (
    <details className="text-sm text-[var(--muted-foreground)]">
      <summary className="cursor-pointer">View error details</summary>
      <p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed">
        {safeServiceError(message)}
      </p>
    </details>
  )
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(API + path, {
      cache: 'no-store',
      signal: AbortSignal.timeout(120000),
      ...options,
    })
  } catch {
    throw new Error(
      'The classroom service is currently unavailable. Reopen DeepSteam, then select Refresh. Other features remain available.'
    )
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok)
    throw new Error(
      typeof body.detail === 'string'
        ? safeServiceError(body.detail)
        : `Request failed (${response.status}). Try again later.`
    )
  return body as T
}
function json(value: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(value),
  }
}
function date(value: string) {
  return new Date(value).toLocaleString('en-US', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
function Status({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-1 text-[11px] ${value === 'ready' || value === 'completed' ? 'bg-[var(--success-surface)] text-[var(--success)]' : 'bg-[var(--muted)] text-[var(--muted-foreground)]'}`}
    >
      {pending(value) && <Loader2 size={11} className="animate-spin" />}
      {statusLabels[value] || value}
    </span>
  )
}
function Field({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-2">
      <span className="text-[13px] font-medium">{title}</span>
      {children}
      {hint && (
        <span className="block text-xs leading-relaxed text-[var(--muted-foreground)]">{hint}</span>
      )}
    </label>
  )
}

export function EducationStudio() {
  const [workspaceId, setWorkspaceId] = useState('')
  const [sourcePicker, setSourcePicker] = useState<'workspace' | 'range' | null>(null)
  const [rangeMaterialId, setRangeMaterialId] = useState('')
  const [maxMaterialBytes, setMaxMaterialBytes] = useState(200 * 1024 * 1024)
  useEffect(() => {
    setWorkspaceId(activeWorkspaceId())
    void request<{ max_bytes: number }>('/material-config').then(config => {
      if (Number.isFinite(config.max_bytes) && config.max_bytes > 0) setMaxMaterialBytes(config.max_bytes)
    }).catch(() => { /* Upload endpoint remains authoritative when configuration is temporarily unavailable. */ })
  }, [])
  // Stable app URLs during SSR/hydration; browser development resolves after mount.
  const [serviceOrigins, setServiceOrigins] = useState({ portal: 'deepsteam://portal', classroom: 'deepsteam://classroom' })
  useEffect(() => { setServiceOrigins({ portal: deepsteamService(3791), classroom: deepsteamService(3793) }) }, [])
  const API = `${serviceOrigins.portal}/api`
  const OPENMAIC = serviceOrigins.classroom
  const [tab, setTab] = useState<Tab>('classroom')
  const [materials, setMaterials] = useState<Material[]>([])
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<Set<string>>(new Set())
  const [confirmMaterialDelete, setConfirmMaterialDelete] = useState(false)
  const [materialDeleteErrors, setMaterialDeleteErrors] = useState<Record<string, string>>({})
  const [materialDeleteMessage, setMaterialDeleteMessage] = useState('')
  const materialDeleteInFlight = useRef(false)
  const [lessons, setLessons] = useState<Lesson[]>([])
  const [retryLessonTarget, setRetryLessonTarget] = useState<Lesson | null>(null)
  const [attempts, setAttempts] = useState<Attempt[]>([])
  const [settings, setSettings] = useState<Provider>(emptyProvider)
  const [form, setForm] = useState<Provider>(emptyProvider)
  const [connection, setConnection] = useState<ModelConnection | null>(null)
  const [key, setKey] = useState('')
  const [ttsKey, setTtsKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [clearTtsKey, setClearTtsKey] = useState(false)
  const [materialId, setMaterialId] = useState('')
  const [lessonId, setLessonId] = useState('')
  const [practiceId, setPracticeId] = useState('')
  const [title, setTitle] = useState('')
  const [goal, setGoal] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [preview, setPreview] = useState<Material | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [showVideo, setShowVideo] = useState(false)
  const uploadRef = useRef<HTMLInputElement>(null)
  const selectedMaterial = materials.find(item => item.id === materialId)
  const selectedLesson = lessons.find(item => item.id === lessonId)
  const unifiedClassroom = form.connection_mode === 'native' || form.connection_mode === 'current'
  const [classroomSelection, persistClassroomSelection] = useSurfaceModelSelection('classroom')
  const modelCatalog = useLLMOptions()
  const classroomOption = modelCatalog.options.find(option => sameLLMSelection(option, classroomSelection ?? modelCatalog.activeDefault))
  const configured = unifiedClassroom ? Boolean(classroomOption) && !modelCatalog.error : connection?.targets.classroom === 'selected'
  const selectClassroomModel = (selection: LLMSelection | null) => {
    void act('model-selection', async () => {
      const result = await request<Provider>('/settings', { ...json({ connection_mode: 'native' }), method: 'PUT' })
      persistClassroomSelection(selection)
      setSettings(result); setForm(previous => ({ ...previous, connection_mode: 'native' }))
      setConnection(await request<ModelConnection>('/models/connection'))
      setNotice('Classroom model selection saved for the next generation.')
    })
  }

  const refresh = useCallback(async () => {
    const [m, l, a] = await Promise.all([
      request<Items<Material>>(`/materials?workspace_id=${encodeURIComponent(workspaceId)}`),
      request<Items<Lesson>>(`/lessons?workspace_id=${encodeURIComponent(workspaceId)}`),
      request<Items<Attempt>>(`/attempts?workspace_id=${encodeURIComponent(workspaceId)}`),
    ])
    if (workspaceId !== activeWorkspaceId()) return
    setMaterials(m.items)
    setSelectedMaterialIds(current => new Set([...current].filter(id => m.items.some(item => item.id === id))))
    setLessons(l.items)
    setAttempts(a.items)
    setMaterialId(current => m.items.some(item => item.id === current) ? current : m.items[0]?.id || '')
    setPracticeId(current => current || l.items[0]?.id || '')
  }, [workspaceId])

  useEffect(() => {
    let alive = true
    void Promise.all([refresh(), request<Provider>('/settings'), request<ModelConnection>('/models/connection')])
      .then(([, config, current]) => {
        if (alive) {
          setSettings(config)
          setForm(classroomForm(config, current))
          setConnection(current)
        }
      })
      .catch(e => {
        if (alive) setError(e.message)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [refresh])

  const hasPending =
    lessons.some(item => pending(item.status)) || attempts.some(item => pending(item.status))
  useEffect(() => {
    if (!hasPending) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh().catch(e => setError(e.message))
    }, 4000)
    return () => window.clearInterval(timer)
  }, [hasPending, refresh])

  const act = async (name: string, work: () => Promise<void>) => {
    if (busy) return
    setBusy(name)
    setError('')
    setNotice('')
    try {
      await work()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The operation did not finish. Try again.')
    } finally {
      setBusy('')
    }
  }
  const chooseLesson = (item: Lesson) => {
    setLessonId(item.id)
    setPracticeId(item.id)
    setMaterialId(item.material_id)
    setTab('classroom')
    setShowVideo(false)
  }
  const deleteLesson = async (item: Lesson) => {
    await request(`/lessons/${encodeURIComponent(item.id)}`, { method: 'DELETE' })
    setLessonId(current => current === item.id ? '' : current)
    setPracticeId(current => current === item.id ? '' : current)
    setShowVideo(false)
    await refresh()
    setNotice('The classroom and its exclusive generated content were permanently deleted. Source materials were preserved.')
  }

  const deleteSelectedMaterials = async () => {
    if (materialDeleteInFlight.current || !selectedMaterialIds.size || busy) return
    materialDeleteInFlight.current = true
    setBusy('delete-materials')
    setMaterialDeleteMessage('')
    const ids = [...selectedMaterialIds]
    try {
      const result: Items<MaterialDeleteResult> = { items: [] }
      for (let offset = 0; offset < ids.length; offset += 200) {
        try {
          const batch = await request<Items<MaterialDeleteResult>>('/materials/delete', json({ ids: ids.slice(offset, offset + 200) }))
          if (Array.isArray(batch.items)) result.items.push(...batch.items)
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : 'Could not confirm deletion. Try again.'
          result.items.push(...ids.slice(offset).map(id => ({ id, deleted: false, error: message })))
          break
        }
      }
      const deleted = new Set(ids.filter(id => result.items?.some(item => item.id === id && item.deleted)))
      const failed = ids.filter(id => !deleted.has(id))
      const errors = Object.fromEntries(failed.map(id => [id,
        result.items?.find(item => item.id === id)?.error || 'Deletion of this material is not yet confirmed. Try again.']))
      setMaterialDeleteErrors(errors)
      setSelectedMaterialIds(new Set(failed))
      setMaterials(current => current.filter(item => !deleted.has(item.id)))
      setMaterialId(current => deleted.has(current) ? '' : current)
      setPreview(current => current && deleted.has(current.id) ? null : current)
      const message = `Deleted ${deleted.size} materials${failed.length ? `; ${failed.length} items are not confirmed deleted and remain selected.` : '.'}`
      const retained = result.items?.some(item => deleted.has(item.id) && item.retained_shared)
      setNotice(message + (retained ? ' Material copies in other learning features were retained.' : ''))
      if (failed.length) setMaterialDeleteMessage(message)
      else setConfirmMaterialDelete(false)
    } catch (reason) {
      setMaterialDeleteMessage(reason instanceof Error ? reason.message : 'Could not confirm deletion. Try again.')
    } finally {
      materialDeleteInFlight.current = false
      setBusy('')
    }
  }
  const upload = (file?: File) => {
    if (!file) return
    void act('upload', async () => {
      if (file.size > maxMaterialBytes) throw new Error(`File size must not exceed ${Math.floor(maxMaterialBytes / 1024 / 1024)} MB.`)
      const body = new FormData()
      body.append('file', file)
      const result = await request<Material>(`/materials?workspace_id=${encodeURIComponent(workspaceId)}`, { method: 'POST', body })
      await refresh()
      setMaterialId(result.id)
      setNotice('Material imported. Preview it and select the reading range for this classroom.')
      setRangeMaterialId(result.id); setSourcePicker('range')
    })
  }
  const createLesson = (event: FormEvent) => {
    event.preventDefault()
    void act('generate', async () => {
      const item = await request<Lesson>(
        '/lessons',
        json({
          material_id: materialId,
          title: title.trim() || selectedMaterial?.title || 'New interactive classroom',
          goal: goal.trim(),
          ...(unifiedClassroom ? { llm_selection: classroomSelection } : {}),
        })
      )
      await refresh()
      chooseLesson(item)
    })
  }
  const openDemo = () =>
    void act('demo', async () => {
      const item = await request<Lesson>('/demo-lesson', json({}))
      await refresh()
      chooseLesson(item)
    })
  const saveSettings = (event: FormEvent, section: 'language' | 'narration') => {
    event.preventDefault()
    void act(section, async () => {
      if (section === 'language' && form.connection_mode === 'custom' && (!form.base_url.trim() || !form.model.trim()))
        throw new Error('Enter the model  API  endpoint and model name.')
      if (
        section === 'narration' && form.tts_enabled &&
        form.tts_mode === 'api' &&
        (!form.tts_base_url.trim() || !form.tts_model.trim() || !form.tts_voice.trim())
      )
        throw new Error('Before enabling narration, enter the speech  API  endpoint, model and voice name.')
      if ((section === 'language' && clearKey && key.trim()) || (section === 'narration' && clearTtsKey && ttsKey.trim()))
        throw new Error('Choose either entering a new key or clearing the saved key.')
      const result = await request<Provider>('/settings', {
        ...json(section === 'language' ? languageSettingsPatch(form, key, clearKey) : narrationSettingsPatch(form, ttsKey, clearTtsKey)),
        method: 'PUT',
      })
      setSettings(result)
      const current = await request<ModelConnection>('/models/connection')
      setConnection(current)
      setForm(previous => section === 'language'
        ? { ...previous, ...classroomForm(result, current) }
        : { ...classroomForm(result, current), connection_mode: previous.connection_mode, base_url: previous.base_url, model: previous.model })
      setKey('')
      setTtsKey('')
      setClearKey(false)
      setClearTtsKey(false)
      setNotice(section === 'language' ? 'Classroom model connection saved.' : 'Narration settings saved. Learning and classroom model connections are unchanged.')
    })
  }
  const resumeLesson = (item: Lesson) =>
    void act('resume', async () => {
      await request(`/lessons/${encodeURIComponent(item.id)}/resume`, json({}))
      // The server schedules a background poll and can respond with the previous
      // state. Start client polling now; do not turn it off with an immediate GET.
      setLessons(current =>
        current.map(row =>
          row.id === item.id
            ? { ...row, status: 'generating', progress: 'Checking the original task again...' }
            : row
        )
      )
    })
  const retryLesson = (item: Lesson) =>
    void act('retry-lesson', async () => {
      const result = await request<Lesson>(`/lessons/${encodeURIComponent(item.id)}/retry`,
        json({ attempt_id: item.job_attempt_id }))
      setLessons(current => current.map(row => row.id === item.id ? result : row))
      setRetryLessonTarget(null)
    })
  const submitAnswer = (event: FormEvent) => {
    event.preventDefault()
    void act('answer', async () => {
      await request<Attempt>(
        `/lessons/${encodeURIComponent(practiceId)}/attempts`,
        json({ question: question.trim(), answer: answer.trim() })
      )
      setAnswer('')
      await refresh()
      setNotice('Your original answer is saved. Model feedback will appear in the records below.')
    })
  }
  const tabs: { id: Tab; label: string }[] = [
    { id: 'classroom', label: 'Interactive classroom' },
    { id: 'materials', label: 'Classroom materials' },
    { id: 'records', label: 'Answers and records' },
    { id: 'settings', label: 'Classroom settings' },
  ]

  return (
    <FeaturePage>
      <PageHeader
        title="Interactive classroom"
        description="Turn articles and handouts into illustrated classrooms with questions, practice and review."
        action={
          <>
            <button
              type="button"
              className={secondary}
              disabled={Boolean(busy)}
              onClick={() => void act('refresh', refresh)}
              aria-label="Refresh classroom materials and records"
            >
              <RefreshCw size={14} className={busy === 'refresh' ? 'animate-spin' : ''} />
              Refresh
            </button>
            <a href={OPENMAIC} target="_blank" rel="noreferrer" className={secondary}>
              Classroom center <ArrowUpRight size={14} />
            </a>
          </>
        }
      />
      <div className="mb-5">{unifiedClassroom ? <div className={`${panelClass} p-4`}><UnifiedModelControl value={classroomSelection} onChange={selectClassroomModel} surface="classroom" disabled={Boolean(busy)} label="Model for the next classroom generation" placement="bottom" /></div> : <ConnectionSummary connection={connection} />}</div>
      <input
        ref={uploadRef}
        type="file"
        className="hidden"
        accept=".pdf,.docx,.pptx,.md,.txt,.xlsx"
        aria-label="Upload classroom materials"
        onChange={e => {
          upload(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      {sourcePicker && <div className="mb-5"><WorkspaceMaterialPicker workspaceId={workspaceId}
        materialId={sourcePicker === 'range' ? rangeMaterialId : undefined}
        onCancel={() => setSourcePicker(null)} onSelected={id => {
          setSourcePicker(null)
          void act('select-source', async () => { await refresh(); setMaterialId(id); setNotice('Source range selected. The file version will be checked again when generating the classroom.') })
        }} /></div>}
      <nav
        aria-label="Interactive classroom page"
        className="mb-6 flex gap-1 overflow-x-auto border-b border-[var(--border)]"
      >
        {tabs.map(item => (
          <button
            key={item.id}
            type="button"
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => setTab(item.id)}
            className={`shrink-0 border-b-2 px-4 py-3 text-[13px] transition-colors ${tab === item.id ? 'border-[var(--primary)] font-medium text-[var(--foreground)]' : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]'}`}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {error && (
        <div
          role="alert"
          className="mb-5 flex gap-3 rounded-lg border border-[var(--destructive)]/30 bg-[var(--destructive)]/5 p-4 text-sm leading-relaxed"
        >
          <div className="flex-1 space-y-2">
            <p>The operation did not finish. Check the fields or try again later.</p>
            <ErrorDetails message={error} />
          </div>
          <button type="button" aria-label="Dismiss error" onClick={() => setError('')}>
            <X size={16} />
          </button>
        </div>
      )}
      {notice && (
        <div
          role="status"
          className="mb-5 flex items-start gap-2 rounded-lg bg-[var(--muted)] p-3 text-sm"
        >
          <Check size={16} className="mt-0.5 shrink-0" />
          {notice}
        </div>
      )}
      {loading && (
        <div
          role="status"
          className="flex items-center gap-2 py-5 text-sm text-[var(--muted-foreground)]"
        >
          <Loader2 size={16} className="animate-spin" />
          Loading classrooms and materials...
        </div>
      )}

      {tab === 'classroom' && (
        <div className="space-y-7">
          {selectedLesson ? (
            <section className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <button type="button" className={secondary} onClick={() => setLessonId('')}>
                  <ArrowLeft size={14} />
                  All classrooms
                </button>
                <label className="flex min-w-0 flex-1 items-center gap-3 sm:max-w-md">
                  <span className="sr-only">Switch classroom</span>
                  <select
                    className={inputClass}
                    value={lessonId}
                    onChange={e => {
                      const item = lessons.find(l => l.id === e.target.value)
                      if (item) chooseLesson(item)
                    }}
                  >
                    {lessons.map(l => (
                      <option key={l.id} value={l.id}>
                        {l.title}
                      </option>
                    ))}
                  </select>
                </label>
                <Status value={selectedLesson.status} />
              </div>
              <ResolvedModelBadge value={selectedLesson.resolved_model} />
              <div className="space-y-2 text-sm leading-relaxed text-[var(--muted-foreground)]">
                {selectedLesson.progress && <p>{selectedLesson.progress}</p>}
                {selectedLesson.recovery_message && <p>{safeServiceError(selectedLesson.recovery_message)}</p>}
                {selectedLesson.warning && (
                  <p className="rounded-lg bg-[var(--warning-surface)] p-3 text-[var(--warning-foreground)]">
                    {safeServiceError(selectedLesson.warning)}
                  </p>
                )}
                {selectedLesson.tts_coverage && <p>Narration coverage: {selectedLesson.tts_coverage}</p>}
                {selectedLesson.error && (
                  <div className="space-y-2">
                    {!retainedReview(selectedLesson) && (
                      <p className="text-[var(--destructive)]">The classroom task did not finish. Check the settings or try again later.</p>
                    )}
                    <ErrorDetails message={selectedLesson.error} />
                  </div>
                )}
                {selectedLesson.status === 'awaiting_reconnect' && (
                  <button
                    type="button"
                    disabled={Boolean(busy)}
                    className={secondary}
                    onClick={() => resumeLesson(selectedLesson)}
                  >
                    <RefreshCw size={14} />
                    Check the original task
                  </button>
                )}
                {['interrupted', 'failed'].includes(selectedLesson.status) && Boolean(selectedLesson.retryable)
                  && selectedLesson.job_attempt_id && (
                  <button type="button" disabled={Boolean(busy)} className={secondary}
                    onClick={() => setRetryLessonTarget(selectedLesson)}>
                    <RefreshCw size={14} /> Regenerate from the original source
                  </button>
                )}
                {selectedLesson.status === 'interrupted' && !selectedLesson.retryable && (
                  <p>This older task lacks complete recovery details. Materials and records are retained. Select the source again under Classroom materials to generate a new classroom.</p>
                )}
              </div>
              <ConfirmDialog open={Boolean(retryLessonTarget)} title="Regenerate this classroom?"
                confirmLabel="Regenerate" busy={busy === 'retry-lesson'} busyLabel="Submitting..."
                onCancel={() => setRetryLessonTarget(null)}
                onConfirm={() => retryLessonTarget && retryLesson(retryLessonTarget)}>
                Regenerate from the saved source range and language model. This may use model or narration credits again. Saved answers are retained.
              </ConfirmDialog>
              {selectedLesson.status === 'ready' && selectedLesson.classroom_id ? (
                <>
                  <div className={`${panelClass} overflow-hidden`}>
                    <iframe
                      key={selectedLesson.classroom_id}
                      title={`${selectedLesson.title} · Interactive classroom player`}
                      src={`${OPENMAIC}/classroom/${encodeURIComponent(selectedLesson.classroom_id)}`}
                      className="h-[76vh] min-h-[540px] w-full bg-[var(--background)]"
                      allow="fullscreen; autoplay; microphone"
                      allowFullScreen
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <a
                      href={`${OPENMAIC}/classroom/${encodeURIComponent(selectedLesson.classroom_id)}`}
                      target="_blank"
                      rel="noreferrer"
                      className={secondary}
                    >
                      Learn in a new window <ArrowUpRight size={14} />
                    </a>
                    <button type="button" className={primary} onClick={() => setTab('records')}>
                      <Send size={14} />
                      Answers and feedback
                    </button>
                    {selectedLesson.dt_course_id && (
                      <Link
                        href={`/courses/${encodeURIComponent(selectedLesson.dt_course_id)}`}
                        className={secondary}
                      >
                        <BookOpen size={14} />
                        DeepSteam Course
                      </Link>
                    )}
                  </div>
                </>
              ) : retainedReview(selectedLesson) ? (
                <div className={`${panelClass} space-y-4 p-6`}>
                  <h3 className="font-medium text-[var(--destructive)]">Generation failed · Draft awaiting verification</h3>
                  <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
                    The full draft was retained, but source verification has not passed. Compare its explanations, conditions and images with the original. This draft is not yet a completed classroom, and narration or video has not been generated automatically.
                  </p>
                  <a
                    href={`${OPENMAIC}/classroom/${encodeURIComponent(selectedLesson.classroom_id!)}`}
                    target="_blank"
                    rel="noreferrer"
                    className={secondary}
                  >
                    View draft awaiting verification <ArrowUpRight size={14} />
                  </a>
                </div>
              ) : (
                <div
                  className={`${panelClass} flex min-h-64 flex-col items-center justify-center gap-4 p-8 text-center`}
                >
                  {pending(selectedLesson.status) ? (
                    <Loader2 size={28} className="animate-spin text-[var(--primary)]" />
                  ) : (
                    <Presentation size={28} className="text-[var(--muted-foreground)]" />
                  )}
                  <p className="text-sm">
                    {pending(selectedLesson.status)
                      ? 'The classroom will appear automatically when ready. You can continue other work while it is prepared.'
                      : 'Materials and task details were retained.'}
                  </p>
                  <button type="button" className={secondary} onClick={() => setLessonId('')}>
                    Back to classrooms
                  </button>
                </div>
              )}
            </section>
          ) : (
            <>
              <form
                onSubmit={createLesson}
                className={`${panelClass} mx-auto max-w-3xl p-5 sm:p-7`}
              >
                <div className="mb-6 flex items-center gap-3">
                  <div className="rounded-xl bg-[var(--muted)] p-3">
                    <Presentation size={22} strokeWidth={1.5} />
                  </div>
                  <div>
                    <h2 className="font-serif text-xl font-semibold">What would you like to learn today?</h2>
                    <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                      Choose a source and tell the teacher what you want to learn.
                    </p>
                  </div>
                </div>
                <div className="space-y-5">
                  <Field title="Learning materials">
                    <div className="flex flex-wrap gap-2">
                      <select
                        aria-label="Select learning materials"
                        required
                        className={`${inputClass} min-w-0 flex-1 basis-48`}
                        value={materialId}
                        onChange={e => setMaterialId(e.target.value)}
                      >
                        <option value="">Select materials</option>
                        {materials.map(m => (
                          <option key={m.id} value={m.id}>
                            {m.title}
                          </option>
                        ))}
                      </select>
                      <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => setSourcePicker('workspace')}>Choose from workspace</button>
                      <button
                        type="button"
                        className={secondary}
                        disabled={Boolean(busy)}
                        onClick={() => uploadRef.current?.click()}
                      >
                        {busy === 'upload' ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Upload size={14} />
                        )}
                        Upload materials
                      </button>
                    </div>
                  </Field>
                  {selectedMaterial && <div className="space-y-2 text-xs text-[var(--muted-foreground)]">
                    <p>Classroom source range: {sourceRangeLabel(selectedMaterial.source_locators)}{selectedMaterial.preview_truncated ? '; only the selected range is included.' : ''}</p>
                    <button type="button" className="underline" disabled={Boolean(busy)} onClick={() => { setRangeMaterialId(selectedMaterial.id); setSourcePicker('range') }}>Preview and adjust the reading range</button>
                    {selectedMaterial.source_status === 'needs_ocr' && <p>This range lacks usable text. First complete  OCR  or select another range.</p>}
                  </div>}
                  {!unifiedClassroom && <p className="text-xs text-[var(--muted-foreground)]">Classroom-specific selection: {form.connection_mode === 'unconfigured' ? 'Select a model first' : form.model || connection?.model || 'Model not configured'} · <button type="button" className="underline" onClick={() => selectClassroomModel(null)}>Follow the global default</button></p>}
                  <Field title="Learning goals">
                    <textarea
                      rows={3}
                      required
                      maxLength={6000}
                      className={`${inputClass} resize-y`}
                      placeholder="For example: I am a beginner. Explain the core concepts with diagrams, then give me an application question."
                      value={goal}
                      onChange={e => setGoal(e.target.value)}
                    />
                  </Field>
                  <details className="text-sm">
                    <summary className="cursor-pointer text-[var(--muted-foreground)]">
                      Set a classroom name (optional)
                    </summary>
                    <input
                      aria-label="Classroom name"
                      maxLength={200}
                      className={`${inputClass} mt-3`}
                      placeholder={selectedMaterial?.title || 'Uses the source name by default'}
                      value={title}
                      onChange={e => setTitle(e.target.value)}
                    />
                  </details>
                  <div className="flex flex-wrap items-center justify-between gap-4 border-t border-[var(--border)] pt-5">
                    <p className="max-w-sm text-xs leading-relaxed text-[var(--muted-foreground)]">
                      {configured
                        ? 'Generation sends the selected materials and learning goals to the model above. The model is fixed when the task starts.'
                        : 'Try the example or configure your own model to generate a classroom.'}
                    </p>
                    {configured ? (
                      <button
                        type="submit"
                        className={primary}
                        disabled={Boolean(busy) || !materialId || !goal.trim()}
                      >
                        {busy === 'generate' ? (
                          <Loader2 size={15} className="animate-spin" />
                        ) : (
                          <Plus size={15} />
                        )}
                        Generate classroom
                      </button>
                    ) : (
                      <button type="button" className={primary} onClick={() => setTab('settings')}>
                        <Settings2 size={15} />
                        Configure classroom connection
                      </button>
                    )}
                  </div>
                </div>
              </form>
              <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-3 text-[13px]">
                <button
                  type="button"
                  disabled={Boolean(busy)}
                  onClick={openDemo}
                  className="inline-flex items-center gap-2 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  {busy === 'demo' ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <Presentation size={15} />
                  )}
                  Open example classroom
                </button>
                <button
                  type="button"
                  onClick={() => setShowVideo(current => !current)}
                  className="inline-flex items-center gap-2 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  <Film size={15} />
                  {showVideo ? 'Hide example video' : 'Watch a teaching video'}
                </button>
                <span className="text-[11px] text-[var(--muted-foreground)]">
                  Prebuilt example · No model calls
                </span>
              </div>
              {showVideo && (
                <div className={`${panelClass} mx-auto max-w-3xl overflow-hidden`}>
                  <video
                    controls
                    preload="metadata"
                    src={`${API}/demo-video`}
                    className="w-full"
                    aria-label="Prebuilt conditional probability teaching video"
                  />
                  <p className="px-4 py-3 text-xs text-[var(--muted-foreground)]">
                    Codex assisted authoring · Local speech synthesis
                  </p>
                </div>
              )}
              <section>
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold">My classrooms</h2>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {lessons.length} classrooms
                  </span>
                </div>
                {lessons.length ? (
                  <div className="divide-y divide-[var(--border)] rounded-xl border border-[var(--border)]">
                    {lessons.map(item => (
                      <PermanentDeleteMenu key={item.id} title={item.title} onOpen={() => chooseLesson(item)} onDelete={() => deleteLesson(item)} description="Permanently delete this classroom, its answers and generated files used only by it. Running generation will stop first. Original textbooks are retained. This cannot be undone.">
                      <button
                        type="button"
                        onClick={() => chooseLesson(item)}
                        className="flex w-full items-center gap-4 px-4 py-4 pr-10 text-left transition-colors first:rounded-t-xl last:rounded-b-xl hover:bg-[var(--muted)]/50"
                      >
                        <Presentation
                          size={19}
                          strokeWidth={1.5}
                          className="shrink-0 text-[var(--muted-foreground)]"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{item.title}</p>
                          <p className="mt-1 truncate text-xs text-[var(--muted-foreground)]">
                            {date(item.created_at)} ·{' '}
                            {materials.find(m => m.id === item.material_id)?.title || 'Classroom materials'}
                          </p>
                        </div>
                        <Status value={item.status} />
                      </button>
                      </PermanentDeleteMenu>
                    ))}
                  </div>
                ) : (
                  <p className="rounded-xl border border-dashed border-[var(--border)] py-9 text-center text-sm text-[var(--muted-foreground)]">
                    Your classrooms are saved here. Return anytime to continue learning.
                  </p>
                )}
              </section>
            </>
          )}
        </div>
      )}

      {tab === 'materials' && (
        <section className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Classroom materials</h2>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                Supports PDF, DOCX, PPTX, Markdown, TXT and XLSX. Maximum file size: {Math.floor(maxMaterialBytes / 1024 / 1024)} MB. Use files in the current workspace without uploading them again. Save legacy DOC/PPT files in a modern format first.
              </p>
            </div>
            <div className="flex flex-wrap gap-2"><button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => setSourcePicker('workspace')}>Choose from workspace</button><button
              type="button"
              className={primary}
              disabled={Boolean(busy)}
              onClick={() => uploadRef.current?.click()}
            >
              <Upload size={14} />
              Upload materials
            </button>
            </div>
          </div>
          {materials.length > 0 && (
            <div className={`${panelClass} flex flex-wrap items-center gap-3 p-3`} aria-label="Bulk material management">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" aria-label="Select all materials in the current list"
                  checked={selectedMaterialIds.size === materials.length}
                  ref={node => { if (node) node.indeterminate = selectedMaterialIds.size > 0 && selectedMaterialIds.size < materials.length }}
                  disabled={Boolean(busy)}
                  onChange={event => setSelectedMaterialIds(new Set(event.target.checked ? materials.map(item => item.id) : []))} />
                Select all in this list
              </label>
              <span className="text-sm text-[var(--muted-foreground)]" aria-live="polite">Selected {selectedMaterialIds.size} items</span>
              <button type="button" className={secondary} disabled={Boolean(busy) || !selectedMaterialIds.size}
                onClick={() => { setSelectedMaterialIds(new Set()); setMaterialDeleteErrors({}); setMaterialDeleteMessage('') }}>Clear selection</button>
              <button type="button" className={`${secondary} text-[var(--destructive)]`} disabled={Boolean(busy) || !selectedMaterialIds.size}
                onClick={() => { setMaterialDeleteMessage(''); setConfirmMaterialDelete(true) }}>
                <Trash2 size={14} />Delete selected
              </button>
            </div>
          )}
          <ConfirmDialog open={confirmMaterialDelete} title={`Permanently delete the selected  ${selectedMaterialIds.size}  materials?`}
            confirmLabel={materialDeleteMessage ? 'Retry remaining deletions' : 'Permanently delete selected items'} cancelLabel="Cancel"
            tone="danger" busy={busy === 'delete-materials'} busyLabel="Deleting..."
            onCancel={() => setConfirmMaterialDelete(false)} onConfirm={() => void deleteSelectedMaterials()}>
            <p>Permanently delete imported copies or workspace references and text previews from this list. Original textbooks and workspace folders stay intact. Delete associated classrooms first for materials already in use. Copies in other learning features are retained.</p>
            {materialDeleteMessage && <p role="alert" className="mt-3 text-[var(--destructive)]">{materialDeleteMessage}</p>}
            <div className="mt-3 max-h-[30vh] space-y-2 overflow-y-auto break-words" aria-label="Remaining material deletion details">
              {Object.entries(materialDeleteErrors).filter(([id]) => selectedMaterialIds.has(id)).map(([id, message]) =>
                <p key={id} className="text-xs">{materials.find(item => item.id === id)?.title || 'Material'}: {message}</p>)}
            </div>
          </ConfirmDialog>
          {materials.length ? (
            materials.map(item => (
              <article key={item.id} className={`${panelClass} p-4`}>
                <div className="flex items-start gap-3">
                  <input type="checkbox" className="mt-1.5 shrink-0" aria-label={`Select material: ${item.title}`}
                    checked={selectedMaterialIds.has(item.id)} disabled={Boolean(busy)}
                    onChange={event => setSelectedMaterialIds(current => {
                      const next = new Set(current)
                      if (event.target.checked) next.add(item.id); else next.delete(item.id)
                      return next
                    })} />
                  <FileText size={20} className="mt-1 shrink-0 text-[var(--muted-foreground)]" />
                  <div className="min-w-0 flex-1">
                    <h3 className="break-words text-sm font-medium">{item.title}</h3>
                    <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                      {item.filename} · {item.char_count.toLocaleString('en-US')} characters
                      {item.page_count ? ` · ${item.page_count} reading units` : ''}
                    </p>
                    {item.source_kind && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{item.source_kind === 'workspace' ? 'Original workspace file · ' : 'Upload materials · '}{sourceRangeLabel(item.source_locators)}{item.preview_truncated ? ' · Selected range' : ''}</p>}
                    {item.sync_error && (
                      <div className="mt-2 space-y-2">
                        <p className="text-xs text-[var(--warning-foreground)]">Material synchronization did not finish. Try again later.</p>
                        <ErrorDetails message={item.sync_error} />
                      </div>
                    )}
                    {materialDeleteErrors[item.id] && <p className="mt-2 text-xs text-[var(--destructive)]">{materialDeleteErrors[item.id]}</p>}
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className={primary}
                    disabled={Boolean(busy)}
                    onClick={() => {
                      setMaterialId(item.id)
                      setLessonId('')
                      setTab('classroom')
                    }}
                  >
                    Create a classroom from this
                  </button>
                  <button
                    type="button"
                    className={secondary}
                    disabled={Boolean(busy)}
                    onClick={() =>
                      void act('preview', async () =>
                        setPreview(
                          await request<Material>(`/materials/${encodeURIComponent(item.id)}`)
                        )
                      )
                    }
                  >
                    View text
                  </button>
                  <button type="button" className={secondary} disabled={Boolean(busy)} onClick={() => { setRangeMaterialId(item.id); setSourcePicker('range') }}>Choose reading range</button>
                  {item.source_kind !== 'workspace' && <a
                    className={secondary}
                    href={`${API}/materials/${encodeURIComponent(item.id)}/file`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Download size={14} />
                    Original file
                  </a>}
                </div>
              </article>
            ))
          ) : (
            <div
              className={`${panelClass} py-12 text-center text-sm text-[var(--muted-foreground)]`}
            >
              Upload your own materials or 
              <button
                type="button"
                disabled={Boolean(busy)}
                onClick={() =>
                  void act('demo-material', async () => {
                    const item = await request<Material>('/demo-material', json({}))
                    await refresh()
                    setMaterialId(item.id)
                  })
                }
                className="ml-1 underline underline-offset-4"
              >
                import the public example handout
              </button>
              .
            </div>
          )}
          {preview && (
            <section className={`${panelClass} p-5`} aria-label="Material text preview">
              <div className="mb-4 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">{preview.title}</h3>
                <button
                  type="button"
                  aria-label="Close material preview"
                  onClick={() => setPreview(null)}
                  className={secondary}
                >
                  <X size={14} />
                </button>
              </div>
              <p className="mb-3 text-xs text-[var(--muted-foreground)]">
                The text preview does not display images. Generation checks the original file version and reads only the selected range and its images.
                {preview.preview_truncated && 'Only part of the text is displayed here.'}
              </p>
              <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-7">
                {preview.text_preview}
              </pre>
            </section>
          )}
        </section>
      )}

      {tab === 'records' && (
        <section className="space-y-7">
          <form onSubmit={submitAnswer} className={`${panelClass} max-w-3xl space-y-5 p-5 sm:p-6`}>
            <h2 className="text-sm font-semibold">Submit classroom answer</h2>
            <Field title="Classroom">
              <select
                required
                className={inputClass}
                value={practiceId}
                onChange={e => setPracticeId(e.target.value)}
              >
                <option value="">Select a classroom</option>
                {lessons.map(l => (
                  <option key={l.id} value={l.id}>
                    {l.title}
                  </option>
                ))}
              </select>
            </Field>
            <Field title="Question">
              <textarea
                rows={2}
                className={inputClass}
                maxLength={12000}
                required
                value={question}
                onChange={e => setQuestion(e.target.value)}
                placeholder="Enter the question you are answering"
              />
            </Field>
            <Field title="My answer">
              <textarea
                rows={4}
                className={inputClass}
                maxLength={30000}
                required
                value={answer}
                onChange={e => setAnswer(e.target.value)}
                placeholder="Write your own understanding first, then receive feedback"
              />
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-md text-xs leading-relaxed text-[var(--muted-foreground)]">
                Your original answer is saved first. The question, answer and related materials are then sent to the configured model.
              </p>
              {configured ? (
                <button
                  type="submit"
                  className={primary}
                  disabled={Boolean(busy) || !practiceId || !question.trim() || !answer.trim()}
                >
                  <Send size={14} />
                  Save and get feedback
                </button>
              ) : (
                <button type="button" className={secondary} onClick={() => setTab('settings')}>
                  Configure the classroom connection first
                </button>
              )}
            </div>
          </form>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Learning records · {attempts.length}</h2>
            <a href={`${API}/export-records`} download className={secondary}>
              <Download size={14} />
              Export learning records
            </a>
          </div>
          {attempts.length ? (
            <div className="space-y-3">
              {attempts.map(item => (
                <details key={item.id} className={`${panelClass} p-4`}>
                  <summary className="flex cursor-pointer list-none items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm font-medium">{item.question}</p>
                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                        {item.lesson_title} · {date(item.created_at)}
                      </p>
                    </div>
                    <Status value={item.status} />
                  </summary>
                  <div className="mt-5 space-y-4 border-t border-[var(--border)] pt-4 text-sm leading-7">
                    <div>
                      <h3 className="mb-1 text-xs font-semibold text-[var(--muted-foreground)]">
                        Original answer
                      </h3>
                      <p className="whitespace-pre-wrap break-words">{item.answer}</p>
                    </div>
                    {item.feedback && (
                      <div>
                        <h3 className="mb-1 text-xs font-semibold text-[var(--muted-foreground)]">
                          Teacher feedback
                        </h3>
                        <p className="whitespace-pre-wrap break-words">{item.feedback}</p>
                      </div>
                    )}
                    {item.error && (
                      <div className="space-y-2">
                        <p className="text-xs text-[var(--warning-foreground)]">Your answer was saved; feedback is not ready yet.</p>
                        <ErrorDetails message={item.error} />
                      </div>
                    )}
                    {item.dt_session_id && (
                      <Link
                        href={`/chat/${encodeURIComponent(item.dt_session_id)}`}
                        className={secondary}
                      >
                        In  DeepSteam Continue in <ArrowUpRight size={14} />
                      </Link>
                    )}
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">
              No classroom answers yet. Your original answers and feedback appear here after submission.
            </p>
          )}
        </section>
      )}

      {tab === 'settings' && (
        <section className="mx-auto max-w-3xl space-y-5">
          <div className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            <p>
              Choose the classroom model and enable narration if needed.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Link href="/settings" className={secondary}>
                Model settings <ArrowUpRight size={14} />
              </Link>
              <a href={OPENMAIC} target="_blank" rel="noreferrer" className={secondary}>
                More classroom settings <ArrowUpRight size={14} />
              </a>
            </div>
          </div>
          <form onSubmit={event => saveSettings(event, 'language')} className="space-y-5">
            <div className={`${panelClass} space-y-5 p-5 sm:p-6`}>
              <div>
                <h2 className="text-sm font-semibold">Classroom language model</h2>
                <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                  Uses the same default model as other learning features, with an optional classroom-specific selection. Narration is configured separately.
                </p>
              </div>
              {unifiedClassroom && <UnifiedModelControl value={classroomSelection} onChange={selectClassroomModel} surface="classroom" disabled={Boolean(busy)} label="Classroom model" placement="bottom" />}
              <Field title="Advanced connection method">
                <select
                  className={inputClass}
                  value={form.connection_mode || 'current'}
                  onChange={e => setForm({ ...form, connection_mode: e.target.value as Provider['connection_mode'] })}
                >
                  <option value="current">Shared model catalog (follow the default or choose separately)</option>
                  <option value="native">Shared model catalog (follow the default or choose separately)</option>
                  <option value="unconfigured" disabled>No model selected</option>
                  <option value="custom">Classroom-specific custom  API</option>
                </select>
              </Field>
              {unifiedClassroom && <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">The selected model appears above. Changes are saved immediately and affect only the next generation.<Link href="/settings" className="ml-1 underline">Full model and API settings</Link></p>}
              {form.connection_mode === 'unconfigured' && (
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                  Select a model from the shared catalog or enter your own API endpoint.<Link href="/connect" className="ml-1 underline">Connect DeepSeek</Link>
                </p>
              )}
              {form.connection_mode === 'custom' && <div className="space-y-5">
              <Field title="API  endpoint">
                <input
                  className={inputClass}
                  type="url"
                  placeholder="https://api.example.com/v1"
                  value={form.base_url}
                  onChange={e => setForm({ ...form, base_url: e.target.value })}
                />
              </Field>
              <Field title="Model name">
                <input
                  className={inputClass}
                  placeholder="Enter the model  ID"
                  value={form.model}
                  onChange={e => setForm({ ...form, model: e.target.value })}
                />
              </Field>
              <Field
                title="API key"
                hint={
                  settings.api_key_set
                    ? 'An API key is already saved. Leave this blank to keep it. The key is never displayed.'
                    : 'Leave blank if the service does not require a key.'
                }
              >
                <input
                  className={inputClass}
                  type="password"
                  autoComplete="new-password"
                  value={key}
                  onChange={e => setKey(e.target.value)}
                  placeholder={settings.api_key_set ? 'Saved · Leave blank to keep unchanged' : 'Enter  API key'}
                />
              </Field>
              {settings.api_key_set && (
                <label className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
                  <input
                    type="checkbox"
                    checked={clearKey}
                    onChange={e => setClearKey(e.target.checked)}
                  />
                  Clear the saved model key when saving
                </label>
              )}
              </div>}
              <button type="submit" className={primary} disabled={Boolean(busy)}>{busy === 'language' && <Loader2 size={14} className="animate-spin" />}Save classroom model</button>
            </div>
          </form>
          <form onSubmit={event => saveSettings(event, 'narration')} className="space-y-5">
            <div className={`${panelClass} space-y-5 p-5 sm:p-6`}>
              <label className="flex items-center justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold">Classroom narration</span>
                  <span className="mt-1 block text-xs text-[var(--muted-foreground)]">
                    Local English narration requires no API. You can also use your own speech service.
                  </span>
                </span>
                <input
                  type="checkbox"
                  aria-label="Enable classroom narration"
                  checked={form.tts_enabled}
                  onChange={e => setForm({ ...form, tts_enabled: e.target.checked })}
                />
              </label>
              {form.tts_enabled && (
                <>
                  <Field title="Narration method">
                    <select className={inputClass} value={form.tts_mode || 'local'} onChange={e => setForm({ ...form, tts_mode: e.target.value as 'local' | 'api' })}>
                      <option value="local">Local English voice</option>
                      <option value="api">Your speech  API</option>
                    </select>
                  </Field>
                  {form.tts_mode !== 'api' && <p className="text-xs text-[var(--muted-foreground)]">Use  Windows installed English voices. If none are available, the app asks you to install one and does not automatically use a cloud service.</p>}
                  {form.tts_mode === 'api' && <>
                  <Field title="Speech API  endpoint">
                    <input
                      className={inputClass}
                      type="url"
                      value={form.tts_base_url}
                      onChange={e => setForm({ ...form, tts_base_url: e.target.value })}
                    />
                  </Field>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field title="Speech model">
                      <input
                        className={inputClass}
                        value={form.tts_model}
                        onChange={e => setForm({ ...form, tts_model: e.target.value })}
                      />
                    </Field>
                    <Field title="Voice name">
                      <input
                        className={inputClass}
                        value={form.tts_voice}
                        onChange={e => setForm({ ...form, tts_voice: e.target.value })}
                      />
                    </Field>
                  </div>
                  <Field
                    title="Speech API key"
                    hint={
                      settings.tts_key_set
                        ? 'An API key is saved. Leave this blank to keep it.'
                        : 'Enter separately if required by the service.'
                    }
                  >
                    <input
                      className={inputClass}
                      type="password"
                      autoComplete="new-password"
                      value={ttsKey}
                      onChange={e => setTtsKey(e.target.value)}
                      placeholder={settings.tts_key_set ? 'Saved · Leave blank to keep unchanged' : ''}
                    />
                  </Field>
                  {settings.tts_key_set && (
                    <label className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
                      <input
                        type="checkbox"
                        checked={clearTtsKey}
                        onChange={e => setClearTtsKey(e.target.checked)}
                      />
                      Clear the saved speech key when saving
                    </label>
                  )}
                  </>}
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-[var(--muted-foreground)]">
                Saving updates configuration only and does not call the model.
              </p>
              <button type="submit" className={primary} disabled={Boolean(busy)}>
                {busy === 'narration' ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )}
                Save narration settings
              </button>
            </div>
          </form>
        </section>
      )}
      <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-4 text-[11px] text-[var(--muted-foreground)]">
        <span>DeepSteam · This project was AIassisted generation · Primary tools: Codex</span>
        <a
          href={`${serviceOrigins.portal}/legacy`}
          target="_blank"
          rel="noreferrer"
          className="hover:underline"
        >
          Alternative workbench
        </a>
      </footer>
    </FeaturePage>
  )
}
