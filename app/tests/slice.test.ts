// Pins Print a model (design/print-a-model/, C "Ready first", picked 2 October 2026): what the
// Ready page decides before anyone asks, and how a model is read and drawn.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { asKind, editRows, editSummary, editWords, steps, type Editable, fitScale, groupChanges, matchPrinter, modelName, pickSpool, showValue, supportsWords, tooBigWords, usableSpools, type SliceChange } from '../src/slice/plan.ts'
import { layOn, parseModel, sizeOf } from '../src/slice/stl.ts'
import { project, rgb } from '../src/slice/render.ts'

const spool = (slot: number, material: string | null, status = 'ready', in_use = false, color = '#2563EB') =>
  ({ slot, material, status: status as 'ready', in_use, color })

test('a new model starts with the spool in the head, if it has settings here', () => {
  const spools = [spool(0, 'PETG'), spool(1, 'PLA', 'ready', true), spool(2, 'NYLON', 'ready')]
  assert.equal(pickSpool(spools, ['PLA', 'PETG'])?.slot, 1)
  assert.equal(pickSpool([spool(0, 'NYLON', 'ready', true), spool(3, 'petg')], ['PLA', 'PETG'])?.slot, 3)
  assert.equal(pickSpool([spool(0, null, 'empty'), spool(1, 'PLA', 'unknown')], ['PLA']), null)
  assert.deepEqual(usableSpools([spool(0, 'PLA', 'low'), spool(1, 'PLA', 'empty')], ['PLA']).map(s => s.slot), [0])
})

test('too big: shrunk to the largest whole percent that fits, never grown', () => {
  assert.equal(fitScale([412, 190, 140], [350, 350, 340]), 0.83)   // same as slicer/elyir_bench_slice.py
  assert.equal(fitScale([46, 34, 25], [350, 350, 340]), 1)
  assert.equal(fitScale([100, 100, 500], [350, 350, 340]), 0.68)
  assert.equal(fitScale(null, [350, 350, 340]), 1)
  assert.equal(tooBigWords([412, 190, 140], [350, 350, 340], 'Workshop'), "It's 412 mm long and the bed is 350 mm")
  assert.equal(tooBigWords([100, 400, 50], [350, 350, 340], 'Workshop'), "It's 400 mm deep and the bed is 350 mm")
  assert.equal(tooBigWords([100, 100, 500], [350, 350, 340], 'Workshop'), "It's 500 mm tall and Workshop prints up to 340 mm")
})

test('every setting reads like the board: grouped, with what it replaced', () => {
  const changes: SliceChange[] = [
    { key: 'wall_loops', label: 'Walls', value: '5', was: '3', why: 'Walls carry the load', source: 'purpose' },
    { key: 'top_shell_layers', label: 'Solid top', value: '5', was: '4', why: '', source: 'purpose' },
    { key: 'enable_support', label: 'Supports', value: '1', was: '0', why: '', source: 'supports' },
    { key: 'filament_colour', label: 'Color', value: ['#2563eb'], was: null, why: '', source: 'spool' },
    { key: 'curr_bed_type', label: 'Plate', value: 'High Temp Plate', was: null, why: '', source: 'printer' },
  ]
  const g = groupChanges(changes, 'Strong', 'Workshop')
  assert.deepEqual(g.map(x => x.title), ["Because it's Strong", 'Supports', 'From the spool and Workshop'])
  assert.deepEqual(g[0].rows[1], { label: 'Solid top', key: 'top_shell_layers', why: '', was: '4 layers', now: '5 layers', color: undefined })
  assert.equal(g[1].rows[0].now, 'on')
  assert.equal(g[2].rows[0].color, '#2563EB')
  assert.equal(showValue('support_type', 'tree(auto)'), 'tree')
  assert.equal(showValue('layer_height', '0.12'), '0.12 mm')
  assert.deepEqual(groupChanges([], 'Everyday', 'Workshop'), [])
})

