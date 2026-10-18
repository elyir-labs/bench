// Pins several models from the Bench Box's shelf at once (design/bench-several/, C, picked 10 October 2026): picking on the
// shelf, the plan's cards, strips and lines from a plan as bench/plan.py answers it, moving a model, a split bed's Keep
// them all, and a bed in Up next. The plan's rules are the service's (bench/tests/test_plan.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bedHow, bedHowLine, bedHowSaves, bedTiles, withHow, bedLabel, cardsOf, chipOf, costOf, filamentLine, footBar, footOf, freeLine, keepAll, modelLine, moveOptions, bedOptions, moveBed, filKeyOf, filOf, inChoices, noteOf, pickLine, picksFromQuery,
         picksOf, picksToQuery, planHeadline, plateSpots, setPick, splitsOf, stripsOf, toggle, UNTIMED, type Plan, type PlanBed, type PlanModel } from '../src/bench-app/several.ts'
import { queueSentence, queueTitle, type QueueItem } from '../src/bench-app/shelf.ts'
import { ordered, withQueue, type BenchPrinter } from '../src/bench-app/bench.ts'

const GRAY = '#8A8D91', BLUE = '#2563EB', WHITE = '#F4F4F2', BLACK = '#1C1C1E'
const at = (h: number, m: number) => new Date(2026, 9, 10, h, m).getTime() / 1000
const NOW = at(18, 55)
const M = (shelf: string, name: string, copies: number, o: Partial<PlanModel> = {}): PlanModel =>
  ({ shelf, name, copies, of: copies, picture: `/bench/shelf/${shelf}/picture`, first: false, ...o })
const bed = (printer: string | null, name: string | null, models: PlanModel[], o: Partial<PlanBed> = {}): PlanBed => ({
  id: `${printer ?? 'waits'}:1:${models[0].shelf}`, printer, printer_name: name, order: 1, material: 'PETG', color: GRAY, slot: null, filament: null,
  filament_name: null, words: 'Gray PETG', asks: false, purpose: 'everyday', supports: null, settings: {}, models, fits: true, split: false,
  seconds: null, grams: null, rough: true, when: { kind: 'now' }, start_at: NOW, done_at: null, why: '', ...o })

// the plan on the board C-plan, as POST /bench/plan answers it
const PLAN: Plan = {
  checking: false,
  beds: [
    bed('workshop', 'Workshop', [M('stand', 'Phone stand', 2), M('clips', 'Cable clips', 4)],
        { slot: 3, seconds: 6000, grams: 58, done_at: at(20, 35), why: 'Gray PETG in slot 3.' }),
    bed('kobra3', 'Kobra 3', [M('tray', 'Battery tray', 1)],
        { material: 'PLA', color: BLUE, words: 'Blue PLA', asks: true, seconds: 12360, grams: 112, done_at: at(22, 25),
          why: "It asks what's loaded when it starts: put Blue PLA on." }),
    bed('studio', 'Studio', [M('hinge', 'Hinge', 6)],
        { material: 'PLA', color: WHITE, words: 'White PLA', when: { kind: 'next', clock: '7:40 pm', at: at(19, 40) }, start_at: at(19, 40),
          seconds: 3120, grams: 18, done_at: at(20, 32), why: 'Waits in Up next until Studio is done and its bed is clear.' }),
    bed(null, null, [M('vent', 'Vent', 1)],
        { material: 'ASA', color: BLACK, words: 'Black ASA', when: { kind: 'waits' }, start_at: null, why: "Black ASA isn't loaded on any printer. It waits in Up next until one has it." }),
  ],
  cant: [], out: [], said: [], free_left: [{ id: 'kobra3-2', name: 'Kobra 3 #2' }, { id: 'desk', name: 'Desk' }], printers: 3, done_at: at(22, 25), ahead: 0,
}

