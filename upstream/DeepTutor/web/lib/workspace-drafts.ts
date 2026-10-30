import { activeWorkspaceId } from './workspace-scope'
import { fetchAuthStatus } from './auth'

export type WorkspaceDraft = {
  text: string
  attachments: { filename: string; base64?: string; mimeType?: string }[]
}
async function key(workspaceId = activeWorkspaceId(), pathname = window.location.pathname): Promise<string> {
  const location = `${workspaceId}:${pathname}`
  const status = await fetchAuthStatus()
  if (!status || (status.enabled && (!status.authenticated || !status.user_id)))
    throw new Error('Account identity is unavailable for saving drafts.')
  return `${status.user_id || 'local-admin'}:${location}`
}

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('deeptutor-workspace-drafts', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('drafts')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function writeDraft(draftKey: string, draft: WorkspaceDraft, expectedText?: string): Promise<void> {
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('drafts', 'readwrite')
      const store = tx.objectStore('drafts')
      if (expectedText !== undefined) {
        // An older response must not remove a newer pending answer.
        const request = store.get(draftKey)
        request.onsuccess = () => {
          if (request.result?.text === expectedText) store.delete(draftKey)
        }
      } else if (draft.text || draft.attachments.length) store.put(draft, draftKey)
      else store.delete(draftKey)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

async function readDraft(draftKey: string): Promise<WorkspaceDraft | undefined> {
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', 'readonly')
      const store = tx.objectStore('drafts')
      const request = store.get(draftKey)
      tx.oncomplete = () => resolve(request.result)
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally {
    db.close()
  }
}

export async function saveWorkspaceDraft(draft: WorkspaceDraft, workspaceId?: string, pathname?: string): Promise<void> {
  await writeDraft(await key(workspaceId, pathname), draft)
}

export async function readWorkspaceDraft(workspaceId?: string, pathname?: string): Promise<WorkspaceDraft | undefined> {
  return readDraft(await key(workspaceId, pathname))
}

/** Bind identity while online, so an outage cannot change a pending write's owner. */
export async function openWorkspaceDraft(workspaceId: string, pathname: string) {
  const draftKey = await key(workspaceId, pathname)
  return {
    read: () => readDraft(draftKey),
    save: (draft: WorkspaceDraft) => writeDraft(draftKey, draft),
    clearIf: (text: string) => writeDraft(draftKey, { text: '', attachments: [] }, text),
  }
}

/** Move the current unsent message with an explicit composer assignment. */
export async function transferWorkspaceDraft(destination: string): Promise<void> {
  const source = activeWorkspaceId()
  if (source === destination) return
  const draft = await readWorkspaceDraft()
  if (!draft || (!draft.text && !draft.attachments.length)) return
  const prior = await readWorkspaceDraft(destination, '/chat')
  await saveWorkspaceDraft({
    text: [prior?.text, draft.text].filter(Boolean).join('\n\n'),
    attachments: [...(prior?.attachments || []), ...draft.attachments],
  }, destination, '/chat')
  await saveWorkspaceDraft({ text: '', attachments: [] })
}
