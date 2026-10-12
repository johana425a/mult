import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { PermanentDeleteMenu } from '@/components/ui/PermanentDeleteMenu'

it('requires one confirmation, suppresses duplicate requests and keeps failure retry visible', async () => {
  let reject!: (reason: Error) => void
  const remove = vi.fn().mockImplementationOnce(() => new Promise((_, fail) => { reject = fail })).mockResolvedValueOnce(undefined)
  const open = vi.fn()
  render(<PermanentDeleteMenu title="Fixture" description="Permanent deletion; originals remain." onDelete={remove} onOpen={open}><button onClick={open}>Fixture content</button></PermanentDeleteMenu>)
  fireEvent.contextMenu(screen.getByRole('button', { name: 'Fixture content' }))
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete permanently' }))
  expect(remove).not.toHaveBeenCalled()
  expect(open).not.toHaveBeenCalled()
  const confirm = screen.getByRole('button', { name: 'Delete permanently' })
  fireEvent.click(confirm); fireEvent.click(confirm)
  expect(remove).toHaveBeenCalledOnce()
  await act(async () => { reject(new Error('Fixture cleanup blocked')); })
  expect(screen.getByRole('alert')).toHaveTextContent('Fixture cleanup blocked')
  fireEvent.click(screen.getByRole('button', { name: 'Retry deletion' }))
  await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  expect(remove).toHaveBeenCalledTimes(2)
})
