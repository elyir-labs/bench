// Pins Look at a model (design/look/, A with C's layers, picked 9 October 2026): files are read on the
// device, every part of a 3MF where the file put it, and a STEP through OpenCascade.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { deflateRawSync } from 'node:zlib'
import { entries, readEntry } from '../src/look/zip.ts'
import { partsOf, read3mf, then } from '../src/look/threemf.ts'
import { readModel, sideBySide, sizeWords, title, together } from '../src/look/read.ts'
import { stepParts, type Occt } from '../src/look/step.ts'
import { sizeOf } from '../src/slice/stl.ts'

/** A zip of the given files, the first stored and the rest deflated. */
function zip(files: Record<string, string>): ArrayBuffer {
  const local: Buffer[] = [], central: Buffer[] = []
  let at = 0
  Object.entries(files).forEach(([name, text], i) => {
    const raw = Buffer.from(text), body = i === 0 ? raw : deflateRawSync(raw), n = Buffer.from(name)
    const h = Buffer.alloc(30)
    h.writeUInt32LE(0x04034b50, 0); h.writeUInt16LE(i === 0 ? 0 : 8, 8); h.writeUInt16LE(n.length, 26)
    const c = Buffer.alloc(46)
    c.writeUInt32LE(0x02014b50, 0); c.writeUInt16LE(i === 0 ? 0 : 8, 10)
    c.writeUInt32LE(body.length, 20); c.writeUInt32LE(raw.length, 24); c.writeUInt16LE(n.length, 28); c.writeUInt32LE(at, 42)
    local.push(h, n, body); central.push(c, n)
    at += 30 + n.length + body.length
  })
  const cd = Buffer.concat(central), end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(central.length / 2, 8); end.writeUInt16LE(central.length / 2, 10)
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(at, 16)
  const all = Buffer.concat([...local, cd, end])
  return all.buffer.slice(all.byteOffset, all.byteOffset + all.length)
}

const cube = (s = 10) => {
  const v = [[0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0], [0, 0, s], [s, 0, s], [s, s, s], [0, s, s]]
  const t = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
  return `<mesh><vertices>${v.map(([x, y, z]) => `<vertex x="${x}" y="${y}" z="${z}"/>`).join('')}</vertices>`
    + `<triangles>${t.map(([a, b, c]) => `<triangle v1="${a}" v2="${b}" v3="${c}"/>`).join('')}</triangles></mesh>`
}
const RELS = '<Relationships><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'