test('the Supports row names the kind, and whether it is the usual (design/supports/, A)', () => {
  assert.deepEqual(supportsWords('normal', true, 'normal'), { value: 'Normal', note: 'Comes off in blocks · your usual' })
  assert.deepEqual(supportsWords('tree', null, 'normal'), { value: 'Tree', note: 'Branches, for this print' })
  assert.equal(supportsWords('normal', false, 'normal').value, 'None needed')
  assert.equal(supportsWords('off', true, 'normal').value, 'Off')
  assert.equal(asKind('auto', 'tree'), 'tree')
  assert.equal(asKind('off', 'tree'), 'off')
  assert.equal(asKind(undefined, 'normal'), 'normal')
})

test('names and printers', () => {
  assert.equal(modelName('phone-stand_v2.stl'), 'Phone stand v2')
  const ps = [{ id: 'workshop', name: 'Workshop' }, { id: 'studio', name: 'Studio' }]
  assert.equal(matchPrinter(ps, 'studio')?.id, 'studio')
  assert.equal(matchPrinter(ps, 'Desk'), null)
  assert.equal(matchPrinter([ps[0]], 'anything')?.id, 'workshop')
})

// a 10 mm cube, as text STL and as binary STL
const CUBE_V = [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10]]
const CUBE_F = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
function textCube(): ArrayBuffer {
  const s = ['solid c', ...CUBE_F.flatMap(f => ['facet normal 0 0 0', 'outer loop', ...f.map(i => `vertex ${CUBE_V[i].join(' ')}`), 'endloop', 'endfacet']), 'endsolid c'].join('\n')
  return new TextEncoder().encode(s).buffer as ArrayBuffer
}
function binaryCube(): ArrayBuffer {
  const buf = new ArrayBuffer(84 + CUBE_F.length * 50)
  const v = new DataView(buf)
  v.setUint32(80, CUBE_F.length, true)
  CUBE_F.forEach((f, t) => f.forEach((i, k) => CUBE_V[i].forEach((c, a) => v.setFloat32(84 + t * 50 + 12 + k * 12 + a * 4, c, true))))
  return buf
}

test('models are read from text STL, binary STL and OBJ; STEP has no picture', () => {
  assert.deepEqual(sizeOf(parseModel('a.stl', textCube())!), [10, 10, 10])
  assert.deepEqual(sizeOf(parseModel('a.STL', binaryCube())!), [10, 10, 10])
  const obj = new TextEncoder().encode('v 0 0 0\nv 20 0 0\nv 20 5 3\nv 0 5 3\nf 1 2 3 4\n').buffer as ArrayBuffer
  const tris = parseModel('a.obj', obj)!
  assert.equal(tris.length, 18)                          // a quad fans into two triangles
  assert.deepEqual(sizeOf(tris), [20, 5, 3])
  assert.equal(parseModel('a.step', obj), null)
})

test('drawing: only the faces towards the camera, the top among them', () => {
  const p = project(parseModel('a.stl', binaryCube())!)
  const shown = Array.from(p.keep).filter(Boolean).length
  assert.equal(shown, 6)                                  // three sides of a cube, two triangles each
  assert.equal(p.keep[2] && p.keep[3], 1)                 // the top
  assert.equal(p.keep[0] || p.keep[1], 0)                 // the bottom
  assert.deepEqual(rgb('#2563EB'), [37, 99, 235])
  assert.ok(rgb('#000000').every(c => c > 0))             // black filament still has a shape
})

test('which way down: a plate on its edge is laid on its biggest side, as the slicer turns it', () => {
  // a 30 x 20 x 3 plate tipped 60 degrees about X; its big face points (0, sin, -cos) after the tip
  const t = 60 * Math.PI / 180
  const rot = ([x, y, z]: number[]) => [x, y * Math.cos(t) - z * Math.sin(t), y * Math.sin(t) + z * Math.cos(t)]
  const V = [0, 30].flatMap(x => [0, 20].flatMap(y => [0, 3].map(z => rot([x, y, z]))))
  const F = [[0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3], [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6]]
  const tris = new Float32Array(F.flatMap(f => f.flatMap(i => V[i])))
  const s = sizeOf(tris)!
  assert.ok(s[2] > 15)                                   // standing up
  const down = [0, Math.sin(t), -Math.cos(t)]            // the big face that faced down before tipping
  const laid = sizeOf(layOn(tris, down))!
  assert.deepEqual(laid.map(v => Math.round(v)), [30, 20, 3])
  assert.equal(Math.min(...Array.from(layOn(tris, down)).filter((_, i) => i % 3 === 2)), 0)
})

