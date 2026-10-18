// Reads a STEP off the main thread. The reader (about 7 MB) is fetched the first time a STEP is opened.
// Needs WebAssembly allowed by the page's CSP ('wasm-unsafe-eval' in script-src).
import occtimportjs from 'occt-import-js'
import wasmUrl from 'occt-import-js/dist/occt-import-js.wasm?url'
import { stepParts, type Occt } from './step.ts'

let occt: Promise<Occt> | null = null

self.onmessage = async (e: MessageEvent<ArrayBuffer>) => {
  try {
    occt ??= occtimportjs({ locateFile: () => wasmUrl })
    const parts = stepParts(await occt, new Uint8Array(e.data))
    ;(self as unknown as Worker).postMessage({ parts }, parts.map((p) => p.tris.buffer))
  } catch (err) {
    occt = null
    const blocked = /Refused to compile|unsafe-eval|Content Security Policy/i.test(String((err as Error)?.message ?? err))
    ;(self as unknown as Worker).postMessage({ error: blocked ? 'blocked' : String((err as Error)?.message ?? err), detail: String((err as Error)?.message ?? err) })
  }
}
