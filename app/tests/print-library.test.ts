// Pins the Print tab's library chosen on 3 October 2026 (design/print-library/, B "a shelf and a door").
// The boards there are the spec; if one of these fails, the tab has drifted from them.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  DAY, ago, chips, countLabel, emptyLine, filtered, hide, joinLibrary, listLine, metaLine, sentLine, sheetHistory,
  shelf, tileLine, withGhosts, type PastJob, type PrinterFile,
} from '../src/print/library.ts'
import { HIDDEN, hideFromRecent, listFiles, removeFile, type Call } from '../src/print/files.ts'

const NOW = new Date('2026-10-03T18:20:00').getTime() / 1000
const thumb = (n: string) => ({ thumbnails: [{ width: 400, height: 300, relative_path: `.thumbs/${n}.png` }] })
const file = (path: string, ageDays: number, meta: Record<string, unknown> = {}): PrinterFile =>
  ({ path, modified: NOW - ageDays * DAY, meta: { slicer: 'OrcaSlicer', filament_colors: ['#3B82F6'], ...meta } })
const job = (filename: string, daysAgo: number, status = 'completed', secs = 600, meta: Record<string, unknown> = {}): PastJob =>
  ({ filename, status, start_time: NOW - daysAgo * DAY, end_time: NOW - daysAgo * DAY + secs, print_duration: secs, metadata: meta })

const FILES = [
  file('lid.gcode', 5 / 1440, { estimated_time: 4320, filament_weight_total: 38, ...thumb('lid') }),
  file('spool_holder.gcode', 1.05, { estimated_time: 9600, filament_weight_total: 96, ...thumb('holder') }),
  file('hinge_pin.gcode', 12, { estimated_time: 720, filament_weight_total: 4 }),
  file('Benchy.gcode', 19, { slicer: 'PrusaSlicer', estimated_time: 3420, filament_weight_total: 13, ...thumb('benchy') }),
  file('phone_stand.gcode', 20, { estimated_time: 6000, filament_weight_total: 33, ...thumb('stand') }),
  file('Body80.gcode', 120, { estimated_time: 2460, filament_weight_total: 10, ...thumb('body80') }),
  file('Voron spares/voron_cube.gcode', 60, { estimated_time: 2880, filament_weight_total: 21, ...thumb('cube') }),
  file('Voron spares/skirt_clip.gcode', 61, { estimated_time: 1080 }),
]
const JOBS = [
  job('phone_stand.gcode', 1, 'completed', 6000),
  job('Benchy.gcode', 5, 'completed', 3400),
  job('Voron spares/voron_cube.gcode', 7),
  job('filament_guide.gcode', 14, 'completed', 1080, { estimated_time: 1080, ...thumb('guide') }),
  job('Body80.gcode', 22, 'klippy_shutdown', 20),
  job('Benchy.gcode', 27, 'completed', 3400),
  job('Benchy.gcode', 50, 'completed', 3400),
  job('phone_stand.gcode', 55, 'cancelled', 300),
  job('Body80.gcode', 123, 'completed', 2460),
  job('Voron spares/skirt_clip.gcode', 61),
]
const items = joinLibrary(FILES, JOBS)
const byName = (n: string) => items.find(i => i.filename === n)!

test('the library is the files on the printer, not the history (bug 1)', () => {
  assert.equal(items.filter(i => i.onPrinter).length, 8)
  // never printed and printed long ago are both there
  assert.equal(byName('hinge_pin.gcode').attempts, 0)
  assert.equal(byName('Body80.gcode').onPrinter, true)
  // history only says how often and when
  const benchy = byName('Benchy.gcode')
  assert.equal(benchy.printed, 3)
  assert.equal(benchy.lastPrinted, NOW - 5 * DAY + 3400)
  const stand = byName('phone_stand.gcode')
  assert.equal(stand.printed, 1)          // a cancelled attempt isn't a print
  assert.equal(stand.attempts, 2)
  assert.equal(byName('Voron spares/voron_cube.gcode').folder, 'Voron spares')
  assert.equal(byName('Voron spares/voron_cube.gcode').name, 'Voron cube')
})

