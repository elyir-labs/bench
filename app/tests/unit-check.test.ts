// Pins Check and measure (design/unit-setup/, B, stage 1, picked 22 October 2026): the step dots, which buttons the
// flow draws where, each slot card's lines, the progress while measuring, and Care's Filament unit row. The boards
// b-test, a-measure and b-ready are the spec; the printer words it (printer/unit_check.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  backAction, barButtons, cardLines, careRows, dots, flowShown, gearButtons, gearChecklist, padNumber, padPress,
  progress, rangeAt, stepLabel,
  type GearView, type UnitCheckView,
} from '../src/intent/unitCheck.ts'

const act = (id: string, label: string, primary = false) => ({ id, label, primary, style: 'default' as const })
const STOP = act('unit_check_stop', 'Stop')

const view = (over: Partial<UnitCheckView> = {}): UnitCheckView => ({
  unit: 'ERCF 1', unit_index: 0, driver: 'happy_hare', step: 'slots', n: 1, of: 3,
  headline: 'Push filament into slot 3.', detail: "Slot 2's sensor saw the filament, and its motor turned.", tone: 'ok',
  slots: [], current: 2, note: '2 of 8 checked. Then Bench measures the tube to the head.', measure: null, ready: null,
  stopping: false, actions: [act('unit_check_skip', 'Skip slot 3'), STOP], raw: '', ...over,
})

test('the flow takes the screen while a check is going, never away from home', () => {
  assert.equal(flowShown(view(), false), true)
  assert.equal(flowShown(view(), true), false)
  assert.equal(flowShown(null, false), false)
})

test('one dot per step: checking, measuring, ready', () => {
  assert.equal(stepLabel(view()), '1 of 3')
  assert.deepEqual(dots(view()), ['n', '', ''])
  assert.deepEqual(dots(view({ step: 'measure', n: 2 })), ['d', 'n', ''])
  assert.equal(stepLabel(view({ step: 'ready', n: 3 })), 'Done')
  assert.deepEqual(dots(view({ step: 'ready', n: 3 })), ['d', 'd', 'd'])
})

test('checking slots: Skip at the bottom right, Stop is the back button', () => {
  assert.deepEqual(barButtons(view()).map((a) => a.label), ['Skip slot 3'])
  assert.equal(backAction(view())?.id, 'unit_check_stop')
  // a gate with no sensor: It's in is the main button, last
  const noSensor = view({ actions: [act('unit_check_in', "It's in", true), act('unit_check_skip', 'Skip slot 3'), STOP] })
  assert.deepEqual(barButtons(noSensor).map((a) => a.label), ['Skip slot 3', "It's in"])
  const failed = view({ tone: 'failed', actions: [act('unit_check_retry', 'Try again', true), act('unit_check_skip', 'Skip slot 5'), STOP] })
  assert.deepEqual(barButtons(failed).map((a) => a.label), ['Skip slot 5', 'Try again'])
  assert.equal(backAction(view({ stopping: true, actions: [] })), null)
})

test('measuring: Stop is drawn at the bottom too (board a-measure)', () => {
  assert.deepEqual(barButtons(view({ step: 'measure', n: 2, actions: [STOP] })).map((a) => a.label), ['Stop'])
  const cant = view({ step: 'measure', n: 2, tone: 'failed', actions: [act('unit_check_skip', 'Skip it', true), STOP] })
  assert.deepEqual(barButtons(cant).map((a) => a.label), ['Skip it'])
})

test('Ready: Done, then Load spools; back is Done', () => {
  const ready = view({ step: 'ready', n: 3, actions: [act('unit_check_done', 'Done'), { ...act('unit_check_done', 'Load spools', true), args: { then: 'materials' } }] })
  assert.deepEqual(barButtons(ready).map((a) => a.label), ['Done', 'Load spools'])
  assert.equal(backAction(ready)?.label, 'Done')
})

test('each slot card says what it found', () => {
  const card = (state: any, extra = {}) => ({ slot: 0, label: 'Slot 1', state, sensor: null, motor: null, line: null, ...extra })
  assert.deepEqual(cardLines(card('ok', { sensor: true, motor: true })), [{ mark: 'y', text: 'Sensor' }, { mark: 'y', text: 'Motor' }])
  assert.deepEqual(cardLines(card('waiting', { line: 'Waiting…' })), [{ mark: 'spin', text: 'Waiting…' }])
  assert.deepEqual(cardLines(card('next', { line: 'Next' })), [{ mark: null, text: 'Next' }])
  assert.deepEqual(cardLines(card('failed', { sensor: true, line: "Didn't pass" })), [{ mark: 'y', text: 'Sensor' }, { mark: 'q', text: "Didn't pass" }])
})

test('the progress bar counts toward the estimate and never claims done', () => {
  const m = { what: 'tube' as const, slot: 0, seconds: 40, elapsed: null, n: 1, of: 1, note: '' }
  assert.deepEqual(progress(m), { pct: 0, words: 'About 40 seconds' })
  assert.deepEqual(progress({ ...m, elapsed: 18 }), { pct: 0.45, words: 'About 25 seconds' })
  assert.equal(progress({ ...m, elapsed: 18 }, 4).words, 'About 20 seconds')
  assert.deepEqual(progress({ ...m, elapsed: 90 }), { pct: 0.95, words: 'Almost done' })
})

