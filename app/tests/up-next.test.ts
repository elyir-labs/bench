// Pins Up next on the phone's Now when Ready, picked on 5 October 2026 (design/ready-phone/, C).
// The board there is the spec; if one of these fails, Now has drifted from it.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { DAY, joinLibrary, type PastJob, type PrinterFile } from '../src/print/library.ts'
import { upNext, UP_NEXT_MAX } from '../src/print/upnext.ts'
import type { CareItem } from '../src/intent/care.ts'

const NOW = new Date('2026-10-05T17:40:00').getTime() / 1000
const file = (path: string, ageDays: number, meta: Record<string, unknown> = {}): PrinterFile =>
  ({ path, modified: NOW - ageDays * DAY, meta: { slicer: 'OrcaSlicer', estimated_time: 4320, filament_weight_total: 38, filament_type: 'PLA', ...meta } })
const job = (filename: string, daysAgo: number, status = 'completed', secs = 600): PastJob =>
  ({ filename, status, start_time: NOW - daysAgo * DAY, end_time: NOW - daysAgo * DAY + secs, print_duration: secs })
const care = (name: string, due: boolean, snoozed = false): CareItem =>
  ({ id: name, name, note: '', due, snoozed, progress: due ? 1 : 0.2, label: due ? '40 of 40 print hours' : '8 of 40 print hours' })

const MIN = 1 / 1440

test('the board: a new file, Print again, Care that is due, in that order', () => {
  const items = joinLibrary(
    [file('lid.gcode', 6 * MIN), file('phone_stand.gcode', 20, { slicer: 'PrusaSlicer', estimated_time: 6000, filament_weight_total: 33 })],
    [job('phone_stand.gcode', 1)])
  const rows = upNext(items, [care('Clean the nozzle', false), care('Wipe the bed', true)], NOW)
  assert.deepEqual(rows.map(r => r.kind), ['new', 'again', 'care'])
  assert.deepEqual(rows.map(r => r.label), ['New from Orca · 6 min ago', 'Print again · yesterday', 'Care · due now'])
  assert.deepEqual(rows.map(r => r.name), ['Lid', 'Phone stand', 'Wipe the bed'])
  assert.equal(rows[0].meta, '1 h 12 m · 38 g · PLA')
  assert.equal(rows[2].meta, '40 of 40 print hours')
})

test('a file sent before the last print is not news any more; only the newest one shows', () => {
  const items = joinLibrary(
    [file('old.gcode', 2), file('a.gcode', 30 * MIN), file('b.gcode', 10 * MIN), file('stand.gcode', 20)],
    [job('stand.gcode', 1)])
  const rows = upNext(items, [], NOW)
  assert.deepEqual(rows.map(r => r.kind), ['new', 'again'])
  assert.equal(rows[0].kind === 'new' && rows[0].item.filename, 'b.gcode')
  const before = joinLibrary([file('old.gcode', 2), file('stand.gcode', 20)], [job('stand.gcode', 1)])
  assert.deepEqual(upNext(before, [], NOW).map(r => r.kind), ['again'])
})

test('a print that stopped is offered again, said honestly', () => {
  const items = joinLibrary([file('cube.gcode', 9)], [job('cube.gcode', 3, 'completed'), job('cube.gcode', 1, 'cancelled', 40)])
  const rows = upNext(items, [], NOW)
  assert.equal(rows[0].label, 'Try again · stopped yesterday')
})

test('a last print whose file is gone gets no row', () => {
  const items = joinLibrary([], [job('gone.gcode', 1)])
  assert.deepEqual(upNext(items, [], NOW), [])
})

test('nothing printed and nothing new: Print a model', () => {
  assert.deepEqual(upNext([], [], NOW).map(r => [r.kind, r.name]), [['start', 'Print a model']])
  const rows = upNext(joinLibrary([file('lid.gcode', MIN)], []), null, NOW)
  assert.deepEqual(rows.map(r => r.kind), ['new'])
})

test('snoozed or not-due care stays in Care; never more than three rows', () => {
  const items = joinLibrary([file('lid.gcode', MIN), file('stand.gcode', 20)], [job('stand.gcode', 1)])
  const rows = upNext(items, [care('Wipe the bed', true, true), care('Check the belts', true), care('Lube', true)], NOW)
  assert.deepEqual(rows.map(r => r.name), ['Lid', 'Stand', 'Check the belts'])
  assert.equal(rows.length, UP_NEXT_MAX)
})

test('PrusaSlicer is Prusa in the row, so it fits a phone', () => {
  const rows = upNext(joinLibrary([file('lid.gcode', 6 * MIN, { slicer: 'PrusaSlicer' })], []), [], NOW)
  assert.equal(rows[0].label, 'New from Prusa · 6 min ago')
})

test('the same model sliced again is the new row, not a second row', () => {
  const items = joinLibrary([file('phone_stand.gcode', 20), file('v2/phone_stand.gcode', 5 * MIN)], [job('phone_stand.gcode', 1)])
  const rows = upNext(items, [], NOW)
  assert.deepEqual(rows.map(r => [r.kind, r.name]), [['new', 'Phone stand']])
  assert.equal(rows[0].kind === 'new' && rows[0].item.filename, 'v2/phone_stand.gcode')
})