test('Select ticks in the order picked; the bar at the foot says how many, which, and Print N models (C-select)', () => {
  let ids = toggle([], 'stand')
  ids = toggle(ids, 'clips')
  ids = toggle(toggle(ids, 'tray'), 'tray')
  assert.deepEqual(ids, ['stand', 'clips'])
  assert.equal(pickLine(5), '5 picked. The box works out where each prints.')
  assert.equal(pickLine(0), 'Tap the models to print together.')
  assert.deepEqual(footBar(['Phone stand', 'Cable clips', 'Battery tray', 'Hinge', 'Vent']),
                   { count: '5 models', names: 'Phone stand, Cable clips, Battery tray, Hinge, Vent', go: 'Print 5 models' })
  assert.deepEqual(footBar(['Vent']), { count: '1 model', names: 'Vent', go: 'Print 1 model' })
  assert.equal(footBar([]).go, 'Print')
  // each with the copies it last printed with; the picks ride in the address, moves too, so a reload keeps them
  const picks = picksOf(['stand', 'mount'], [{ id: 'stand', last: { copies: 2 } }, { id: 'mount', last: null }])
  assert.deepEqual(picks, [{ shelf: 'stand', copies: 2 }, { shelf: 'mount', copies: 1 }])
  const moved = [...picks, { shelf: 'clips', copies: 4, printer: 'kobra3-2' }, { shelf: 'tray', copies: 1, printer: 'workshop', bed: 'own' as const },
                 { shelf: 'vent', copies: 1, out: true as const }]
  assert.equal(picksToQuery(moved), 'stand~2,mount~1,clips~4~on%3Akobra3-2,tray~1~own%3Aworkshop,vent~1~out')
  assert.deepEqual(picksFromQuery(picksToQuery(moved)), moved)
  assert.deepEqual(picksFromQuery('a~0,a~3,b~999'), [{ shelf: 'a', copies: 1 }, { shelf: 'b', copies: 200 }])
  assert.deepEqual(picksFromQuery(undefined), [])
})

test('the plan: the headline, a card per printer with its chip, filament, bed and models, and its time (C-plan)', () => {
  assert.equal(planHeadline(PLAN), 'Five models, three printers.')
  const cards = cardsOf(PLAN)
  assert.deepEqual(cards.map((b) => [b.printer_name, chipOf(b).word, chipOf(b).tone, filamentLine(b, b.printer === 'studio' ? 'A lid' : null), bedLabel(b)]), [
    ['Workshop', 'Free now', 'green', 'Gray PETG in slot 3', 'One bed'],
    ['Kobra 3', 'Free now', 'green', "Blue PLA · it asks what's loaded", 'One bed'],
    ['Studio', 'Next, about 7:40 pm', 'gray', 'White PLA · printing a lid now', 'Its next bed'],
  ])
  assert.deepEqual(cards[0].models.map((m) => [m.name, m.copies, modelLine(PLAN, cards[0], m)]),
                   [['Phone stand', 2, 'Gray PETG, as last time'], ['Cable clips', 4, 'Gray PETG, as last time']])
  // the note only when there's more to say than the chip: it asks, it waits its turn
  assert.deepEqual(cards.map(noteOf), ['', "It asks what's loaded when it starts: put Blue PLA on.", 'Waits in Up next until Studio is done and its bed is clear.'])
  assert.deepEqual(cards.map((b) => costOf(b)), [
    { cost: '1 h 40 min · 58 g', done: 'done about 8:35 pm' }, { cost: '3 h 26 min · 112 g', done: 'done about 10:25 pm' },
    { cost: '52 min · 18 g', done: 'done about 8:32 pm' }])
  // a model never timed alone: nothing invented
  const untimed = bed('desk', 'Desk', [M('mount', 'Mount', 1, { first: true })], { words: 'Black PETG' })
  assert.deepEqual(costOf(untimed), { cost: '', done: '' })
  assert.equal(UNTIMED, "Timed once it's set up")
  assert.equal(modelLine(PLAN, untimed, untimed.models[0]), "Black PETG, what's loaded")
  assert.equal(planHeadline({ ...PLAN, beds: [PLAN.beds[3]], printers: 0, free_left: [] }), 'One model. No printer can take it now.')
  assert.equal(planHeadline({ ...PLAN, beds: [], free_left: [] }), 'Nothing left to print.')
})

