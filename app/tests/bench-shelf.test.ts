// Pins printing from the Bench Box's shelf (design/bench-print/, A): the filaments across the bench, and where a
// model in one can print, the soonest free with it loaded first, with why for every other printer.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { choices, colorName, filamentFor, filaments, firstPick, foldShelf, lastLine, printOn, queueSentence, shelfCard, shelfSentence, timeable, type QueueItem } from '../src/bench-app/shelf.ts'
import { ordered, sentence, withQueue } from '../src/bench-app/bench.ts'
import type { BenchPrinter } from '../src/bench-app/bench.ts'

const WHITE = '#F4F4F2', GRAY = '#8A8D91', BLACK = '#1C1C1E'
const job = (name: string, eta: string, remaining: number) =>
  ({ name, filename: name + '.gcode', thumbnail: null, grams: null, state: 'printing', progress: 0.4, layer: null, layers: null,
     elapsed_s: 0, total_s: 0, remaining_s: remaining, eta: null, eta_clock: eta, estimated_s: null, colors: [], material: 'petg' })
const spool = (slot: number, material: string, color: string, extra: Record<string, unknown> = {}) =>
  ({ slot, material, color, grams: 800, status: 'ready', in_use: false, rfid: false, ...extra })
const intent = (state: string, spools: unknown[], extra: Record<string, unknown> = {}) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools, ...extra }) as any
const P = (name: string, i: any, live = true): BenchPrinter => ({ id: name.toLowerCase().replace(/ /g, ''), name, live, intent: i })

// the bench on design/bench-print's boards
const BENCH = [
  P('Workshop', intent('printing', [spool(0, 'PETG', GRAY, { in_use: true }), spool(4, 'PLA', WHITE)], { job: job('Phone stand', '4:20 pm', 5600) })),
  P('Studio', intent('needs_you', [spool(0, 'PLA', WHITE), spool(1, 'PLA', WHITE, { status: 'empty' })], { headline: 'Slot 2 ran out.' })),
  P('Kobra Max', intent('finished', [spool(0, 'PLA', BLACK, { direct: true })])),
  P('Desk', intent('ready', [spool(0, 'PLA', '#F2F2F0', { direct: true })], { detail: 'White PLA loaded.' })),
  P('Kobra 3 #2', null, false),
]
const ALL: Record<string, { materials: string[] }> = Object.fromEntries(['workshop', 'studio', 'kobramax', 'desk'].map((id) => [id, { materials: ['PLA', 'PETG', 'ASA'] }]))

test('the filaments loaded across the bench, the most widely loaded first, named as people say them', () => {
  assert.deepEqual(filaments(BENCH).map((f) => [f.name, f.on]), [
    ['White PLA', ['Workshop', 'Studio', 'Desk']], ['Black PLA', ['Kobra Max']], ['Gray PETG', ['Workshop']]])
  assert.equal(filamentFor(filaments(BENCH), 'pla', '#F0F0EE')?.name, 'White PLA')   // what it was last printed in
  assert.equal(filamentFor(filaments(BENCH), 'ASA', null), null)
  assert.equal(colorName('#FF8800'), 'Orange')
  assert.equal(colorName('#00FFFF'), '')
})

test('a model in white PLA: the soonest free with it loaded, then why each other printer is where it is', () => {
  const white = filaments(BENCH)[0]
  const rows = printOn(BENCH, white, ALL)
  assert.deepEqual(rows.map((r) => [r.name, r.fits, r.line]), [
    ['Desk', true, 'Free now: it has White PLA'],
    ['Workshop', true, 'After the phone stand, about 4:20 pm · White PLA in slot 5'],
    ['Kobra Max', false, 'It has Black PLA, not White PLA'],
    ['Studio', false, 'Stopped: Slot 2 ran out.'],
  ])
  assert.deepEqual(rows.map((r) => r.now), [true, false, true, false])   // Workshop is printing: it only gets the file
  assert.deepEqual([rows[0].slot, rows[1].slot], [null, 5])    // Desk's one spool feeds the head; Workshop's is slot 5
  assert.equal(firstPick(rows)?.name, 'Desk')
  assert.equal(firstPick(rows, 'workshop')?.name, 'Workshop')          // a tile's Print a model asks for its printer
  assert.equal(firstPick(rows, 'kobramax')?.name, 'Desk')      // ...unless it can't take it
})

