// Pins Set up a filament unit (design/unit-setup/, B, stage 2, picked 22 October 2026): the five step dots, which
// buttons the flow draws where, when the main one can be tapped, the board's versions, the guides card, Care's rows,
// and when the flow takes the screen. Boards b-unit, b-board, b-install and b-phone are the spec; the printer words
// it (printer/unit_setup.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  backAction, barButtons, careSetupRows, dots, guidesCard, pick, primaryReady, setupShown, stepLabel, versionsOf,
  type UnitSetupView,
} from '../src/intent/unitSetup.ts'

const act = (id: string, label: string, primary = false) => ({ id, label, primary, style: 'default' as const })
const GUIDES = [{ name: 'Happy Hare', url: 'https://github.com/moggieuk/Happy-Hare/wiki' }, { name: 'AFC', url: 'https://www.afcproject.dev/' }]

const view = (over: Partial<UnitSetupView> = {}): UnitSetupView => ({
  step: 'unit', n: 1, of: 5, where: 'Set up a filament unit', looking: false, unit: null, board: null, family: null,
  units: [{ id: 'ercf_v2', name: 'ERCF v2', kind: 'happy_hare', line: '6 to 12 slots · Happy Hare' }],
  boards: [], slots: null, found: null, ports: [], mcu: null, guides: GUIDES, program: null,
  headline: 'Which unit is it?', headline_phone: null, detail: null, why: null, progress: null, note: null, next: null,
  actions: [act('unit_setup_close', 'Close'), act('unit_setup_next', 'Next', true)], ...over,
})

const MMB = {
  family: 'mmb', name: 'BTT MMB', line: 'v1.0, v1.1 or v2', probably: true, board: 'mmb_1_0',
  versions: [{ board: 'mmb_1_0', label: 'v1.0' }, { board: 'mmb_1_1', label: 'v1.1' }, { board: 'mmb_2_0', label: 'v2' }],
}
const board = (over: Partial<UnitSetupView> = {}) => view({
  step: 'board', n: 2, unit: 'ercf_v2', family: 'mmb', board: 'mmb_1_1', mcu: '/dev/serial/by-id/x', boards: [MMB],
  slots: { choices: [6, 8, 9, 12], value: 8 }, program: 'Happy Hare 4.1',
  actions: [act('unit_setup_back', 'Back'), act('unit_setup_install', 'Set it up', true)], ...over,
})

test('the flow takes the screen at home, never away, and not on a phone that handed it to the printer', () => {
  assert.equal(setupShown(view(), false, false), true)
  assert.equal(setupShown(view(), true, false), false)
  assert.equal(setupShown(view(), false, true), false)
  assert.equal(setupShown(null, false, false), false)
})

test('five dots: unit, board, installing, then the check and Ready', () => {
  assert.equal(stepLabel(view()), '1 of 5')
  assert.deepEqual(dots(view()), ['n', '', '', '', ''])
  assert.deepEqual(dots(board()), ['d', 'n', '', '', ''])
  assert.deepEqual(dots(view({ step: 'installing', n: 3 })), ['d', 'd', 'n', '', ''])
  assert.equal(stepLabel(view({ step: 'put_back', n: 3 })), 'Done')
})

test('which unit: Close is the back button, Next waits for a unit', () => {
  assert.equal(backAction(view())?.id, 'unit_setup_close')
  assert.deepEqual(barButtons(view()).map((a) => a.label), ['Next'])
  assert.equal(primaryReady(view()), false)
  assert.equal(primaryReady(view({ unit: 'ercf_v2' })), true)
  assert.equal(primaryReady(view({ unit: 'ercf_v2', looking: true })), false)
  assert.deepEqual(pick('unit', 'box_turtle').args, { unit: 'box_turtle' })
})

test('which board: Back and Set it up, ready once a board and its port are known', () => {
  assert.deepEqual(barButtons(board()).map((a) => a.label), ['Back', 'Set it up'])
  assert.equal(backAction(board())?.id, 'unit_setup_back')
  assert.equal(primaryReady(board()), true)
  assert.equal(primaryReady(board({ mcu: null })), false)
  assert.deepEqual(versionsOf(board()).map((v) => v.label), ['v1.0', 'v1.1', 'v2'])
  assert.deepEqual(versionsOf(board({ boards: [{ ...MMB, versions: [] }] })), [])
  assert.deepEqual(pick('slots', 9).args, { slots: 9 })
  assert.deepEqual(pick('port', '/dev/serial/by-id/y').args, { mcu: '/dev/serial/by-id/y' })
})

test('installing has no buttons and no way back; a failure has Close, Put it back and Try again, main one last', () => {
  assert.deepEqual(barButtons(view({ step: 'installing', n: 3, actions: [] })), [])
  assert.equal(backAction(view({ step: 'installing', n: 3, actions: [] })), null)
  const failed = view({ step: 'failed', n: 3, actions: [act('unit_setup_close', 'Close'), act('unit_setup_putback', 'Put it back'), act('unit_setup_retry', 'Try again', true)] })
  assert.deepEqual(barButtons(failed).map((a) => a.label), ['Close', 'Put it back', 'Try again'])
  assert.equal(backAction(failed)?.id, 'unit_setup_close')
})

test("Something else and Another board lead to the projects' own guides", () => {
  assert.deepEqual(guidesCard(view(), 'unit').guides.map((g) => g.name), ['Happy Hare', 'AFC'])
  const c = guidesCard(board(), 'board')
  assert.deepEqual(c.guides.map((g) => g.name), ['Happy Hare'])
  assert.match(c.text, /^Bench sets up ERCF v2 on the boards shown\. For another board, Happy Hare's guide shows how/)
})

test("Care: Set one up when there's no unit, Put it back while a copy is kept", () => {
  const start = act('unit_setup_start', 'Set one up')
  const back = act('unit_setup_putback', 'Put it back')
  assert.deepEqual(careSetupRows(null, null), [])
  const rows = careSetupRows({ action: start, why: null }, { action: back, why: null, line: 'Your settings from before Happy Hare 4.1 was set up.' })
  assert.deepEqual(rows.map((r) => [r.name, r.action.label]), [['Filament unit', 'Set one up'], ['Filament unit · Your old settings', 'Put it back']])
  assert.match(rows[0].line, /^None found\. Bench sets up a Box Turtle, Night Owl, ERCF or Tradrack\.$/)
  assert.equal(careSetupRows({ action: start, why: "Not while it's printing." }, null)[0].line, "Not while it's printing.")
})
