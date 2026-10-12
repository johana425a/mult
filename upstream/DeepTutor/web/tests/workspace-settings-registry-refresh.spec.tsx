import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import WorkspaceSettingsSection from '@/features/settings/sections/WorkspaceSettingsSection'
import { notifySessionsChanged } from '@/lib/session-events'

const fixture = vi.hoisted(() => ({ catalog: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/workspaces/WorkspaceResourcePicker', () => ({ WorkspaceResourcePicker: () => null }))
vi.mock('@/components/workspaces/SystemWorkspaceSnapshot', () => ({ SystemWorkspaceSnapshot: () => null }))
vi.mock('@/lib/deepsteam-desktop', () => ({ canPickWorkspaceDirectory: () => false }))
vi.mock('@/lib/workspaces-api', async () => ({
  ...await vi.importActual<typeof import('@/lib/workspaces-api')>('@/lib/workspaces-api'),
  getWorkspaceCatalog: fixture.catalog,
}))
const row = { workspace_id: 'native-fixture', kind: 'workspace', follows_root: false, display_name: 'Fixture', path: 'D:\\Fixture', archived: false, created_at: '', status: 'ready', error: '' }
const catalog = { root: 'D:\\Root', workspaces: [row] }
beforeEach(() => { fixture.catalog.mockReset(); fixture.catalog.mockResolvedValue(catalog) })

it('reflects external rename, archive and restore in mounted settings', async () => {
  render(<WorkspaceSettingsSection />)
  await screen.findByRole('article', { name: 'Fixture' })
  fixture.catalog.mockResolvedValue({ ...catalog, workspaces: [{ ...row, display_name: 'Renamed in sidebar' }] })
  act(() => notifySessionsChanged())
  await screen.findByRole('article', { name: 'Renamed in sidebar' })
  fixture.catalog.mockResolvedValue({ ...catalog, workspaces: [{ ...row, display_name: 'Renamed in sidebar', archived: true }] })
  act(() => notifySessionsChanged())
  await screen.findByRole('button', { name: 'Restore workspace' })
  expect(within(screen.getByRole('article', { name: 'Renamed in sidebar' })).getByText('Archived')).toBeVisible()
  fixture.catalog.mockResolvedValue(catalog)
  act(() => notifySessionsChanged())
  await screen.findByRole('button', { name: 'Archive workspace' })
  expect(screen.queryByRole('button', { name: 'Restore workspace' })).not.toBeInTheDocument()
})

it('keeps the newest registry result when a slower refresh completes last', async () => {
  let finish!: (value: typeof catalog) => void
  fixture.catalog.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  render(<WorkspaceSettingsSection />)
  fixture.catalog.mockResolvedValue({ ...catalog, workspaces: [{ ...row, display_name: 'Latest name', archived: true }] })
  act(() => notifySessionsChanged())
  await screen.findByRole('article', { name: 'Latest name' })
  await act(async () => finish(catalog))
  expect(screen.queryByRole('article', { name: 'Fixture' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Restore workspace' })).toBeVisible()
})

it('does not reset a root migration draft when a sidebar mutation refreshes settings', async () => {
  render(<WorkspaceSettingsSection />)
  await screen.findByRole('article', { name: 'Fixture' })
  fireEvent.change(screen.getByRole('textbox', { name: 'Workspace root folder' }), { target: { value: 'D:\\TypedDestination' } })
  fixture.catalog.mockResolvedValue({ ...catalog, workspaces: [{ ...row, display_name: 'Latest name' }] })
  act(() => notifySessionsChanged())
  await screen.findByRole('article', { name: 'Latest name' })
  expect(screen.getByRole('textbox', { name: 'Workspace root folder' })).toHaveValue('D:\\TypedDestination')
})

it('unsubscribes on unmount and ignores a rejected obsolete refresh', async () => {
  let reject!: (error: Error) => void
  fixture.catalog.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  const page = render(<WorkspaceSettingsSection />)
  page.unmount()
  await act(async () => reject(new Error('late failed read')))
  act(() => notifySessionsChanged())
  expect(fixture.catalog).toHaveBeenCalledTimes(1)
})
