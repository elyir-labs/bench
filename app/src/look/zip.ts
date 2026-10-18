// Reading a zip in the browser (a 3MF is one), with nothing but DecompressionStream.

export interface ZipEntry { name: string; method: number; offset: number; csize: number; size: number }

export function entries(buf: ArrayBuffer): ZipEntry[] {
  const v = new DataView(buf)
  let end = -1
  for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 65557); i--) {
    if (v.getUint32(i, true) === 0x06054b50) { end = i; break }
  }
  if (end < 0) throw new Error("isn't a zip")
  const count = v.getUint16(end + 10, true)
  let at = v.getUint32(end + 16, true)
  if (at === 0xffffffff) throw new Error('is too big to read here')
  const names = new TextDecoder()
  const out: ZipEntry[] = []
  for (let k = 0; k < count; k++) {
    if (v.getUint32(at, true) !== 0x02014b50) throw new Error('is a broken zip')
    const n = v.getUint16(at + 28, true), m = v.getUint16(at + 30, true), c = v.getUint16(at + 32, true)
    out.push({
      name: names.decode(new Uint8Array(buf, at + 46, n)),
      method: v.getUint16(at + 10, true),
      csize: v.getUint32(at + 20, true),
      size: v.getUint32(at + 24, true),
      offset: v.getUint32(at + 42, true),
    })
    at += 46 + n + m + c
  }
  return out
}

/** One entry's bytes. Sizes come from the central directory: a local header may leave them 0. */
export async function readEntry(buf: ArrayBuffer, e: ZipEntry): Promise<Uint8Array> {
  const v = new DataView(buf)
  if (v.getUint32(e.offset, true) !== 0x04034b50) throw new Error('is a broken zip')
  const start = e.offset + 30 + v.getUint16(e.offset + 26, true) + v.getUint16(e.offset + 28, true)
  const raw = new Uint8Array(buf, start, e.csize)
  if (e.method === 0) return raw
  if (e.method !== 8) throw new Error(`uses a packing this can't read (${e.method})`)
  const stream = new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'))
  return new Uint8Array(await new Response(stream).arrayBuffer())
}
