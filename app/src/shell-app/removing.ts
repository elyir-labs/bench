// Remove, done (design/printers-remove/, A): off this phone's list, and the printer told to forget this phone.

import { shallowRef } from 'vue'
import { forgetPrinter, recordOf, savePrinter, type LivePrinter, type PrinterRecord } from './printers'
import { canUndo, caseOf, toastWords } from './remove'
import { account, call, refreshAccount } from './account'

export interface Removed {
  record: PrinterRecord
  words: string
  undo: boolean
}
// shallow: the record goes back into IndexedDB as it is, which can't store Vue's proxies
export const removed = shallowRef<Removed | null>(null)

/** The printer forgets this phone; false when it couldn't (out of reach now, or a release without DELETE /door/me). */
async function offThePrinter(p: LivePrinter): Promise<boolean> {
  try {
    const r = await fetch(`${p.base}/door/me`, {
      method: 'DELETE', headers: { Authorization: `Bearer ${p.token}` }, cache: 'no-store', signal: AbortSignal.timeout(8000),
    })
    return r.ok || r.status === 401     // 401: it didn't know this phone any more either
  } catch {
    return false
  }
}

/** In the account signed in here: Remove takes it out of the account, or it would come straight back. */
export function inAccount(p: Pick<LivePrinter, 'account' | 'house'>): boolean {
  return !!p.account && account.state === 'in' && account.me?.house?.id === p.house
}

export async function removePrinter(p: LivePrinter, alsoOff: boolean): Promise<void> {
  const c = caseOf(p)
  if (inAccount(p)) {
    await call('DELETE', `/v1/devices/${encodeURIComponent(p.account!)}`)
    if (c === 'reachable') await offThePrinter(p)
    await forgetPrinter(p.id)
    removed.value = { record: recordOf(p), words: toastWords(p.name, false, true), undo: false }
    void refreshAccount()
    return
  }
  const stillKnown = c === 'reachable' && alsoOff && !(await offThePrinter(p))
  const record = recordOf(p)
  await forgetPrinter(p.id)
  removed.value = { record, words: toastWords(p.name, stillKnown), undo: canUndo(c, alsoOff, stillKnown) }
}

export async function undoRemove(): Promise<void> {
  const r = removed.value
  removed.value = null
  if (r) await savePrinter(r.record)
}
