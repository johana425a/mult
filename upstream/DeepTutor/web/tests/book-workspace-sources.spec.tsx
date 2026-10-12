import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { initI18n } from '@/i18n/init'
import BookCreator from '@/app/(workspace)/learning/books/components/BookCreator'

initI18n('en')
vi.mock('@/context/AppShellContext', () => ({ useAppShell: () => ({ language: 'en' }) }))
vi.mock('@/components/workspaces/WorkspaceSourceStatus', () => ({ WorkspaceSourceStatus: () => <span>Bound workspace</span> }))
vi.mock('@/components/common/UnifiedModelControl', () => ({ UnifiedModelControl: () => <span>Model</span> }))
vi.mock('@/hooks/useTopicSourceLibrary', () => ({
  useTopicSourceLibrary: () => ({ library: {}, loading: false, candidates: [{ key: 'file', kind: 'workspace_file', path: 'lesson.docx', sourceId: 'lesson.docx' }], childLists: {}, loadChildren: vi.fn() }),
  toggleSourceSelection: (_selected: Set<string>, key: string) => new Set([key]),
  hydrateTopicSource: async () => ({ kind: 'workspace_file', source_id: 'lesson.docx', label: 'lesson.docx', metadata: { workspace_id: 'lesson', path: 'lesson.docx' } }),
}))
vi.mock('@/components/space/learning/TopicWizardSteps', () => ({ SourcesStep: ({ onToggle, automaticDiscovery }: { onToggle: (key: string) => void; automaticDiscovery: boolean }) => <div><button onClick={() => onToggle('file')}>Select workspace document</button><span>{String(automaticDiscovery)}</span></div> }))

it('requires a selected source for a workspace-based book instead of silently generating without materials', async () => {
  window.history.replaceState(null, '', '/learning/books?dt_workspace=lesson')
  const create = vi.fn()
  render(<BookCreator onCreate={create} />)
  expect(screen.getByLabelText('Create from materials')).toBeChecked()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Explain the chapter' } })
  fireEvent.click(screen.getByText('Generate proposal'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Choose at least one source below')
  expect(create).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Select workspace document'))
  fireEvent.click(screen.getByText('Generate proposal'))
  await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ source_mode: 'materials', source_refs: [expect.objectContaining({ kind: 'workspace_file' })] })))
})

it('allows an explicit general-knowledge book without pretending to use workspace files', async () => {
  window.history.replaceState(null, '', '/learning/books?dt_workspace=lesson')
  const create = vi.fn()
  render(<BookCreator onCreate={create} />)
  fireEvent.click(screen.getByLabelText('Create from a topic'))
  expect(screen.getByText(/does not claim to have read/)).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'A general introduction' } })
  fireEvent.click(screen.getByText('Generate proposal'))
  await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ source_mode: 'general', source_refs: [], knowledge_bases: [] })))
})