test('nothing can print it now: an amber strip with Take it out; the printers left free are named; the foot (C-plan)', () => {
  const cant = { ...PLAN, cant: [{ shelf: 'pod', name: 'Bench box pod', copies: 1, why: "Studio has White PLA, not White ABS." }] }
  assert.deepEqual(stripsOf(cant).map((s) => [s.title, s.line, s.shelves, s.short]), [
    ['Vent · Black ASA', "Black ASA isn't loaded on any printer. It waits in Up next until one has it.", ['vent'], "The vent waits: Black ASA isn't loaded anywhere."],
    ['Bench box pod', 'Studio has White PLA, not White ABS.', ['pod'], 'Bench box pod: Studio has White PLA, not White ABS.'],
  ])
  assert.equal(planHeadline(cant), 'Six models, three printers.')
  assert.equal(freeLine(PLAN), 'Kobra 3 #2 and Desk are free too: none of these need them. Tap a model to move it.')
  assert.equal(freeLine({ ...PLAN, free_left: [] }), 'Tap a model to move it.')
  assert.deepEqual(footOf(PLAN, false), { done: 'All done about 10:25 pm.', line: 'Each printer asks about its bed before it starts.',
                                          go: 'Print all · 3 printers', short: 'Print all', can: true })
  // away, a phone adds the plan to the queue: nothing starts
  assert.deepEqual(footOf(PLAN, true), { done: 'All done about 10:25 pm.', line: 'Nothing starts until someone at home says each bed is clear.',
                                         go: 'Add to the queue', short: 'Add to the queue', can: true })
  // still checking what fits: it says so, and Print all waits
  assert.deepEqual(footOf({ ...PLAN, checking: true }, false), { done: 'Working it out…', line: 'The box checks what fits each bed.',
                                                                 go: 'Working it out…', short: 'Working it out…', can: false })
  assert.equal(footOf({ ...PLAN, done_at: null }, false).done, '')            // a bed never timed: no all-done time
})

const live = (state: string, spools: unknown[], extra: Record<string, unknown> = {}) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools, ...extra }) as never
const spool = (slot: number, material: string, color: string, extra: Record<string, unknown> = {}) =>
  ({ slot, material, color, grams: 800, status: 'ready', in_use: false, rfid: false, ...extra })
const P = (id: string, name: string, i: unknown): BenchPrinter => ({ id, name, live: true, intent: i as never })
const BENCH = [
  P('workshop', 'Workshop', live('ready', [spool(2, 'PETG', GRAY), spool(4, 'PLA', WHITE)], { detail: 'Gray PETG loaded.' })),
  P('kobra3-2', 'Kobra 3 #2', live('ready', [spool(0, 'PETG', GRAY, { direct: true })])),
  P('studio', 'Studio', live('printing', [spool(0, 'PLA', WHITE, { direct: true })], { job: { name: 'Lid', remaining_s: 2700, eta_clock: '7:40 pm' } })),
]

test('moving a model: as the box planned it, each printer that can take it, its own bed, and why the others cannot (C-move)', () => {
  const workshop = PLAN.beds[0]
  const picks = [{ shelf: 'stand', copies: 2 }, { shelf: 'clips', copies: 4 }]
  const opts = moveOptions(workshop, 'stand', picks, BENCH, {})
  assert.deepEqual(opts.map((o) => [o.title, o.line, o.on, o.off]), [
    ['Workshop, with the cable clips', 'One bed, as the box planned it', true, false],
    ['Kobra 3 #2', 'Free now: it has Gray PETG', false, false],
    ['Workshop, its own bed', 'After the cable clips: Workshop asks about its bed again', false, false],
    ['Studio', 'It has White PLA, not Gray PETG', false, true],
  ])
  assert.deepEqual(opts.map((o) => o.patch), [{ printer: undefined, bed: undefined }, { printer: 'kobra3-2', bed: undefined },
                                              { printer: 'workshop', bed: 'own' }, { printer: 'studio', bed: undefined }])
  // moved to Kobra 3 #2: its card says so, and the box's own choice is one tap back
  const moved = setPick(picks, 'stand', opts[1].patch)
  assert.deepEqual(moved, [{ shelf: 'stand', copies: 2, printer: 'kobra3-2' }, { shelf: 'clips', copies: 4 }])
  const there = bed('kobra3-2', 'Kobra 3 #2', [M('stand', 'Phone stand', 2)])
  assert.deepEqual(chipOf(there, moved), { word: 'Moved here', tone: 'blue' })
  const again = moveOptions(there, 'stand', moved, BENCH, {})
  assert.deepEqual(again.map((o) => [o.title, o.on]), [['Where the box puts it', false], ['Kobra 3 #2', true], ['Workshop', false], ['Studio', false]])
  assert.deepEqual(setPick(moved, 'stand', again[0].patch), picks)
  // copies stay between 1 and 200; Take it out leaves it out of the plan
  assert.deepEqual(setPick(picks, 'clips', { copies: 0 })[1].copies, 1)
  assert.deepEqual(setPick(picks, 'clips', { out: true })[1], { shelf: 'clips', copies: 4, out: true })
})