test('a zip is read stored or deflated', async () => {
  const buf = zip({ 'a.txt': 'stored as is', 'b/c.txt': 'packed '.repeat(50) })
  const es = entries(buf)
  assert.deepEqual(es.map((e) => e.name), ['a.txt', 'b/c.txt'])
  assert.equal(new TextDecoder().decode(await readEntry(buf, es[0])), 'stored as is')
  assert.equal(new TextDecoder().decode(await readEntry(buf, es[1])), 'packed '.repeat(50))
  assert.throws(() => entries(new ArrayBuffer(100)), /isn't a zip/)
})

test('a 3MF: every build item a part, placed where the file put it', async () => {
  const model = `<model unit="millimeter"><resources>
    <object id="1" name="Block" type="model">${cube(10)}</object>
    <object id="2" type="model">${cube(5)}</object>
    <object id="3" type="support">${cube(1)}</object>
  </resources><build>
    <item objectid="1" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>
    <item objectid="2" transform="2 0 0 0 2 0 0 0 2 0 0 0"/>
    <item objectid="3"/>
  </build></model>`
  const parts = await read3mf(zip({ '_rels/.rels': RELS, '3D/3dmodel.model': model }))
  assert.deepEqual(parts.map((p) => p.name), ['Block', 'Part 2'])
  const s = (p: Float32Array) => { let x = Infinity; for (let i = 0; i < p.length; i += 3) x = Math.min(x, p[i]); return x }
  assert.equal(s(parts[0].tris), 100)
  assert.deepEqual(sizeOf(parts[1].tris), [10, 10, 10])
})

test("a 3MF from Orca or Bambu: parts in other files, named in the slicer's settings", () => {
  const files = new Map([
    ['_rels/.rels', RELS],
    ['3D/3dmodel.model', `<model><resources><object id="7" type="model"><components>
      <component p:path="/3D/Objects/object_1.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 5"/>
      <component p:path="/3D/Objects/object_1.model" objectid="2"/></components></object></resources>
      <build><item objectid="7" transform="1 0 0 0 1 0 0 0 1 50 60 0" printable="1"/></build></model>`],
    ['3D/Objects/object_1.model', `<model><resources><object id="1" type="model">${cube(4)}</object><object id="2" type="model">${cube(2)}</object></resources></model>`],
    ['Metadata/model_settings.config', '<config><object id="7"><metadata key="name" value="gbp_arm.stl"/></object></config>'],
  ])
  const parts = partsOf(files)
  assert.equal(parts.length, 1)
  assert.equal(parts[0].name, 'Gbp arm')
  assert.equal(parts[0].tris.length, 2 * 12 * 9)
  assert.deepEqual(sizeOf(parts[0].tris), [4, 4, 9])
})

test('3MF transforms compose: the component first, then the item', () => {
  const up5 = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 5], twice = [2, 0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 0]
  assert.deepEqual(then(up5, twice), [2, 0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 10])
  assert.deepEqual(then(twice, up5), [2, 0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 5])
})

test('a 3MF in inches is shown in millimeters', () => {
  const files = new Map([['3D/3dmodel.model', `<model unit="inch"><resources><object id="1">${cube(1)}</object></resources><build><item objectid="1"/></build></model>`]])
  assert.deepEqual(sizeOf(partsOf(files)[0].tris), [25.4, 25.4, 25.4])
})

