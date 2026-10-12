import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Book, Page } from '@/lib/book-types'
import type { StreamEvent } from '@/features/chat/model/protocol'
import { initI18n } from '@/i18n/init'

initI18n('en')

const mocks = vi.hoisted(() => ({
  send: vi.fn(), getSession: vi.fn(), saveSessionModel: vi.fn(),
  event: null as ((event: StreamEvent) => void) | null,
}))
vi.mock('@/context/AppShellContext', () => ({ useAppShell: () => ({ language: 'en' }) }))
vi.mock('@/components/workspaces/WorkspaceSourceStatus', () => ({ WorkspaceSourceStatus: () => null }))
vi.mock('@/lib/session-api', () => ({ getSession: mocks.getSession }))
vi.mock('@/lib/attachment-limits', () => ({ useAttachmentLimits: () => ({ maxAttachments: 5, maxFileBytes: 10000, maxTotalBytes: 50000 }) }))
vi.mock('@/components/common/AssistantResponse', () => ({ default: ({ content }: { content: string }) => <div>{content}</div> }))
vi.mock('@/components/common/UnifiedModelControl', () => ({
  UnifiedModelControl: ({ value, onChange, disabled }: { value: unknown; onChange: (value: unknown) => void; disabled?: boolean }) => <div>
    <span data-testid="selection">{JSON.stringify(value)}</span>
    <button type="button" disabled={disabled} onClick={() => onChange({ profile_id: 'fixture', model_id: 'chosen' })}>Choose model</button>
    <button type="button" disabled={disabled} onClick={() => onChange(null)}>Follow default</button>
  </div>,
}))
vi.mock('@/lib/resolved-model', async (original) => ({ ...(await original<object>()), saveSessionModel: mocks.saveSessionModel }))
vi.mock('@/features/chat/transport/UnifiedTurnClient', () => ({
  UnifiedTurnClient: class {
    connected = true
    constructor(event: (event: StreamEvent) => void) { mocks.event = event }
    connect() {}
    disconnect() {}
    send = mocks.send
  },
}))

const { default: BookChatPanel } = await import('@/app/(workspace)/learning/books/components/BookChatPanel')
const book = { id: 'book', title: 'Book', language: 'en', knowledge_bases: [] } as unknown as Book
const page = { id: 'page', title: 'Page' } as unknown as Page
const identity = { provider: 'openai', provider_label: 'OpenAI', model: 'recorded-model', model_name: 'recorded-model', selection_source: 'override' }

describe('Book page model routing', () => {
  beforeEach(() => {
    mocks.send.mockReset()
    mocks.getSession.mockReset()
    mocks.saveSessionModel.mockReset().mockResolvedValue({ available: true })
    mocks.event = null
  })

  it('starts in inherited mode and includes a selected override in the actual turn request', async () => {
    render(<BookChatPanel book={book} page={page} open onClose={() => {}} />)
    expect(screen.getByTestId('selection').textContent).toBe('null')
    fireEvent.click(screen.getByText('Choose model'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Explain this page' } })
    fireEvent.submit(screen.getByRole('textbox').closest('form')!)
    expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({
      llm_selection: { profile_id: 'fixture', model_id: 'chosen' },
      book_references: [{ book_id: 'book', page_ids: ['page'] }],
    }))
  })

  it('sends the saved book workspace even when the surrounding URL names a different folder', () => {
    window.history.replaceState(null, '', '/learning/books?dt_workspace=other')
    render(<BookChatPanel book={{ ...book, content_workspace_id: 'original' }} page={page} open onClose={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Read its source' } })
    fireEvent.submit(screen.getByRole('textbox').closest('form')!)
    expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({ workspace_id: 'original' }))
    window.history.replaceState(null, '', '/learning/books')
  })

  it('restores the conversation choice and saved reply identity without using the current default', async () => {
    mocks.getSession.mockResolvedValue({
      preferences: { llm_selection: { profile_id: 'fixture', model_id: 'old-choice' } },
      messages: [{ role: 'assistant', content: 'Recorded answer', metadata: { resolved_model: identity }, events: [] }],
    })
    render(<BookChatPanel book={book} page={page} open onClose={() => {}} initialSessionId="session" />)
    await screen.findByText('Recorded answer')
    expect(screen.getByTestId('selection').textContent).toContain('old-choice')
    expect(screen.getByText('OpenAI · recorded-model')).toBeTruthy()
    fireEvent.click(screen.getByText('Follow default'))
    await waitFor(() => expect(mocks.saveSessionModel).toHaveBeenCalledWith('session', null))
    await waitFor(() => expect(screen.getByTestId('selection').textContent).toBe('null'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Continue' } })
    fireEvent.submit(screen.getByRole('textbox').closest('form')!)
    expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({ llm_selection: null }))
    expect(screen.getByText('OpenAI · recorded-model')).toBeTruthy()
  })

  it('keeps the saved selection when a preference update fails', async () => {
    mocks.getSession.mockResolvedValue({ preferences: { llm_selection: null }, messages: [] })
    mocks.saveSessionModel.mockRejectedValue(new Error('Fixture save failure'))
    render(<BookChatPanel book={book} page={page} open onClose={() => {}} initialSessionId="session" />)
    await waitFor(() => expect((screen.getByText('Choose model') as HTMLButtonElement).disabled).toBe(false))
    fireEvent.click(screen.getByText('Choose model'))
    await screen.findByRole('alert')
    expect(screen.getByTestId('selection').textContent).toBe('null')
  })

  it('displays the server dispatch identity on a newly streamed answer', async () => {
    render(<BookChatPanel book={book} page={page} open onClose={() => {}} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Explain' } })
    fireEvent.submit(screen.getByRole('textbox').closest('form')!)
    act(() => {
      mocks.event?.({ type: 'session', timestamp: 1, metadata: { session_id: 'created', resolved_model: identity }, content: '', source: '', stage: '' })
      mocks.event?.({ type: 'content', timestamp: 2, metadata: {}, content: 'Generated fixture answer', source: 'chat', stage: 'responding' })
      mocks.event?.({ type: 'done', timestamp: 3, metadata: {}, content: '', source: '', stage: '' })
    })
    expect(screen.getByText('OpenAI · recorded-model')).toBeTruthy()
  })
})