test('too much for one bed: what the box said, and Keep them all on Workshop, which asks for Workshop for each of its models (C-edge)', () => {
  const said = 'Not all of it fits one bed on Workshop: Cable clips × 8 go on Kobra 3 #2, which has Gray PETG too.'
  const split = { ...PLAN, said: [said], beds: [
    bed('workshop', 'Workshop', [M('stand', 'Phone stand', 2), M('clips', 'Cable clips', 22, { of: 30 })], { split: true }),
    bed('kobra3-2', 'Kobra 3 #2', [M('clips', 'Cable clips', 8, { of: 30 })]), ...PLAN.beds.slice(1)] }
  assert.equal(planHeadline(split), 'Five models, three printers.')
  assert.deepEqual(splitsOf(split), [{ printer: 'workshop', said, shelves: ['stand', 'clips'], keep: 'Keep them all on Workshop' }])
  assert.deepEqual(split.beds.slice(0, 2).map((b) => modelLine(split, b, b.models[b.models.length - 1])), ['22 of 30', 'the other 8'])
  const picks = [{ shelf: 'stand', copies: 2 }, { shelf: 'clips', copies: 30 }, { shelf: 'tray', copies: 1 }]
  assert.deepEqual(keepAll(picks, splitsOf(split)[0]),
                   [{ shelf: 'stand', copies: 2, printer: 'workshop' }, { shelf: 'clips', copies: 30, printer: 'workshop' }, { shelf: 'tray', copies: 1 }])
  // kept there: the rest is a second bed on Workshop, after the first, and there is nothing left to keep
  const kept = { ...split, said: ['Not all of it fits one bed on Workshop: Cable clips × 8 go on a second bed there, after the first.'], beds: [
    split.beds[0], bed('workshop', 'Workshop', [M('clips', 'Cable clips', 8, { of: 30 })], { order: 2, when: { kind: 'after' } })] }
  assert.equal(splitsOf(kept)[0].keep, null)
  assert.deepEqual([bedLabel(kept.beds[1]), chipOf(kept.beds[1]).word], ['Second bed, after the first', 'After bed 1'])
})

test("a bed's picture: its models' copies dealt in turn onto the plate, never more than fit the drawing", () => {
  const spots = plateSpots([{ picture: 'a', copies: 2 }, { picture: 'b', copies: 4 }])
  assert.deepEqual(spots.map((s) => s.picture), ['a', 'b', 'a', 'b', 'b', 'b'])
  assert.ok(spots.every((s) => s.x > 0 && s.x < 180 && s.y > 0 && s.y < 72))
  assert.equal(plateSpots([{ picture: 'c', copies: 200 }]).length, 36)
  assert.deepEqual(plateSpots([]), [])
})

const row = (o: Partial<QueueItem>): QueueItem =>
  ({ id: 'q', shelf: 'stand', name: 'Phone stand', copies: 1, material: 'PETG', color: GRAY, state: 'waiting', printer: null, printer_name: null,
     time: null, line: '', error: null, ...o }) as QueueItem

