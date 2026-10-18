// npm test  (node --experimental-strip-types --test tests/)
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { arcFor, stageOf, stallLine } from '../src/boot/progress.ts'

const mark = JSON.parse(readFileSync(new URL('../src/boot/mark.json', import.meta.url), 'utf8'))

test('stages follow what the app knows, in order', () => {
  assert.equal(stageOf(false, null), 'loaded')
  assert.equal(stageOf(true, null), 'connected')
  assert.equal(stageOf(true, { state: 'preparing', phase: 'starting_up' }), 'starting')
  assert.equal(stageOf(true, { state: 'ready', phase: 'idle' }), 'ready')
  assert.equal(stageOf(true, { state: 'problem', phase: 'mcu' }), 'problem')
  // a print already under way is not "starting up": the boot is over
  assert.equal(stageOf(true, { state: 'printing' }), 'ready')
  assert.equal(stageOf(true, { state: 'preparing', phase: 'heating' }), 'ready')
})

test('the ring picks up exactly where Plymouth left it, and only ever grows', () => {
  const h = mark.handoff
  const order = ['loaded', 'connected', 'starting', 'ready'] as const
  assert.ok(arcFor('loaded', h) > h)
  for (let i = 1; i < order.length; i++) assert.ok(arcFor(order[i], h) > arcFor(order[i - 1], h))
  assert.equal(arcFor('ready', h), 1)
  // a problem holds the ring where starting up had it, rather than jumping
  assert.equal(arcFor('problem', h), arcFor('starting', h))
})

test('a stall names the part in plain words', () => {
  assert.equal(stallLine('loaded', null), 'Starting the printer’s software…')
  assert.equal(stallLine('starting', { state: 'preparing', raw: "mcu 'EBBCan': Unable to connect" }), 'Waking the print head…')
  assert.equal(stallLine('starting', { state: 'preparing', raw: "mcu 'mcu': Unable to connect" }), 'Waking the printer’s brain…')
  assert.equal(stallLine('connected', null), 'Waking the printer’s brain…')
})

test('the eye lands in the Now tab icon it is drawn after (A′: a thin ring that grows to its weight)', () => {
  const shell = readFileSync(new URL('../src/shell/AppShell.vue', import.meta.url), 'utf8')
  const now = shell.match(/label: 'Now', icon: '([^']+)'/)?.[1] ?? ''
  const ring = now.match(/r="([\d.]+)" fill="none" stroke="currentColor" stroke-width="([\d.]+)"/)
  const pupil = now.match(/<circle cx="12" cy="12" r="([\d.]+)" fill="currentColor"/)
  assert.ok(ring && pupil, 'the Now tab icon is a ring and a pupil')
  assert.deepEqual([+ring[1], +ring[2], +pupil[1]], [mark.now_tab.r, mark.now_tab.stroke, mark.now_tab.pupil])
})