test('a STEP is read by OpenCascade, a part per solid, by its name', async () => {
  const occt = await (createRequire(import.meta.url)('occt-import-js') as () => Promise<Occt>)()
  const parts = stepParts(occt, new Uint8Array(readFileSync(new URL('./fixtures/two-parts.step', import.meta.url))))
  assert.deepEqual(parts.map((p) => p.name), ['Block', 'Peg'])
  assert.deepEqual(sizeOf(parts[0].tris)?.map(Math.round), [20, 10, 5])
  assert.equal(sizeWords(together(parts)), '33 × 10 × 8 mm')
  assert.throws(() => stepParts(occt, new TextEncoder().encode('not a step')), /couldn't be read/)
})

test('readModel: STL by its name, nothing that is not a model, no empty files', async () => {
  const stl = `solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid t\n`
  const none = async () => { throw new Error('no STEP here') }
  const parts = await readModel('wall_hook-v2.stl', new TextEncoder().encode(stl).buffer as ArrayBuffer, none)
  assert.equal(title('wall_hook-v2.stl', parts), 'Wall hook v2')
  await assert.rejects(readModel('notes.txt', new ArrayBuffer(10), none), /isn't a model/)
  await assert.rejects(readModel('empty.stl', new TextEncoder().encode('solid e\nendsolid e\n').buffer as ArrayBuffer, none), /no model/)
  assert.equal(title('plate.3mf', [parts[0], parts[0]]), '2 parts')
})

test('several files on one plate: side by side on the bed, each file keeping its own parts where it put them', () => {
  const box = (x: number, y: number, z: number, d: number) => new Float32Array([x, y, z, x + d, y, z, x, y + d, z + d])
  const a = [{ name: 'Lid', tris: box(-5, -5, 0, 10) }]
  const b = [{ name: 'Left', tris: box(100, 0, 3, 4) }, { name: 'Right', tris: box(120, 0, 3, 4) }]
  const out = sideBySide([a, b])
  assert.deepEqual(out.map((p) => p.name), ['Lid', 'Left', 'Right'])
  const [x0a, , , x1a] = [...span(out[0].tris)], [x0b] = [...span(out[1].tris)]
  assert.ok(x0b >= x1a + 6, 'the second file starts past the first, 6 mm apart')
  assert.equal(span(out[1].tris)[2], 0, "a file that floats is set down on the bed")
  assert.equal(span(out[2].tris)[0] - span(out[1].tris)[0], 20, "a file's own parts keep their spacing")
  assert.equal(x1a - x0a, 10)
  assert.equal(sideBySide([a]), a)
  assert.equal(title('', out, 2), '2 models')
})

function span(t: Float32Array): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity
  for (let i = 0; i < t.length; i += 3) { x0 = Math.min(x0, t[i]); x1 = Math.max(x1, t[i]); y0 = Math.min(y0, t[i + 1]); z0 = Math.min(z0, t[i + 2]) }
  return [x0, y0, z0, x1]
}

test('the STEP reader runs where the CSP forbids eval, once its invoker is patched', async () => {
  const { runInContext, createContext } = await import('node:vm')
  const { noEval } = await import('../src/look/occt-patch.ts')
  const path = createRequire(import.meta.url).resolve('occt-import-js')
  const src = readFileSync(path, 'utf8')
  const run = async (code: string) => {
    const ctx = createContext({ module: { exports: {} }, exports: {}, require: createRequire(path), __filename: path, __dirname: path.replace(/[^/]+$/, ''),
      process, console: { log() {}, warn() {}, error() {} }, WebAssembly, TextDecoder, URL, setTimeout, clearTimeout, performance },
      { codeGeneration: { strings: false, wasm: true } })
    runInContext(code, ctx)
    const occt = await (ctx.module as { exports: () => Promise<Occt> }).exports()
    return stepParts(occt, new Uint8Array(readFileSync(new URL('./fixtures/two-parts.step', import.meta.url))))
  }
  await assert.rejects(run(src), /Code generation from strings disallowed/)
  assert.deepEqual([...await run(noEval(src))].map((p) => String(p.name)), ['Block', 'Peg'])
  assert.throws(() => noEval('nothing to patch'), /not found/)
})

test('how would it print: the plate Ready starts with, and what each row says', async () => {
  const { plateFor, requestFor, rowWords, firstPick } = await import('../src/look/estimate.ts')
  const flat = { model: 'm1', name: 'Mount', size: [10, 40, 80], lying: { down_area: 1, flat_area: 9, flat_normal: [0, 0, -1], flat_better: true, tilt: 0, size_flat: [80, 40, 10] }, copies: 2 }
  const big = { model: 'm2', name: 'Shelf', size: [400, 100, 20], lying: null }
  assert.deepEqual(plateFor([flat], [350, 350, 340]), { parts: [{ model: 'm1', copies: 2, scale: 1, lay: 'flat' }], shrunk: null })
  const p = plateFor([flat, big], [220, 220, 250])
  assert.equal(p.parts[1].lay, 'file')
  assert.equal(p.shrunk, 0.53)
  const printer = { id: 'desk', name: 'Desk', materials: ['PLA', 'PETG'], slots: 1, bed: [300, 300, 310], base: '', supports: 'tree' as const }
  const r = requestFor([flat], printer, [{ slot: 0, color: '#d9534f', material: 'petg', status: 'ready', in_use: true, name: 'Red PETG' }], 'strong')
  assert.deepEqual(r.req, { parts: [{ model: 'm1', copies: 2, scale: 1, lay: 'flat' }], printer: 'desk', purpose: 'strong', supports: 'tree', material: 'PETG', color: '#d9534f', slot: 1 })
  assert.equal(requestFor([flat], printer, [], 'everyday').req.material, 'PLA')

  const job = (s: number, g: number, plates = 1) => ({ id: 'j', state: 'done' as const, changes: [], estimate: { seconds: s, time: null, grams: g, layers: 10 },
    plates: Array.from({ length: plates }, (_, i) => ({ plate: i + 1, seconds: s, time: null, grams: g, counts: [1], gcode: '' })) })
  const spool = { slot: 0, material: 'PLA', color: '#d9534f', name: 'Red PLA' }
  assert.deepEqual(rowWords({ kind: 'done', job: job(19140, 95.6), shrunk: null, spool }), { time: '5 h 19 m', grams: '96 g', note: 'Red PLA' })
  assert.equal(rowWords({ kind: 'done', job: job(600, 5, 2), shrunk: 0.8, spool }).note, 'Shrunk to 80% to fit · 2 plates · Red PLA')
  assert.equal(rowWords({ kind: 'away' }).note, "Times come when you're home")
  assert.equal(rowWords({ kind: 'slicer', state: { state: 'down', name: 'Workshop' } }).note, 'Workshop is off')
  assert.equal(rowWords({ kind: 'slicing', job: { id: 'j', state: 'queued', changes: [], behind: 'Workshop' } }).note, "After Workshop's slice")
  const rows = { a: { kind: 'away' as const }, b: { kind: 'done' as const, job: job(1, 1), shrunk: 0.5, spool }, c: { kind: 'done' as const, job: job(1, 1), shrunk: null, spool } }
  assert.equal(firstPick(['a', 'b', 'c'], rows), 'c')
  assert.equal(firstPick(['a', 'b'], rows), 'b')
  assert.equal(firstPick(['a'], rows), null)
  // on a Bench Box: the box's words, and one that can't take it as things are is offered last
  const boxRow = { kind: 'done' as const, job: job(600, 5), shrunk: null, spool, line: 'It has White PETG, not Black PLA', fits: false }
  assert.equal(rowWords(boxRow).note, 'It has White PETG, not Black PLA')
  assert.equal(firstPick(['x', 'c'], { x: boxRow, c: rows.c }), 'c')
  assert.equal(firstPick(['x'], { x: boxRow }), 'x')
})

test('a printer paired directly and on a Bench Box is asked through the box', async () => {
  const { onABench } = await import('../src/look/estimate.ts')
  assert.deepEqual([...onABench([{ id: 'workshop', name: 'Workshop' }, { id: 'desk', name: 'Desk' }], [{ name: 'workshop ' }, { name: 'Kobra 3' }])], ['workshop'])
})

test('layers: the stack and one layer unpacked as the slicer packs them, in words people use', async () => {
  const { stackFrom, pathsFrom, layerWords, kindsIn, WALL, SUPPORT, OTHER } = await import('../src/look/layers.ts')
  const i16 = (v: number[]) => Buffer.from(new Int16Array(v).buffer).toString('base64')
  const u16 = (v: number[]) => Buffer.from(new Uint16Array(v).buffer).toString('base64')
  const s = stackFrom({ count: 3, z: [0.2, 0.4, 12.6], width: 0.45, walls: { count: 2, segs: i16([100, 100, 200, 100, 2, 50, 50, 300, 100, 4]), layer: u16([0, 1]) } })
  assert.deepEqual([...s.walls], [10, 10, 20, 10, 0.2, 5, 5, 30, 10, 0.4].map(Math.fround))
  assert.deepEqual([...s.layer], [0, 1])
  assert.equal(layerWords(s, 1), 'Layer 2 of 3 · 0.4 mm')
  assert.equal(layerWords(s, 2), 'Layer 3 of 3 · 12.6 mm')
  const p = pathsFrom(1, { count: 3, segs: i16(new Array(15).fill(10)), kinds: Buffer.from([SUPPORT, OTHER, WALL]).toString('base64') })
  assert.equal(p.lines.length, 15)
  assert.deepEqual(kindsIn(p), [WALL, SUPPORT])
  assert.deepEqual(kindsIn(null), [])
})