test('every setting starts with what was done to the model', () => {
  const g = groupChanges([
    { key: 'wall_loops', label: 'Walls', value: '5', was: '3', why: '', source: 'purpose' },
    { key: 'orientation', label: 'Lying', value: 'flat on its biggest side', was: 'as in the file', why: 'Its biggest flat side wasn\'t down', source: 'model' },
  ], 'Strong', 'Workshop')
  assert.deepEqual(g.map(x => x.title), ['The model', "Because it's Strong"])
  assert.equal(g[0].rows[0].now, 'flat on its biggest side')
})

// ── more than one on the plate (design/plate/, A, picked 3 October 2026) ──
import { overflow, plateHeadline, plateLabel, plural } from '../src/slice/plan.ts'
import { centred, compose, provisional } from '../src/slice/plate.ts'

test('names read like the board: cleaned up, and counted', () => {
  assert.equal(modelName('[a]_buildplate_bushing_open_x1_r1s.stl'), 'Buildplate bushing open')   // same as the slicer
  assert.equal(modelName('[a]_knife_holder.stl'), 'Knife holder')
  assert.equal(plural('Bushing', 6), '6 bushings')
  assert.equal(plural('Box', 2), '2 boxes')
  assert.equal(plural('Knife holder', 1), '1 knife holder')
  assert.equal(plural('Buildplate bushing open', 6), '6 copies of buildplate bushing open')
  assert.equal(plateLabel([{ name: 'mount.stl', copies: 1 }]), 'Mount')
  assert.equal(plateLabel([{ name: 'bushing.stl', copies: 6 }]), '6 bushings')
  assert.equal(plateLabel([{ name: 'arm.stl', copies: 1 }, { name: 'knife.stl', copies: 2 }]), '3 parts')
})

test('the headline says what is on the plate, and when it takes two', () => {
  const one = [{ name: 'mount.stl', copies: 1 }], six = [{ name: 'bushing.stl', copies: 6 }]
  assert.equal(plateHeadline(one, 'done'), 'Mount is ready to print.')
  assert.equal(plateHeadline(one, 'done', 1, '84%'), 'Mount is ready, at 84%.')
  assert.equal(plateHeadline(six, 'done'), '6 bushings are ready to print.')
  assert.equal(plateHeadline([{ name: 'bushing.stl', copies: 30 }], 'done', 2), '30 bushings, on two plates.')
  assert.equal(plateHeadline(six, 'working'), 'Getting 6 bushings ready…')
  assert.equal(plateHeadline([{ name: 'a.stl', copies: 1 }, { name: 'b.stl', copies: 1 }], 'failed'), "2 parts couldn't be sliced.")
  assert.deepEqual(overflow([{ name: 'bushing.stl', copies: 30 }], [25]), { fit: 25, rest: 5 })
  assert.deepEqual(overflow(six, null), { fit: 6, rest: 0 })
})

test('the plate picture puts each copy where Orca said, turned as it said', () => {
  // a 10 x 4 x 2 box, its corner at (100, 100, 5) in the file
  const box = new Float32Array([100, 100, 5, 110, 100, 5, 110, 104, 7])
  const c = centred(box)
  assert.deepEqual(Array.from(c), [-5, -2, 0, 5, -2, 0, 5, 2, 2])
  assert.deepEqual(Array.from(centred(box, 2)).slice(0, 3), [-10, -4, 0])
  const at = compose([{ tris: box, copies: 2, scale: 1 }], [{ part: 0, x: 50, y: 60, turn: 0 }, { part: 0, x: 200, y: 100, turn: 90 }])
  assert.equal(at.length, 18)
  assert.deepEqual(Array.from(at.slice(0, 3)), [45, 58, 0])
  // turned a quarter anticlockwise: (-5, -2) → (2, -5)
  assert.deepEqual(Array.from(at.slice(9, 12)).map(v => Math.round(v * 1000) / 1000), [202, 95, 0])
  // a part that can't be read here (STEP) is left out of the picture, not the plate
  assert.equal(compose([{ tris: null, copies: 1, scale: 1 }, { tris: box, copies: 1, scale: 1 }], [{ part: 0, x: 0, y: 0, turn: 0 }, { part: 1, x: 0, y: 0, turn: 0 }]).length, 9)
})

