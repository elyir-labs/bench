// A 3MF read on the device: every part on its plate, where the file put it (design/look/).
// The XML is scanned, not parsed into a tree: a part can be millions of vertices, and the
// tests run in Node, which has no DOMParser.

import { entries, readEntry } from './zip.ts'
import type { Part } from './read.ts'
import { modelName } from '../slice/plan.ts'

type M = number[]   // 3MF's 3x4 transform, row vectors: m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32
const I: M = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]

interface Obj { name: string; type: string; mesh: Float32Array | null; comps: { key: string; t: M }[] }

const attrs = (s: string): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const m of s.matchAll(/([\w:]+)\s*=\s*"([^"]*)"/g)) out[m[1]] = m[2]
  return out
}
const matrix = (s?: string): M => {
  const n = (s ?? '').trim().split(/\s+/).map(Number)
  return n.length === 12 && n.every(Number.isFinite) ? n : I
}
/** a, then b */
export function then(a: M, b: M): M {
  const r: M = new Array(12)
  for (let row = 0; row < 4; row++) {
    for (let c = 0; c < 3; c++) {
      r[row * 3 + c] = a[row * 3] * b[c] + a[row * 3 + 1] * b[3 + c] + a[row * 3 + 2] * b[6 + c] + (row === 3 ? b[9 + c] : 0)
    }
  }
  return r
}
const UNITS: Record<string, number> = { micron: 0.001, millimeter: 1, centimeter: 10, inch: 25.4, foot: 304.8, meter: 1000 }
const unslash = (p: string) => p.replace(/^\//, '')

function mesh(body: string): Float32Array | null {
  const v: number[] = []
  for (const m of body.matchAll(/<vertex\b([^>]*)\/>/g)) {
    const a = attrs(m[1])
    v.push(+a.x, +a.y, +a.z)
  }
  const tris: number[] = []
  for (const m of body.matchAll(/<triangle\b([^>]*)\/>/g)) {
    const a = attrs(m[1])
    for (const k of [+a.v1, +a.v2, +a.v3]) tris.push(v[k * 3], v[k * 3 + 1], v[k * 3 + 2])
  }
  return tris.length ? new Float32Array(tris) : null
}

function objects(path: string, xml: string, into: Map<string, Obj>) {
  for (const m of xml.matchAll(/<object\b([^>]*)>([\s\S]*?)<\/object>/g)) {
    const a = attrs(m[1])
    const comps = [...m[2].matchAll(/<component\b([^>]*)\/>/g)].map((c) => {
      const ca = attrs(c[1])
      return { key: `${unslash(ca['p:path'] ?? path)}#${ca.objectid}`, t: matrix(ca.transform) }
    })
    into.set(`${path}#${a.id}`, { name: a.name ?? '', type: a.type ?? 'model', mesh: comps.length ? null : mesh(m[2]), comps })
  }
}

function place(tris: Float32Array, t: M): Float32Array {
  if (t === I) return tris
  const out = new Float32Array(tris.length)
  for (let i = 0; i < tris.length; i += 3) {
    const x = tris[i], y = tris[i + 1], z = tris[i + 2]
    out[i] = x * t[0] + y * t[3] + z * t[6] + t[9]
    out[i + 1] = x * t[1] + y * t[4] + z * t[7] + t[10]
    out[i + 2] = x * t[2] + y * t[5] + z * t[8] + t[11]
  }
  return out
}

function gather(key: string, t: M, objs: Map<string, Obj>, out: Float32Array[], depth = 0) {
  const o = objs.get(key)
  if (!o || depth > 16 || o.type === 'support' || o.type === 'other') return
  if (o.mesh) out.push(place(o.mesh, t))
  for (const c of o.comps) gather(c.key, then(c.t, t), objs, out, depth + 1)
}

const join = (parts: Float32Array[]) => {
  const all = new Float32Array(parts.reduce((n, p) => n + p.length, 0))
  let at = 0
  for (const p of parts) { all.set(p, at); at += p.length }
  return all
}

/** Every build item as a part, from the package's text files by path. Names from the slicer's own
 *  settings (Orca and Bambu keep them in Metadata/model_settings.config) when the object has none. */
export function partsOf(files: Map<string, string>): Part[] {
  const rels = files.get('_rels/.rels') ?? ''
  const root = unslash(/Target="([^"]+\.model)"/i.exec(rels)?.[1] ?? '3D/3dmodel.model')
  const objs = new Map<string, Obj>()
  for (const [path, xml] of files) if (path.endsWith('.model')) objects(path, xml, objs)
  const named = new Map<string, string>()
  for (const m of (files.get('Metadata/model_settings.config') ?? '').matchAll(/<object\s+id="(\d+)"[^>]*>([\s\S]*?)<\/object>/g)) {
    const n = /<metadata\s+key="name"\s+value="([^"]*)"/.exec(m[2])?.[1]
    if (n) named.set(m[1], n)
  }
  const build = /<build\b[^>]*>([\s\S]*?)<\/build>/.exec(files.get(root) ?? '')?.[1] ?? ''
  const unit = UNITS[/<model\b[^>]*\bunit="(\w+)"/.exec(files.get(root) ?? '')?.[1] ?? 'millimeter'] ?? 1
  const mm: M = unit === 1 ? I : [unit, 0, 0, 0, unit, 0, 0, 0, unit, 0, 0, 0]
  const parts: Part[] = []
  for (const m of build.matchAll(/<item\b([^>]*)\/>/g)) {
    const a = attrs(m[1])
    if (a.printable === '0') continue
    const key = `${unslash(a['p:path'] ?? root)}#${a.objectid}`
    const pieces: Float32Array[] = []
    gather(key, then(matrix(a.transform), mm), objs, pieces)
    if (!pieces.length) continue
    const name = objs.get(key)?.name || named.get(a.objectid) || `Part ${parts.length + 1}`
    parts.push({ name: modelName(name), tris: join(pieces) })
  }
  return parts
}

export async function read3mf(buf: ArrayBuffer): Promise<Part[]> {
  const files = new Map<string, string>()
  const text = new TextDecoder()
  for (const e of entries(buf)) {
    if (/\.(model|rels)$/i.test(e.name) || e.name === 'Metadata/model_settings.config') files.set(e.name, text.decode(await readEntry(buf, e)))
  }
  return partsOf(files)
}