test('sent: a bed in Up next is one row with its name as the box says it, never the copies twice; two printers can start (C-sent)', () => {
  const pair = row({ name: 'Phone stand × 2, Cable clips × 4', copies: 6, bed: true, on: 'workshop', on_name: 'Workshop', state: 'ready', printer: 'workshop', printer_name: 'Workshop',
                     models: [{ shelf: 'stand', name: 'Phone stand', copies: 2 }, { shelf: 'clips', name: 'Cable clips', copies: 4 }] })
  const hinge = row({ name: 'Hinge × 6', copies: 6, bed: true, on: 'studio', models: [{ shelf: 'hinge', name: 'Hinge', copies: 6 }] })
  const single = row({ name: 'Cap', copies: 2, models: [{ shelf: 'cap', name: 'Cap', copies: 2 }] })
  assert.deepEqual([pair, hinge, single].map(queueTitle), ['Phone stand × 2, Cable clips × 4', 'Hinge × 6', 'Cap × 2'])
  const tray = row({ name: 'Battery tray', bed: true, state: 'ready', printer: 'kobra3', printer_name: 'Kobra 3' })
  assert.equal(queueSentence([pair, tray, hinge, row({})]), 'Four waiting. Workshop and Kobra 3 can start now.')
  const tile = withQueue(ordered([P('workshop', 'Workshop', live('ready', [spool(2, 'PETG', GRAY)]))]), [{ ...pair }])[0]
  assert.equal(tile.what, 'Phone stand × 2, Cable clips × 4 · from the queue')
})

test('Change printer on a card moves the whole bed in one go, and one tap puts it back', () => {
  const workshop = PLAN.beds[0]
  const picks = [{ shelf: 'stand', copies: 2 }, { shelf: 'clips', copies: 4 }, { shelf: 'tray', copies: 1 }]
  const opts = bedOptions(workshop, picks, BENCH, {})
  assert.deepEqual(opts.map((o) => [o.title, o.on, o.off]), [['Workshop', true, false], ['Kobra 3 #2', false, false], ['Studio', false, true]])
  const moved = moveBed(picks, workshop, opts[1].patch)
  assert.deepEqual(moved, [{ shelf: 'stand', copies: 2, printer: 'kobra3-2' }, { shelf: 'clips', copies: 4, printer: 'kobra3-2' }, { shelf: 'tray', copies: 1 }])
  const there = bed('kobra3-2', 'Kobra 3 #2', [M('stand', 'Phone stand', 2), M('clips', 'Cable clips', 4)])
  const again = bedOptions(there, moved, BENCH, {})
  assert.deepEqual(again.map((o) => [o.title, o.on]), [['Where the box puts it', false], ['Kobra 3 #2', true], ['Workshop', false], ['Studio', false]])
  assert.deepEqual(moveBed(moved, there, again[0].patch), picks)
})

test('models never printed can go to any printer with something loaded, in what it has (10 October 2026)', () => {
  const asa = bed('desk', 'Desk', [M('t1', 'T1-seat', 1, { first: true }), M('t2', 'T2-seat', 1, { first: true })],
    { material: 'ASA', color: '#1C1C1E', words: 'Black ASA' })
  const picks = [{ shelf: 't1', copies: 1 }, { shelf: 't2', copies: 1 }]
  assert.deepEqual(bedOptions(asa, picks, BENCH, {}).map((o) => [o.title, o.line, o.off]), [
    ['Desk', 'One bed, as the box planned it', false],
    ['Kobra 3 #2', 'Prints in Gray PETG', false],
    ['Workshop', 'Prints in Gray PETG', false],
    ['Studio', "Prints in White PLA, once it's free", false],
  ])
  assert.ok(moveOptions(asa, 't1', picks, BENCH, {}).some((o) => o.title === 'Workshop' && !o.off))
  // a model printed before keeps its filament: the printers without it stay grayed, with why
  const printed = { ...asa, models: asa.models.map((m) => ({ ...m, first: false })) }
  assert.ok(bedOptions(printed, picks, BENCH, {}).filter((o) => o.key !== 'box').every((o) => o.off))
})