test("a file's time is its own estimate, never the last attempt (bug 2)", () => {
  const body80 = byName('Body80.gcode')
  assert.equal(body80.estimate, 2460)     // not the 20 s of the shutdown on its last attempt
  assert.equal(metaLine(body80), '41 min · 10 g')
  // no estimate in the file: a finished print's duration, never a failed one
  const [only] = joinLibrary([file('x.gcode', 3, {})], [job('x.gcode', 1, 'klippy_shutdown', 20), job('x.gcode', 2, 'completed', 1500)])
  assert.equal(only.estimate, 1500)
})

test('a past print whose file is gone stays, honestly', () => {
  const guide = byName('filament_guide.gcode')
  assert.equal(guide.onPrinter, false)
  assert.equal(guide.printed, 1)
  assert.equal(tileLine(guide, null, 'shelf', NOW), null)   // the tile says "Not on the printer anymore" instead
  const s = shelf(items, NOW)
  assert.deepEqual(s.recent.map(i => i.name), ['Phone stand', 'Benchy', 'Voron cube', 'Filament guide', 'Body80', 'Skirt clip'])
  assert.equal(s.total, 8)                // gone files aren't counted as on the printer
})

test('"Remove from recent" hides only a gone file, and never touches history', async () => {
  const s = shelf(items, NOW, ['filament_guide.gcode', 'Benchy.gcode'])
  assert.ok(!s.recent.some(i => i.filename === 'filament_guide.gcode'))
  assert.ok(s.recent.some(i => i.filename === 'Benchy.gcode'))   // still on the printer: hiding doesn't apply
  assert.deepEqual(hide(['a', 'b'], 'a'), ['b', 'a'])
  const calls: [string, any][] = []
  const call: Call = async (m, p) => { calls.push([m, p]); return {} as any }
  const next = await hideFromRecent(call, ['old.gcode'], 'filament_guide.gcode')
  assert.deepEqual(next, ['old.gcode', 'filament_guide.gcode'])
  assert.deepEqual(calls, [['server.database.post_item', { ...HIDDEN, value: next }]])
  assert.ok(!calls.some(([m]) => m.startsWith('server.history')))
})

test('New is sent from the slicer and not printed yet, newest first; the shelf keeps six', () => {
  const s = shelf(items, NOW)
  assert.deepEqual(s.fresh.map(i => i.name), ['Lid', 'Spool holder'])   // hinge pin is never printed but 12 days old
  assert.equal(sentLine(s.fresh[0], NOW), 'Sent from Orca · 5 min ago')
  assert.equal(sentLine(s.fresh[1], NOW), 'Sent from Orca · yesterday')
  assert.equal(s.recent.length, 6)
  // the way into the library shows files that aren't on the shelf, with a picture
  assert.ok(s.peek.every(i => !s.recent.includes(i) && !s.fresh.includes(i)))
})

test('the filters: fits, never printed, printed before, under an hour, a chip per folder', () => {
  assert.deepEqual(chips(items).map(c => c.label), ["Fits what's loaded", 'Never printed', 'Printed before', 'Under an hour', 'Voron spares'])
  assert.equal(chips(items)[4].count, 2)
  const checks = { 'spool_holder.gcode': { ok: false, filename: 'spool_holder.gcode', missing: [], short: 'Needs Black PETG' } }
  assert.equal(filtered(items, 'fits', '', checks).length, 7)
  assert.deepEqual(filtered(items, 'never', '').map(i => i.name), ['Lid', 'Spool holder', 'Hinge pin'])
  assert.equal(filtered(items, 'before', '').length, 5)
  assert.deepEqual(filtered(items, 'hour', '').map(i => i.name), ['Hinge pin', 'Benchy', 'Voron cube', 'Skirt clip', 'Body80'])
  assert.deepEqual(filtered(items, 'folder:Voron spares', '').map(i => i.name), ['Voron cube', 'Skirt clip'])
  assert.deepEqual(filtered(items, null, 'BODY').map(i => i.name), ['Body80'])
  assert.deepEqual(filtered(items, null, '').map(i => i.name)[0], 'Lid')   // newest first
})

