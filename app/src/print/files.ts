// The Print library's Moonraker calls, with the call passed in so tests can fake Moonraker.
//
//   files     server.files.get_directory (extended: metadata comes with each file), folder by
//             folder; server.files.list plus server.files.metadata on a Moonraker that refuses it
//   history   server.history.list, for how often and when
//   remove    server.files.delete_file, at home only (the door refuses it from away too), then
//             the name goes on elyir-bench/print_hidden so it leaves Recent as well
//   hidden    elyir-bench/print_hidden: past prints taken off Recent. History itself is never touched.
import type { FileMeta, PastJob, PrinterFile } from './library.ts'
import { hide } from './library.ts'

export type Call = <T = any>(method: string, params?: Record<string, unknown>) => Promise<T>

export const HIDDEN = { namespace: 'elyir-bench', key: 'print_hidden' }
const HISTORY_LIMIT = 500
const MAX_DEPTH = 4

interface DirFile extends FileMeta { filename: string; modified: number }
interface Directory { dirs?: { dirname: string }[]; files?: DirFile[] }

const hiddenName = (n: string) => n.startsWith('.')

async function walk(call: Call, folder: string, depth: number): Promise<PrinterFile[]> {
  const d = await call<Directory>('server.files.get_directory', { path: folder ? `gcodes/${folder}` : 'gcodes', extended: true })
  const here: PrinterFile[] = (d?.files ?? [])
    .filter(f => f?.filename && !hiddenName(f.filename) && /\.(gcode|gco|g|ufp)$/i.test(f.filename))
    .map(({ filename, modified, ...meta }) => ({ path: folder ? `${folder}/${filename}` : filename, modified, meta: meta as FileMeta }))
  if (depth >= MAX_DEPTH) return here
  const below = await Promise.all((d?.dirs ?? [])
    .filter(x => x?.dirname && !hiddenName(x.dirname))
    .map(x => walk(call, folder ? `${folder}/${x.dirname}` : x.dirname, depth + 1).catch(() => [] as PrinterFile[])))
  return here.concat(...below)
}

/** In batches, so a printer with hundreds of files isn't asked hundreds of things at once. */
export async function inBatches<T, R>(list: T[], size: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = []
  for (let i = 0; i < list.length; i += size) out.push(...await Promise.all(list.slice(i, i + size).map(fn)))
  return out
}

/** Every file under the gcodes root, with its metadata. */
export async function listFiles(call: Call): Promise<PrinterFile[]> {
  try {
    return await walk(call, '', 0)
  } catch {
    const list = await call<{ path: string; modified: number }[]>('server.files.list', { root: 'gcodes' })
    const files = (list ?? []).filter(f => f?.path && !f.path.split('/').some(hiddenName))
    return inBatches(files, 6, async f => ({
      path: f.path,
      modified: f.modified,
      meta: await call<FileMeta>('server.files.metadata', { filename: f.path }).catch(() => null),
    }))
  }
}

export async function pastJobs(call: Call): Promise<PastJob[]> {
  try {
    const r = await call<{ jobs: PastJob[] }>('server.history.list', { limit: HISTORY_LIMIT, order: 'desc' })
    return r?.jobs ?? []
  } catch {
    return []
  }
}

export async function loadHidden(call: Call): Promise<string[]> {
  try {
    const r = await call<{ value: unknown }>('server.database.get_item', HIDDEN)
    return Array.isArray(r?.value) ? r.value.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []   // nothing taken off yet
  }
}

export async function saveHidden(call: Call, hidden: string[]): Promise<void> {
  await call('server.database.post_item', { ...HIDDEN, value: hidden })
}

/** "Remove from recent": only a past print whose file is gone; Moonraker's history is never deleted. */
export async function hideFromRecent(call: Call, hidden: string[], filename: string): Promise<string[]> {
  const next = hide(hidden, filename)
  await saveHidden(call, next).catch(() => {})
  return next
}

/** ok, with the new hidden list; or not, with the words to show. */
export interface RemoveResult { ok: boolean; hidden?: string[]; message?: string }

/** Delete the file from the printer. At home only: away there's no call at all. */
export async function removeFile(call: Call, filename: string, o: { away: boolean; hidden: string[] }): Promise<RemoveResult> {
  if (o.away) return { ok: false, message: 'That has to be done at the printer.' }
  try {
    await call('server.files.delete_file', { path: `gcodes/${filename}` })
  } catch (e: any) {
    const why = typeof e?.message === 'string' && e.message ? ` The printer said: ${e.message}` : ''
    return { ok: false, message: `It wasn't removed.${why}` }
  }
  // what you meant: it leaves Recent too, not just the library
  return { ok: true, hidden: await hideFromRecent(call, o.hidden, filename) }
}
