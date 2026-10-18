// Pins colour changes on a printer with a unit (design/colour-change/, C as the main path, A as the fallback;
// picked on 3 October 2026). The boards are the spec: CReady and CAsk for the Print sheet, APause,
// APicked, AMissing and APhone for the pause. The words come from the intent layer (printer/tests/
// test_colour_change.py pins those); these pin which words show and what a tap sends.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canPrint, choicesFor, initialPicks, needsSheet, offered, pauseStep, pickLine, planChanges, spoolBefore,
         stagesOf, tileOf, unitsOf } from '../src/intent/colour.ts'

const choice = (slot: number, name: string, material = 'PLA', ask: string | null = null) =>
  ({ slot, name, color: '#FFFFFF', material, line: `Slot ${slot + 1}`, differs: !!ask, ask })
const change = (over: Record<string, unknown> = {}) => ({
  n: 1, layer: 56, color: null, label: 'Layer 56', slot: null, not_loaded: false, named_line: null, missing_line: null,
  pause_line: "I'll pause at layer 56 for you to choose.", ...over,
})
const sheet = (changes: any[]) => ({
  headline: 'Phone stand changes color at layer 56.', detail: '', material: 'PLA',
  start: { slot: 0, name: 'Red PLA', color: '#D9534F', loaded: true, line: 'Slot 1 · in the head' },
  changes,
  choices: [choice(0, 'Red PLA'), choice(1, 'White PLA'), choice(3, 'Blue PLA'),
            choice(4, 'Yellow PETG', 'PETG', 'Yellow PETG on a PLA print may not stick. Use it anyway?')],
  labels: { start: 'To start', pause: 'Pause there and let me choose', print: 'Print', back: 'Back', change: 'Change', yes: 'Use it anyway' },
}) as any

test('a check with colour changes needs the sheet even when everything is loaded', () => {
  assert.equal(needsSheet({ ok: true, filename: 'a', missing: [] }), false)
  assert.equal(needsSheet({ ok: true, filename: 'a', missing: [], colour: sheet([change()]) }), true)
  assert.equal(needsSheet({ ok: false, filename: 'a', missing: [] }), true)
})

test('CReady: the file names white, so white is picked and Print is ready', () => {
  const s = sheet([change({ color: '#F4F4F2', slot: 1, named_line: "Slot 2 · the file's white" })])
  const picks = initialPicks(s)
  assert.deepEqual(picks, [1])
  assert.ok(canPrint(picks))
  assert.equal(pickLine(s, 0, 1), "Slot 2 · the file's white")
  assert.equal(pickLine(s, 0, 3), 'Slot 4')                 // changed to another: just where it is
  assert.deepEqual(planChanges(picks, []), [{ slot: 1 }])
})

test('CAsk: nothing named, so Print waits for a spool; the one in the head is not offered', () => {
  const s = sheet([change()])
  const picks = initialPicks(s)
  assert.deepEqual(picks, [null])
  assert.equal(canPrint(picks), false)
  assert.deepEqual(choicesFor(s, picks, 0).map((c) => c.slot), [1, 3, 4])
  assert.ok(canPrint(['pause']))                            // "Pause there and let me choose" answers it too
  assert.equal(pickLine(s, 0, 'pause'), "I'll pause at layer 56 for you to choose.")
})

test('a colour that is not loaded pauses there unless another spool is picked', () => {
  const s = sheet([change({ color: '#3BA55C', not_loaded: true, missing_line: "There's no green in the unit. I'll pause at layer 56." })])
  assert.deepEqual(initialPicks(s), ['pause'])
  assert.equal(pickLine(s, 0, 'pause'), "There's no green in the unit. I'll pause at layer 56.")
})

test('a later change follows the spool picked before it, and another material carries sure', () => {
  const s = sheet([change(), change({ n: 2, layer: 90, label: 'Layer 90' })])
  assert.equal(spoolBefore(s, [3, null], 1), 3)
  assert.deepEqual(choicesFor(s, [3, null], 1).map((c) => c.slot), [0, 1, 4])
  assert.deepEqual(planChanges([4, 'pause'], [4]), [{ slot: 4, sure: true }, { slot: 'pause' }])
  assert.throws(() => planChanges([null], []))
})

// ---- the pause ----------------------------------------------------------------------------------------