test('the count beside the title and the line on a phone', () => {
  assert.equal(countLabel(23, 23, null), '23 files')
  assert.equal(countLabel(17, 23, 'fits'), '17 of 23 fit')
  assert.equal(countLabel(2, 23, null, 'body'), '2 of 23 match')
  assert.equal(listLine(23, null), '23 files, newest first')
  assert.equal(listLine(3, 'never'), '3 never printed, newest first')
  assert.equal(emptyLine(null, '', 'Workshop'), 'Nothing on Workshop yet. Send a file from your slicer and it shows up here, under New.')
})

test("a tile's third line: what's in the way, then what's new, then its history", () => {
  const need = { ok: false, filename: 'spool_holder.gcode', missing: [], short: 'Needs Black PETG' }
  assert.deepEqual(tileLine(byName('spool_holder.gcode'), need, 'library', NOW), { text: 'Needs Black PETG', tone: 'need' })
  assert.deepEqual(tileLine(byName('lid.gcode'), null, 'library', NOW), { text: 'New · sent 5 min ago', tone: 'new' })
  assert.deepEqual(tileLine(byName('Benchy.gcode'), null, 'library', NOW), { text: 'Printed 3 times', tone: '' })
  assert.deepEqual(tileLine(byName('hinge_pin.gcode'), null, 'library', NOW), { text: 'Never printed', tone: '' })
  assert.deepEqual(tileLine(byName('Voron spares/voron_cube.gcode'), null, 'library', NOW), { text: 'in Voron spares', tone: '' })
  assert.equal(tileLine(byName('Benchy.gcode'), null, 'shelf', NOW), null)   // the shelf only says what's in the way
  // one spool and the printer isn't sure: the sheet asks; the tile doesn't warn
  assert.equal(tileLine(byName('spool_holder.gcode'), { ...need, ask: true }, 'shelf', NOW), null)
})

test("the sheet's history: how often, when, where it came from", () => {
  const h = sheetHistory(byName('Benchy.gcode'), 'Workshop', NOW)
  assert.equal(h.printed, 'Printed 3 times, last 5 days ago.')
  assert.equal(h.from, 'From PrusaSlicer, on Workshop since 14 September.')
  assert.equal(h.fromShort, 'From PrusaSlicer.')
  assert.equal(sheetHistory(byName('lid.gcode'), 'Workshop', NOW).from, 'From OrcaSlicer, sent 5 min ago.')
  assert.equal(sheetHistory(byName('lid.gcode'), 'Workshop', NOW).printed, 'Never printed.')
  assert.equal(sheetHistory(byName('spool_holder.gcode'), 'Workshop', NOW).from, 'From OrcaSlicer, sent yesterday.')
  assert.equal(sheetHistory(byName('Voron spares/voron_cube.gcode'), 'Workshop', NOW).printed, 'Printed once, 1 week ago.')
  assert.equal(ago(NOW - 300 * DAY, NOW), 'in December 2025')
})

test('a removed tile stays where it stood until the grid closes up', () => {
  const lib = filtered(items, null, '')
  const benchy = lib[3]
  const after = lib.filter(i => i !== benchy)
  assert.deepEqual(withGhosts(after, [{ item: benchy, index: 3 }]).map(i => i.name), lib.map(i => i.name))
  assert.deepEqual(withGhosts(after, []).map(i => i.name), after.map(i => i.name))
})

// ---- Moonraker, faked --------------------------------------------------------------------