test('before Orca has arranged them, copies stand in rows in the middle of the bed', () => {
  const box = new Float32Array([0, 0, 0, 40, 0, 0, 40, 50, 6])
  const at = provisional([{ tris: box, copies: 9, scale: 1 }], [350, 350, 340])
  assert.equal(at.length, 9)
  const xs = at.map(p => p.x), ys = at.map(p => p.y)
  assert.ok(Math.min(...xs) - 20 >= 0 && Math.max(...xs) + 20 <= 350, 'inside the bed across')
  assert.ok(Math.min(...ys) - 25 >= 0 && Math.max(...ys) + 25 <= 350, 'inside the bed front to back')
  assert.equal(new Set(ys).size, 2)             // 7 of 40 mm + 6 mm gaps fit a row of 350: two rows
  assert.ok(Math.abs((Math.min(...xs) + Math.max(...xs)) / 2 - 175) < 1, 'centred')
})

test('a plate the slicer made reads as a name, not a file', async () => {
  const { prettyName } = await import('../src/intent/jobs.ts')
  assert.equal(prettyName('buildplate_bushing_open_x25_1of2_PETG_2h26m.gcode'), 'Buildplate bushing open × 25 (plate 1 of 2)')
  assert.equal(prettyName('cutting_arm_g2e_and_2_more_PETG_20m42s.gcode'), 'Cutting arm g2e and 2 more')
  assert.equal(prettyName('mount_PETG_3m28s.gcode'), 'Mount')
})

test('a skipped copy says which part it was, so it can be printed again', async () => {
  const { skippedByPart, canPrintAgain } = await import('../src/slice/skipped.ts')
  const it = (name: string, state: 'printing' | 'waiting' | 'skipped') => ({ name, n: 1, label: '', where: '', center: [0, 0], polygon: [], state })
  const parts = { items: [it('p0c0__bushing.stl_id_0_copy_0', 'skipped'), it('p0c1__bushing.stl_id_1_copy_0', 'waiting'),
    it('p1c0__knife.stl_id_2_copy_0', 'skipped'), it('p0c2__bushing.stl_id_3_copy_0', 'skipped')], total: 4, left: 1, skipped: [], bed: [0, 0, 350, 350], can_skip: false }
  assert.deepEqual([...skippedByPart(parts)], [[0, 2], [1, 1]])
  assert.equal(canPrintAgain({ ...parts, items: [it('vent.stl_id_0_copy_0', 'skipped')] }), false, "Orca's own files: nothing to slice again from")
})

import { decodeLines } from '../src/slice/supports.ts'
import { lineView } from '../src/slice/render.ts'

test('support lines unpack from the slicer, and turn the way the part does (design/supports/, A)', () => {
  // two lines as slicer/elyir_bench_slice.py support_lines packs them: int16 LE, tenths of a mm
  const v = new Int16Array([200, 100, 200, 200, 2, -15, 0, 400, 400, 4])
  const segs = Buffer.from(new Uint8Array(v.buffer)).toString('base64')
  const d = decodeLines({ count: 2, width: 0.6, segs })
  assert.deepEqual(Array.from(d.lines).map(x => Math.round(x * 10) / 10), [20, 10, 20, 20, 0.2, -1.5, 0, 40, 40, 0.4])
  assert.equal(d.width, 0.6)
  const p = lineView(d.lines, { az: 0, el: 0 })            // straight on: x across, z up (screen y down)
  assert.deepEqual(Array.from(p.pts.slice(0, 4)).map(x => Math.round(x * 10) / 10), [20, -0.2, 20, -0.2])
  assert.equal(p.order.length, 2)
  assert.deepEqual(p.order, [1, 0])                          // the line further back is drawn first
})

