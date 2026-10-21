// Look at a model (design/look/, A): a file from this phone or computer, read here, kept here.

import { ref, shallowRef } from 'vue'
import { del, get, getAll, put } from './db'
import { readModel, sideBySide, type Part } from '@/look/read.ts'

/** One file, or several looked at together (`files`, each with its name; `file` is then the first). */
export interface Looked { id: string; name: string; at: number; parts: number; thumb: string; file: Blob; files?: File[] }

export const filesOf = (k: Looked): File[] => k.files ?? [k.file instanceof File && k.file.name === k.name ? k.file : new File([k.file], k.name)]

const KEEP = 8
const KEEP_BYTES = 60 * 1024 * 1024   // a bigger file is shown but not kept

/** Files dropped anywhere on the app, for the Look page to open together. */
export const pending = shallowRef<File[] | null>(null)

/** "Print on Workshop…": the files, for that printer's own Print once its screen is open (PrinterPage hands it over). */
export const handoff = shallowRef<{ printer: string; files: File[] } | null>(null)

let worker: Worker | null = null
function readStep(buf: ArrayBuffer): Promise<Part[]> {
  worker ??= new Worker(new URL('../look/step-worker.ts', import.meta.url), { type: 'module' })
  const w = worker
  return new Promise((resolve, reject) => {
    w.onmessage = (e) => {
      if (e.data.parts) return resolve(e.data.parts)
      reject(new Error(e.data.error === 'blocked'
        ? "STEP files can't be read here yet. This page needs an update to allow the STEP reader."
        : e.data.error))
    }
    w.onerror = () => { worker = null; reject(new Error("The STEP reader couldn't start.")) }
    w.postMessage(buf, [buf])
  })
}

export async function read(file: Blob, name: string): Promise<Part[]> {
  return readModel(name, await file.arrayBuffer(), readStep)
}

/** Several files on one plate, side by side. */
export async function readAll(files: File[]): Promise<Part[]> {
  const each: Part[][] = []
  for (const f of files) each.push(await read(f, f.name))
  return sideBySide(each)
}

export async function recent(): Promise<Looked[]> {
  try {
    return (await getAll<Looked>('looked')).sort((a, b) => b.at - a.at)
  } catch {
    return []
  }
}

export async function keep(files: File[], name: string, parts: number, thumb: string, id?: string): Promise<string> {
  const key = id ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
  if (files.reduce((n, f) => n + f.size, 0) > KEEP_BYTES) return key
  const sig = (fs: File[]) => fs.map((f) => `${f.name}:${f.size}`).join('/')
  try {
    const old = await recent()
    const same = old.find((o) => sig(filesOf(o)) === sig(files))
    if (same && same.id !== key) await del('looked', same.id)
    await put('looked', { id: key, name, at: Date.now(), parts, thumb, file: files[0], ...(files.length > 1 ? { files } : {}) } satisfies Looked)
    for (const o of old.filter((o) => o.id !== key && o.id !== same?.id).slice(KEEP - 1)) await del('looked', o.id)
  } catch {
    // private browsing or storage full: it's still shown, just not kept
  }
  return key
}

export const looked = (id: string) => get<Looked>('looked', id).catch(() => undefined)
export const forget = (id: string) => del('looked', id).catch(() => undefined)

/** Files shared in from another app (Android's Share): the service worker leaves the file in this cache. */
export async function takeShared(): Promise<File | null> {
  try {
    const cache = await caches.open('look-share')
    const res = await cache.match('/look/shared')
    if (!res) return null
    await cache.delete('/look/shared')
    const name = decodeURIComponent(res.headers.get('X-Name') ?? 'model.stl')
    return new File([await res.blob()], name)
  } catch {
    return null
  }
}

/** The file picker's filter. iPhones and iPads grey out files whose type they don't know (3MF, STEP),
 *  so they get no filter and the name is checked after. */
export const ACCEPT = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Mac/.test(navigator.userAgent))
  ? undefined : '.stl,.3mf,.step,.stp,.obj'
