// A STEP file turned into parts by OpenCascade (occt-import-js, in WebAssembly), on the device.
// Pure: the worker (step-worker.ts) and the tests hand it the loaded library.

import type { Part } from './read.ts'

interface OcctMesh { name?: string; attributes: { position: { array: ArrayLike<number> } }; index: { array: ArrayLike<number> } }
export interface Occt { ReadStepFile(bytes: Uint8Array, params: Record<string, unknown> | null): { success: boolean; meshes: OcctMesh[] } }

export function stepParts(occt: Occt, bytes: Uint8Array): Part[] {
  // null: the library's defaults (millimeters, a chord at most 0.1% of the model). Passing an object makes
  // the glue compile a method caller from a string, which the CSP forbids (see occt-patch.ts).
  const r = occt.ReadStepFile(bytes, null)
  if (!r.success) throw new Error("This STEP file couldn't be read.")
  return r.meshes.map((m, i) => {
    const pos = m.attributes.position.array, idx = m.index.array
    const tris = new Float32Array(idx.length * 3)
    for (let k = 0; k < idx.length; k++) {
      const v = idx[k] * 3
      tris[k * 3] = pos[v]; tris[k * 3 + 1] = pos[v + 1]; tris[k * 3 + 2] = pos[v + 2]
    }
    return { name: m.name || `Part ${i + 1}`, tris }
  })
}
