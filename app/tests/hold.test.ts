// Pins "ending a print is held, never tapped" (AGENTS.md, 3 October 2026). The engine marks the actions
// (printer/tests/test_intent.py); this pins what the button says and how long it takes.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { HOLD_HINT, HOLD_MS, holdLabel } from '../src/intent/hold.ts'
import { sourceOf } from '../src/intent/source.ts'

test('a held action says so', () => {
  assert.equal(holdLabel('Stop this print'), 'Hold to stop this print')
  assert.equal(holdLabel('Stop now'), 'Hold to stop now')
  assert.equal(HOLD_HINT, 'Keep holding to stop')
})

test("long enough that a brush can't do it, short enough for a real stop", () => {
  assert.ok(HOLD_MS >= 800 && HOLD_MS <= 1500)
})

test('every action says which screen sent it', () => {
  assert.equal(sourceOf({ embedded: false, panel: true, away: false }), 'panel')
  assert.equal(sourceOf({ embedded: false, panel: false, away: false }), 'phone or computer')
  assert.equal(sourceOf({ embedded: false, panel: false, away: true }), 'phone or computer, away')
  assert.equal(sourceOf({ embedded: true, panel: false, away: true }), 'printers app, away')
})
