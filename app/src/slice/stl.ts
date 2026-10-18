// Reading a model in the browser, to draw it before the printer has a picture of its own.
// STL (binary or text) and OBJ. STEP isn't read here; it gets no picture.

/** Every triangle's three corners, flat: [x0, y0, z0, x1, ...], nine numbers per triangle. */
export function parseModel(name: string, buf: ArrayBuffer): Float32Array | null {
  const lower = name.toLowerCase()
  if (lower.endsWith('.stl')) return isBinaryStl(buf) ? binaryStl(buf) : textStl(new TextDecoder().decode(buf))
  if (lower.endsWith('.obj')) return obj(new TextDecoder().decode(buf))
  return null
}

function isBinaryStl(buf: ArrayBuffer): boolean {
  if (buf.byteLength < 84) return false
  const n = new DataView(buf).getUint32(80, true)
  return buf.byteLength === 84 + n * 50
}

function binaryStl(buf: ArrayBuffer): Float32Array {
  const v = new DataView(buf)
  const n = v.getUint32(80, true)
  const out = new Float32Array(n * 9)
  for (let i = 0; i < n; i++) {
    const at = 84 + i * 50 + 12          // skip the normal: it's often zero, and recomputed when drawn
    for (let k = 0; k < 9; k++) out[i * 9 + k] = v.getFloat32(at + k * 4, true)
  }
  return out
}

function textStl(text: string): Float32Array {
  const nums: number[] = []
  const re = /vertex\s+(\S+)\s+(\S+)\s+(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) nums.push(+m[1], +m[2], +m[3])
  return new Float32Array(nums.slice(0, nums.length - (nums.length % 9)))
}

function obj(text: string): Float32Array {
  const verts: number[][] = []
  const out: number[] = []
  for (const line of text.split('\n')) {
    const p = line.trim().split(/\s+/)
    if (p[0] === 'v') verts.push([+p[1], +p[2], +p[3]])
    else if (p[0] === 'f') {
      const idx = p.slice(1).map(t => {
        const i = parseInt(t.split('/')[0], 10)
        return i < 0 ? verts.length + i : i - 1
      })
      for (let k = 1; k + 1 < idx.length; k++) {      // fan out polygons into triangles
        for (const i of [idx[0], idx[k], idx[k + 1]]) out.push(...(verts[i] ?? [0, 0, 0]))
      }
    }
  }
  return new Float32Array(out)
}

/** The model turned so the side facing `normal` lies on the plate, as the slicer turns it
 *  (down_rotation in slicer/elyir_bench_slice.py), then set down on z = 0. */
export function layOn(tris: Float32Array, normal: number[]): Float32Array {
  const [nx, ny, nz] = normal
  // axis = n x (0, 0, -1), angle between n and straight down
  let ax = -ny, ay = nx, az = 0
  const s = Math.hypot(ax, ay, az), c = -nz
  let r: number[][]
  if (s < 1e-9) r = c > 0 ? [[1, 0, 0], [0, 1, 0], [0, 0, 1]] : [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
  else {
    ax /= s; ay /= s; az /= s
    const k = 1 - c
    r = [[c + ax * ax * k, ax * ay * k - az * s, ax * az * k + ay * s],
      [ay * ax * k + az * s, c + ay * ay * k, ay * az * k - ax * s],
      [az * ax * k - ay * s, az * ay * k + ax * s, c + az * az * k]]
  }
  const out = new Float32Array(tris.length)
  let zmin = Infinity
  for (let i = 0; i < tris.length; i += 3) {
    const x = tris[i], y = tris[i + 1], z = tris[i + 2]
    for (let k = 0; k < 3; k++) out[i + k] = r[k][0] * x + r[k][1] * y + r[k][2] * z
    if (out[i + 2] < zmin) zmin = out[i + 2]
  }
  for (let i = 2; i < out.length; i += 3) out[i] -= zmin
  return out
}

/** Width, depth and height in mm. */
export function sizeOf(tris: Float32Array): [number, number, number] | null {
  if (!tris.length) return null
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < tris.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const v = tris[i + k]
      if (v < lo[k]) lo[k] = v
      if (v > hi[k]) hi[k] = v
    }
  }
  return [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]].map(v => Math.round(v * 100) / 100) as [number, number, number]
}