test("Care's Filament unit row: only units Bench can check, with why not", () => {
  const start = act('unit_check_start', 'Check and measure')
  const rows = careRows([{ name: 'ACE 1', check: null }, { name: 'ERCF 1', check: { action: start, why: null } },
    { name: 'Turtle 1', check: { action: start, why: 'Not while it\'s printing.' } }])
  assert.deepEqual(rows.map((r) => [r.name, r.why]), [['ERCF 1', null], ['Turtle 1', "Not while it's printing."]])
  assert.equal(rows[0].line, 'Check each slot, and measure the tube to the head. A few minutes at the printer.')
  assert.equal(rows[1].line, "Not while it's printing.")
  assert.deepEqual(careRows(undefined), [])
})

// ---- measuring Happy Hare's gear (design/unit-setup/, "Gear calibration", C with B's mark) ----------------------

const gear = (over: Partial<GearView> = {}): GearView => ({
  step: 'pad', kind: 'per_slot', slots_n: 8, plan: [], side: null, art: 'outlet', pushed: 120, push: 100, tries: 1,
  mm: null, range: [90, 110], near: [80, 120], sheet: null, rows: null, cards: null, progress: null, busy: false, ...over,
})

test('Care: Measure the gear again sits under Check and measure, Happy Hare only', () => {
  const start = act('unit_check_start', 'Check and measure')
  const g = { ...act('unit_check_start', 'Measure the gear again'), args: { unit: 0, gear: 1 } }
  const rows = careRows([{ name: 'ERCF 1', check: { action: start, why: null }, gear: { action: g, why: null } },
    { name: 'Turtle 1', check: { action: start, why: null }, gear: null }])
  assert.deepEqual(rows.map((r) => [r.key, r.gear, r.action.label]), [
    ['ERCF 1', false, 'Check and measure'], ['ERCF 1 gear', true, 'Measure the gear again'],
    ['Turtle 1', false, 'Check and measure']])
  assert.equal(rows[1].line, 'Slot 1 with a ruler, then the unit measures the rest. A few minutes at the printer.')
})

test('the number pad: digits, one point, one decimal, delete', () => {
  let v = ''
  for (const k of ['9', '8', '.', '5', '7']) v = padPress(v, k)
  assert.equal(v, '98.5')
  assert.equal(padPress('98.5', '.'), '98.5')
  assert.equal(padPress('', '.'), '0.')
  assert.equal(padPress('0', '7'), '7')
  assert.equal(padPress('114', '2'), '114')
  assert.equal(padPress('98.5', '⌫'), '98.')
  assert.equal(padNumber('98.5'), 98.5)
  assert.equal(padNumber('98.'), null)
  assert.equal(padNumber(''), null)
  assert.equal(padNumber('0'), null)
})

test("the pad's buttons: That's it carries the number and waits for one; Stop is the back button", () => {
  const uc = view({ step: 'gear', n: 2, of: 4, detail: null, tone: null, gear: gear(),
    actions: [act('unit_check_gear_again', 'Measure again'), act('unit_check_gear_measured', "That's it", true), STOP] })
  const empty = gearButtons(uc, '')
  assert.deepEqual(empty.map((b) => [b.action.label, b.disabled]), [['Measure again', false], ["That's it", true]])
  const typed = gearButtons(uc, '98.5')
  assert.deepEqual(typed[1].action.args, { mm: 98.5 })
  assert.equal(typed[1].disabled, false)
  assert.equal(gearButtons({ ...uc, gear: gear({ busy: true }) }, '98.5')[1].disabled, true)
  assert.equal(backAction(uc)?.id, 'unit_check_stop')
  assert.equal(stepLabel(uc), '2 of 4')
  assert.deepEqual(dots(uc), ['d', 'n', '', ''])
})

test('while the encoder measures, Stop is drawn at the bottom (board gc-encoder)', () => {
  const uc = view({ step: 'gear', n: 2, of: 4, gear: gear({ step: 'gates', busy: true }), actions: [STOP] })
  assert.deepEqual(gearButtons(uc, '').map((b) => [b.action.label, b.disabled]), [['Stop', false]])
  const failed = { ...uc, tone: 'failed' as const, actions: [act('unit_check_retry', 'Try again', true), act('unit_check_skip', 'Skip it'), STOP] }
  assert.deepEqual(gearButtons(failed, '').map((b) => b.action.label), ['Skip it', 'Try again'])
})

test('the plan: No ruler? Skip it, then Start', () => {
  const uc = view({ step: 'gear', n: 2, of: 4, gear: gear({ step: 'plan' }),
    actions: [act('unit_check_gear_skip', 'No ruler? Skip it'), act('unit_check_gear_start', 'Start', true), STOP] })
  assert.deepEqual(gearButtons(uc, '').map((b) => b.action.label), ['No ruler? Skip it', 'Start'])
})

test('tube off, then the mark (board gb-mark)', () => {
  assert.deepEqual(gearChecklist(gear({ step: 'free', pushed: 0 })).map((c) => c.state), ['n', ''])
  assert.deepEqual(gearChecklist(gear({ step: 'free', pushed: 0, busy: true })).map((c) => c.state), ['d', ''])
  const mark = gearChecklist(gear({ step: 'mark', pushed: 20 }))
  assert.deepEqual(mark.map((c) => c.state), ['d', 'n'])
  assert.equal(mark[1].sub, 'Bench pushed a little out. Any marker that shows on it.')
})

test('the range bar and the encoder runs in minutes', () => {
  assert.equal(rangeAt(gear(), 100), 0.5)
  assert.equal(rangeAt(gear(), 140), 1)
  assert.equal(rangeAt(gear(), null), null)
  assert.equal(progress({ seconds: 245, elapsed: 100 }).words, 'About 2 minutes left')
  assert.equal(progress({ seconds: 245, elapsed: null }).words, 'About 4 minutes')
  assert.equal(progress({ seconds: 245, elapsed: 200 }).words, 'About 45 seconds')
})