function fakeMoonraker(o: { getDirectory?: boolean; deleteFails?: string } = {}) {
  const calls: [string, any][] = []
  const call: Call = async (method, p: any = {}) => {
    calls.push([method, p])
    switch (method) {
      case 'server.files.get_directory':
        if (o.getDirectory === false) throw new Error('Method not found')
        if (p.path === 'gcodes') return { dirs: [{ dirname: 'Voron spares' }, { dirname: '.thumbs' }], files: [
          { filename: 'Benchy.gcode', modified: 100, estimated_time: 3420, slicer: 'PrusaSlicer' },
          { filename: '.hidden.gcode', modified: 1 }, { filename: 'notes.txt', modified: 1 }] } as any
        if (p.path === 'gcodes/Voron spares') return { dirs: [], files: [{ filename: 'cube.gcode', modified: 50, estimated_time: 2880 }] } as any
        throw new Error('no such folder')
      case 'server.files.list':
        return [{ path: 'Benchy.gcode', modified: 100 }, { path: 'Voron spares/cube.gcode', modified: 50 }] as any
      case 'server.files.metadata':
        return { estimated_time: p.filename === 'Benchy.gcode' ? 3420 : 2880 } as any
      case 'server.files.delete_file':
        if (o.deleteFails) throw new Error(o.deleteFails)
        return { item: { path: p.path.slice(7), root: 'gcodes' }, action: 'delete_file' } as any
      default:
        return {} as any
    }
  }
  return { call, calls }
}

test('the files come from get_directory, folder by folder, with their metadata', async () => {
  const m = fakeMoonraker()
  const files = await listFiles(m.call)
  assert.deepEqual(files.map(f => [f.path, f.meta?.estimated_time]), [['Benchy.gcode', 3420], ['Voron spares/cube.gcode', 2880]])
  assert.ok(!m.calls.some(([, p]) => String(p.path).includes('.thumbs')))
  assert.deepEqual(m.calls[0], ['server.files.get_directory', { path: 'gcodes', extended: true }])
})

test('a Moonraker without get_directory: the list, then metadata per file', async () => {
  const m = fakeMoonraker({ getDirectory: false })
  const files = await listFiles(m.call)
  assert.deepEqual(files.map(f => [f.path, f.meta?.estimated_time]), [['Benchy.gcode', 3420], ['Voron spares/cube.gcode', 2880]])
  assert.deepEqual(m.calls.filter(([c]) => c === 'server.files.metadata').map(([, p]) => p.filename), ['Benchy.gcode', 'Voron spares/cube.gcode'])
})

test('remove: delete_file on the gcodes path, then off Recent too', async () => {
  const m = fakeMoonraker()
  const r = await removeFile(m.call, 'Voron spares/cube.gcode', { away: false, hidden: [] })
  assert.equal(r.ok, true)
  assert.deepEqual(r.hidden, ['Voron spares/cube.gcode'])
  assert.deepEqual(m.calls.map(([c]) => c), ['server.files.delete_file', 'server.database.post_item'])
  assert.deepEqual(m.calls[0][1], { path: 'gcodes/Voron spares/cube.gcode' })
})

test('remove is at home only: away nothing is called', async () => {
  const m = fakeMoonraker()
  const r = await removeFile(m.call, 'Benchy.gcode', { away: true, hidden: [] })
  assert.equal(r.ok, false)
  assert.equal(r.message, 'That has to be done at the printer.')
  assert.equal(m.calls.length, 0)
})

test("a refused delete says so, and nothing is taken off Recent", async () => {
  const m = fakeMoonraker({ deleteFails: 'File is loaded, DELETE not permitted' })
  const r = await removeFile(m.call, 'Benchy.gcode', { away: false, hidden: [] })
  assert.equal(r.ok, false)
  assert.equal(r.message, "It wasn't removed. The printer said: File is loaded, DELETE not permitted")
  assert.deepEqual(m.calls.map(([c]) => c), ['server.files.delete_file'])
})