test("a printer the box can't set a model up for, or without settings for the material, says so", () => {
  const gray = filaments(BENCH).find((f) => f.material === 'PETG')!
  const rows = printOn(BENCH, gray, { ...ALL, desk: { error: "Desk can't slice here yet: no profile." }, workshop: { materials: ['PLA'] } })
  assert.deepEqual(rows.map((r) => [r.name, r.fits, r.line]), [
    ['Desk', false, "The box can't set a model up for it yet"],
    ['Kobra Max', false, 'It has Black PLA, not Gray PETG'],
    ['Workshop', false, 'It has no PETG settings'],
    ['Studio', false, 'Stopped: Slot 2 ran out.'],
  ])
  assert.equal(firstPick(rows), null)
})

test('the line over the shelf says which printer is free, or which is next', () => {
  assert.equal(shelfSentence(BENCH), 'Desk is free. What should it print?')
  assert.equal(shelfSentence(BENCH.filter((p) => p.name !== 'Desk')), 'Kobra Max is free once its bed is cleared.')
  assert.equal(shelfSentence([BENCH[0]]), 'Nothing is free right now. Workshop is next, about 4:20 pm.')
  assert.equal(shelfSentence([BENCH[1]]), 'No printer is free right now.')
})

test("a shelf model's line: where and when it last printed, in what, or when it was added", () => {
  const now = new Date(2026, 9, 4, 16, 3)
  const at = (d: number, h = 10) => new Date(2026, 9, d, h).getTime() / 1000
  assert.equal(lastLine({ added: at(4), last: null }, now), 'Added today')
  assert.equal(lastLine({ added: at(1), last: { printer_name: 'Desk', copies: 4, material: 'pla', color: WHITE, at: at(3) } }, now), 'Desk · yesterday · White PLA × 4')
  assert.equal(lastLine({ added: at(1), last: { printer_name: 'Workshop', copies: 1, material: 'PETG', color: GRAY, at: at(1) } }, now), 'Workshop · Thursday · Gray PETG')
  assert.equal(lastLine({ added: at(1), last: { printer_name: 'Workshop', copies: 1, material: null, color: null, at: new Date(2026, 8, 20).getTime() / 1000 } }, now), 'Workshop · Sep 20')
})

test("a model printed from a printer's own Print says so, without naming the printer twice", () => {
  const now = new Date(2026, 9, 4, 16, 3)
  const at = new Date(2026, 9, 4, 10).getTime() / 1000
  const from = { printer_name: 'Workshop', at }
  const last = { printer_name: 'Workshop', copies: 1, material: 'PETG', color: GRAY, at }
  assert.deepEqual(shelfCard({ added: at, last, from }, now), { tag: "From Workshop's Print", line: 'today · Gray PETG' })
  // printed again since, on Desk from the box: the line is that print's
  assert.deepEqual(shelfCard({ added: at, last: { ...last, printer_name: 'Desk', at: at + 60 }, from }, now),
                   { tag: "From Workshop's Print", line: 'Desk · today · Gray PETG' })
  assert.deepEqual(shelfCard({ added: at, last: null }, now), { tag: null, line: 'Added today' })
})

test('Tidy A: the last 30 days on show, older ones folded with the month they last printed', () => {
  const now = new Date(2026, 9, 5, 9)
  const day = (m: number, d: number) => new Date(2026, m, d).getTime() / 1000
  const items = [{ id: 'a', added: day(9, 4), last: null }, { id: 'b', added: day(7, 1), last: { at: day(8, 20) } },
                 { id: 'c', added: day(6, 1), last: { at: day(8, 2) } }, { id: 'd', added: day(5, 1), last: null }]
  const f = foldShelf(items, now)
  assert.deepEqual([f.recent.map((i) => i.id), f.older.map((i) => i.id), f.since], [['a', 'b'], ['c', 'd'], 'September'])
  assert.deepEqual(foldShelf(items.slice(0, 2), now).since, null)
})

// written out, not uppercased: the public copy renames each name, and an uppercased rename isn't one
const NAMES: Record<string, string> = { desk: 'Desk', workshop: 'Workshop', studio: 'Studio' }
const q = (state: string, printer: string | null = null, extra: Partial<QueueItem> = {}): QueueItem =>
  ({ id: state + printer, shelf: 's', name: 'Cable clip', copies: 6, material: 'PLA', color: WHITE, state, printer,
     printer_name: printer ? NAMES[printer] : null, time: null, line: '', error: null, ...extra }) as QueueItem