test('In on the move sheet: a filament picked for a model rides in the address, and its row says so', () => {
  const picks = [{ shelf: 'cap', copies: 1, printer: 'workshop', in: { material: 'PETG', color: GRAY } }, { shelf: 'vent', copies: 2 }]
  assert.deepEqual(picksFromQuery(picksToQuery(picks)), picks)
  const fils = [{ key: `PETG${GRAY}`, material: 'PETG', color: GRAY, name: 'Gray PETG', on: ['Workshop'] },
                { key: 'mine:p1', material: 'PETG', color: GRAY, name: 'Polymaker PETG', on: [], preset: 'Polymaker PETG', mine: 'p1' }]
  const b = bed('workshop', 'Workshop', [M('cap', 'Cap', 1, { chosen: true })])
  assert.equal(filKeyOf(fils, b), `PETG${GRAY}`)
  assert.equal(filKeyOf(fils, { ...b, filament: 'Polymaker PETG' }), 'mine:p1')
  assert.deepEqual(filOf(fils[1]), { material: 'PETG', color: GRAY, filament: 'Polymaker PETG', filament_name: 'Polymaker PETG' })
  assert.equal(modelLine({ ...PLAN, beds: [b] }, b, b.models[0]), 'Gray PETG, picked here')
})

test('In shows the filament a bed prints in now, picked, even when nothing has it loaded', () => {
  const fils = [{ key: `PETG${GRAY}`, material: 'PETG', color: GRAY, name: 'Gray PETG', on: ['Workshop'] }]
  const asa = bed(null, null, [M('vent', 'Vent', 1)], { material: 'ASA', color: '#1C1C1E', words: 'Black ASA' })
  const c = inChoices(fils, asa)
  assert.deepEqual([c.on, c.fils.map((f) => f.name)], ['now', ['Black ASA', 'Gray PETG']])
  assert.equal(inChoices(fils, bed('workshop', 'Workshop', [M('cap', 'Cap', 1)])).on, `PETG${GRAY}`)
})

test("How it prints on a card: the model page's words for how the box planned the bed, and a change sets every model on it", () => {
  const EDITABLE = [{ key: 'wall_loops', label: 'Walls', kind: 'number' as const, min: 1, max: 10, step: 1, default: '2', help: '' }]
  const words = { editable: EDITABLE, usual: 'normal' as const }
  const b = PLAN.beds[0]
  assert.equal(bedHowLine(b, words), 'Everyday · Normal supports')
  assert.equal(bedHowLine(b), 'Everyday · Usual supports')
  assert.equal(bedHowLine({ ...b, purpose: 'strong', supports: 'tree', brim: 'ears', settings: { wall_loops: '4' } }, words), 'Strong · Tree supports · Corner pads · Walls 4')
  assert.equal(bedHowLine({ ...b, supports: 'off', settings: { wall_loops: '4', layer_height: '0.12' } }, words), 'Everyday · Supports off · 2 settings changed')
  // a brim never splits a bed, so its models can differ: Mixed on the card and the tile, nothing ticked till one is picked
  const mixed = { ...b, brim: 'mixed' as const }
  assert.equal(bedHowLine(mixed, words), 'Everyday · Normal supports · Mixed brims')
  assert.deepEqual(bedHow(mixed), { how: { purpose: 'everyday', supports: null, brim: null, settings: {} }, mixed: true })
  assert.deepEqual(bedTiles(mixed, words).map((t) => [t.label, t.value]),
                   [["It's for", 'Everyday'], ['Supports', 'Normal'], ['Brim', 'Mixed'], ['Changed', 'Nothing']])
  assert.equal(bedTiles(mixed, words)[1].line, "Comes off in blocks · Workshop's usual")
  // each change is the model page's PUT …/how, once for every model on the bed
  assert.deepEqual(bedHowSaves(b, { brim: 'all' }), [{ shelf: 'stand', change: { brim: 'all' } }, { shelf: 'clips', change: { brim: 'all' } }])
  // shown at once on every bed those models are on, while the box plans again
  const shown = withHow(PLAN, ['stand', 'clips'], { purpose: 'strong', settings: { wall_loops: '4' } })
  assert.deepEqual([shown.beds[0].purpose, shown.beds[0].settings, shown.beds[1].purpose], ['strong', { wall_loops: '4' }, 'everyday'])
  assert.equal(withHow({ ...PLAN, beds: [mixed] }, ['stand'], { purpose: 'draft' }).beds[0].brim, 'mixed')
  assert.equal(withHow({ ...PLAN, beds: [mixed] }, ['stand'], { brim: null }).beds[0].brim, null)
})