const act = (label: string, slot: number, how: string): any =>
  ({ id: 'colour_choose', label, primary: true, style: 'amber', args: { slot, how } })
const white: any = {
  slot: 1, color: '#F1F1F1', status: 'ready', in_use: false, word: 'White', sub: 'PLA', tone: null, how: 'switch',
  action: act('Switch to White PLA', 1, 'switch'), says: ['The file asks for white:', ' White PLA, slot 2.'],
  says_away: ['White PLA', ", slot 2. I'll switch, clean the nozzle and show you the check here."], link: null, ask: null,
  confirm_away: { text: 'Switch to White PLA from here? Nobody needs to be at the printer; you\'ll check it on the camera.', label: 'Yes, switch' },
  at_printer: false, why: null,
}
const petg: any = { ...white, slot: 4, word: 'Yellow', sub: 'PETG', tone: 'amber', action: act('Switch to Yellow PETG', 4, 'switch'),
  says: ['Yellow PETG', ", slot 5. I'll switch and clean the nozzle."],
  ask: { text: 'Yellow PETG on a PLA print may not stick. Use it anyway?', label: 'Use it anyway' } }
const empty: any = { ...white, slot: 6, status: 'empty', word: 'Empty', sub: 'put one in', how: 'put_in',
  action: act('Put a green spool in slot 7', 6, 'put_in'), says: ['Slot 7 is free.', ' Put a green spool on and push its end in. I\'ll notice.'],
  says_away: null, confirm_away: null, at_printer: true }
const red: any = { ...white, slot: 0, word: 'Red', sub: 'in the head', tone: 'accent', how: 'keep', in_use: true,
  action: act('Carry on with Red PLA', 0, 'keep'), confirm_away: null }
const colour: any = { reason: 'not_planned', n: 1, layer: 56, color: '#F4F4F2', material: 'PLA', asks: 'The file asks for white.',
  picked: 1, units: [{ name: 'Unit 1', slots: [0, 1] }, { name: 'Unit 2', slots: [4, 6] }], slots: [red, white, petg, empty],
  away_note: 'Slot 7 is empty. Putting a spool in needs someone at the printer.' }

test('APause: the picked tile names the amber button, and one tap sends it', () => {
  const s = pauseStep(tileOf(colour, colour.picked), false, 0)
  assert.equal(s.label, 'Switch to White PLA')
  assert.deepEqual(s.says, ['The file asks for white:', ' White PLA, slot 2.'])
  assert.deepEqual(s.send?.args, { slot: 1, how: 'switch' })
  assert.deepEqual(unitsOf(colour).map((u) => [u.name, u.tiles.map((t) => t.slot)]), [['Unit 1', [0, 1]], ['Unit 2', [4, 6]]])
})

test('AMissing: an empty slot asks for a spool at the printer, and away it is not offered', () => {
  assert.equal(pauseStep(empty, false, 0).label, 'Put a green spool in slot 7')
  assert.ok(offered(empty, false))
  assert.equal(offered(empty, true), false)
  assert.equal(pauseStep(empty, true, 0).send, null)
})

test('another material is asked about once, then sent with sure', () => {
  assert.deepEqual(stagesOf(petg, false), ['ask'])
  const first = pauseStep(petg, false, 0)
  assert.equal(first.label, 'Switch to Yellow PETG')
  assert.equal(first.send, null)
  const asked = pauseStep(petg, false, 1)
  assert.deepEqual([asked.label, asked.says, asked.tone], ['Use it anyway', ['Yellow PETG on a PLA print may not stick. Use it anyway?', ''], 'amber'])
  assert.deepEqual(asked.send?.args, { slot: 4, how: 'switch', sure: true })
})

test('APhone: away, a switch says the phone line and is confirmed once more before it is sent', () => {
  const first = pauseStep(white, true, 0)
  assert.deepEqual(first.says, ['White PLA', ", slot 2. I'll switch, clean the nozzle and show you the check here."])
  assert.equal(first.send, null)
  const sure = pauseStep(white, true, 1)
  assert.equal(sure.label, 'Yes, switch')
  assert.deepEqual(sure.send?.args, { slot: 1, how: 'switch', away_ok: true })
  assert.deepEqual(pauseStep(red, true, 0).send?.args, { slot: 0, how: 'keep' })   // carrying on needs no confirmation
})