test('Queue A: the line over the queue, and the printer whose bed a queued print waits for', () => {
  assert.equal(queueSentence([q('ready', 'desk'), q('waiting'), q('waiting')]), 'Three waiting. Desk can start the next now.')
  assert.equal(queueSentence([q('setting', 'desk')]), 'One waiting.')
  assert.equal(queueSentence([]), null)
  const tiles = withQueue(ordered(BENCH), [q('ready', 'desk')])
  const desk = tiles.find((t) => t.id === 'desk')!
  assert.deepEqual([desk.tone, desk.word, desk.says, desk.what, desk.action], ['amber', 'Next up', 'Clear the bed', 'Cable clip × 6 · from the queue', "It's clear, start"])
  assert.equal(tiles.find((t) => t.id === 'workshop')!.word, 'Printing')                  // a printing printer is never asked
  // Workshop printing and Desk waiting for its bed: the sentence asks for Desk's bed
  assert.equal(sentence(withQueue(ordered([BENCH[0], BENCH[3]]), [q('ready', 'desk')])),
               'Desk is next: clear its bed to start the cable clip. Workshop is done at 4:20 pm.')
})

test("a printer whose one spool nobody described takes any filament it has settings for, and asks at the start", () => {
  const kobra = P('Kobra 3', intent('ready', [{ slot: 0, material: null, color: null, grams: null, status: 'unknown', in_use: false, rfid: false, direct: true }]))
  const white = filaments(BENCH)[0]
  const rows = printOn([...BENCH, kobra], white, { ...ALL, 'kobra3': { materials: ['PLA'] } })
  assert.deepEqual(rows.slice(0, 3).map((r) => [r.name, r.fits, r.line]), [
    ['Desk', true, 'Free now: it has White PLA'],
    ['Workshop', true, 'After the phone stand, about 4:20 pm · White PLA in slot 5'],
    ['Kobra 3', true, "Free now: it asks what's loaded when it starts"],   // after the ones known to have it
  ])
  assert.equal(rows[2].asks, true)
  const petg = printOn([kobra], { key: 'PETG', material: 'PETG', color: null, name: 'PETG', on: [] }, { kobra3: { materials: ['PLA'] } })
  assert.deepEqual(petg.map((r) => [r.fits, r.line]), [[false, 'It has no PETG settings']])
  assert.equal(firstPick(printOn([kobra], white, { kobra3: { materials: ['PLA'] } }))?.name, 'Kobra 3')
})

test('when a printer asks what is on its one spool, its materials are offered in any color, and match any color loaded', () => {
  const kobra = P('Kobra 3', intent('ready', [{ slot: 0, material: null, color: null, grams: null, status: 'unknown', in_use: false, rfid: false, direct: true }]))
  const can = { ...ALL, kobra3: { materials: ['TPU', 'PETG', 'PLA'] } }
  assert.deepEqual(choices([...BENCH, kobra], can).map((f) => f.name), ['White PLA', 'Black PLA', 'Gray PETG', 'Any PLA', 'Any PETG', 'Any TPU'])
  assert.deepEqual(choices(BENCH, ALL).map((f) => f.name), filaments(BENCH).map((f) => f.name))      // nobody asks: as before
  const pla = choices([...BENCH, kobra], can).find((f) => f.key === 'PLA')!
  assert.deepEqual(printOn([...BENCH, kobra], pla, can).filter((r) => r.fits).map((r) => r.name), ['Desk', 'Kobra Max', 'Workshop', 'Kobra 3'])
})

test('every printer the box can set the filament up for gets a time on its row (design/bench-look/, C)', () => {
  const row = (id: string, o: Record<string, unknown> = {}) => ({ id, name: id.toUpperCase(), free: true, line: '', fits: true, slot: null, now: true, ...o }) as never
  const rows = [row('workshop'), row('kobra3', { fits: false }), row('desk', { stopped: true }), row('k3max'), row('studio')]
  const printable = { workshop: { materials: ['PLA', 'ABS'], slots: 8 }, kobra3: { materials: ['PLA'], slots: 4 }, desk: { materials: ['PLA'], slots: 1 },
    k3max: { error: "can't slice here yet" }, studio: { materials: ['PETG'], slots: 1 } } as never
  const pla = { key: 'PLA', material: 'PLA', color: null, name: 'Any PLA', on: [] } as never
  // another filament loaded still gets a time; stopped, no settings for it, or not set up at all: none
  assert.deepEqual(timeable(rows, printable, pla), ['workshop', 'kobra3'])
  assert.deepEqual(timeable(rows, printable, null), [])
})