const WALLS: Editable = { key: 'wall_loops', label: 'Walls', kind: 'number', min: 1, max: 10, step: 1, default: '2', help: '' }
const LAYER: Editable = { key: 'layer_height', label: 'Layer height', kind: 'number', min: 0.08, max: 0.32, step: 0.04, unit: 'mm', default: '0.2', help: '' }
const INSIDE: Editable = { key: 'sparse_infill_density', label: 'Inside', kind: 'number', min: 0, max: 100, step: 5, unit: '%', default: '15%', help: '' }
const BRIM: Editable = { key: 'brim_type', label: 'Brim', kind: 'choice', default: 'auto_brim', choices: [['auto_brim', 'Auto'], ['outer_only', 'All round']], help: '' }

test('a setting a person changes reads in their words, and steps by its own step (design/edit-settings/, C)', () => {
  assert.equal(editWords(LAYER, '0.2'), '0.2 mm')
  assert.equal(editWords(INSIDE, '25%'), '25%')
  assert.equal(editWords(BRIM, undefined), 'Auto')
  assert.equal(editWords(BRIM, 'outer_only'), 'All round')
  const l = steps(LAYER, '0.2')
  assert.deepEqual([l.at, l.last, l.value(l.at - 1), l.value(l.at + 1)], [3, 6, '0.16', '0.24'])
  const i = steps(INSIDE, '15%')
  assert.deepEqual([i.at, i.value(i.at + 2)], [3, '25%'])
  assert.equal(editSummary([WALLS, INSIDE, BRIM], { sparse_infill_density: '25%', wall_loops: '4' }), 'Walls 4 · Inside 25%')
})

test('Every setting splits kept, this print and the rest, each with its reason', () => {
  const ch = (key: string, value: string, source: SliceChange['source'], why = '') => ({ key, label: key, value, was: null, why, source })
  const r = editRows([WALLS, INSIDE, BRIM], { wall_loops: '5', sparse_infill_density: '25%', brim_type: 'auto_brim' }, { wall_loops: '3', sparse_infill_density: '15%' },
    [ch('wall_loops', '4', 'kept', 'Yours'), ch('wall_loops', '5', 'you', 'This print'), ch('sparse_infill_density', '25%', 'purpose', 'Denser inside')], 'Workshop')
  assert.deepEqual(r.you.map(x => [x.label, x.was, x.now]), [['Walls', '4', '5']])
  assert.deepEqual(r.kept, [])
  assert.deepEqual(r.rest.map(x => [x.label, x.now, x.why]), [['Inside', '25%', 'Denser inside'], ['Brim', 'Auto', "Workshop's own"]])
})

import { fileCounts, pickFrom, severalFrom } from '../src/slice/plate.ts'

test('picking from a file keeps its parts in place and in order, the rest wait off the plate (design/remove-parts/, C)', () => {
  const p = (key: number, from: string, order = 0) => ({ key, from, order })
  const stl = p(1, 'plug.stl'), arm = [p(10, 'arm.3mf', 0), p(11, 'arm.3mf', 1), p(12, 'arm.3mf', 2), p(13, 'arm.3mf', 3)], cap = p(2, 'cap.stl')
  const r = pickFrom([stl, ...arm, cap], [], 'arm.3mf', new Set([13, 11]))
  assert.deepEqual(r.parts.map(x => x.key), [1, 11, 13, 2])
  assert.deepEqual(r.left.map(x => x.key), [10, 12])
  // Change: put one back
  const r2 = pickFrom(r.parts, r.left, 'arm.3mf', new Set([10, 11, 13]))
  assert.deepEqual(r2.parts.map(x => x.key), [1, 10, 11, 13, 2])
  assert.deepEqual(r2.left.map(x => x.key), [12])
  assert.deepEqual(fileCounts(r2.parts, r2.left), [{ from: 'arm.3mf', on: 3, of: 4 }])
  assert.equal(severalFrom([stl, cap]), null)
  assert.equal(severalFrom([stl, ...arm]), 'arm.3mf')
})
