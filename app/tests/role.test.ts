// Pins printer or Bench Box on a fresh card's first screen, picked on 5 October 2026 (design/role/, B: it follows
// what's plugged in). The boards there are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { EMPTY, boxFailed, boxGone, boxSteps, headerFor, pollMs, screenFor, shown, type BringInfo } from '../src/intent/bring.ts'

const info = (o: Partial<BringInfo> = {}): BringInfo => ({ ...EMPTY, role: null, ...o })

test('a board found: the three ways, as a new printer', () => {
  assert.equal(screenFor(info({ boards: 2 }), { at: 'start' }, false), 'start')
  assert.deepEqual(headerFor('start'), { who: 'New printer', steps: ['Wi-Fi', 'Printer'] })
})

test("nothing plugged in: the box leads; It's a printer goes on to the three ways", () => {
  assert.equal(screenFor(info({ boards: 0 }), { at: 'start' }, false), 'none')
  assert.deepEqual(headerFor('none'), { who: 'New', steps: ['Wi-Fi', 'Printer or box'] })
  assert.equal(screenFor(info({ boards: 0 }), { at: 'printer' }, false), 'start')
})

test("not looked yet, or a printer side that can't: today's screen", () => {
  assert.equal(screenFor(info({ boards: null }), { at: 'start' }, false), 'start')
  assert.equal(screenFor({ ...EMPTY, boards: 0 }, { at: 'start' }, false), 'start')   // no `role` at all
})

test('becoming a Bench Box takes the screen, and keeps it shown and followed', () => {
  const i = info({ boards: 0, role: { state: 'switching', progress: { step: 'Its screen', done: 1, of: 3 }, why: null, url: 'http://bench-box.local:8088/' } })
  assert.equal(screenFor(i, { at: 'sources' }, false), 'box')
  assert.deepEqual(headerFor('box'), { who: 'New Bench Box', steps: ['Wi-Fi', 'Bench Box'] })
  assert.equal(shown({ state: 'ready', info: i, requested: false, seen: true }), true)
  assert.equal(pollMs(i, true), 1000)
  assert.deepEqual(boxSteps(i.role!.progress).map(s => s.status), ['ok', 'now', 'todo'])
  assert.deepEqual(boxSteps(null).map(s => s.label), ['The Bench app', 'Its screen', 'Klipper and Moonraker off'])
})

test('once Moonraker is off, the phone is told where the box is; a failure says why', () => {
  assert.equal(boxGone('http://bench-box.local:8088/'), 'Its screen is switching to the Bench app. On this phone, open http://bench-box.local:8088/ in a minute.')
  assert.match(boxGone(null), /same address/)
  assert.deepEqual(boxFailed('The Bench app needs nginx.'), { title: "It didn't become a Bench Box.", line: 'The Bench app needs nginx.' })
})
