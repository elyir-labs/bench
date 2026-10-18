// Pins Tell Elyir something (design/report/, B, picked 18 October 2026): what goes with a report, the moment a
// problem screen hands over, and the address the panel's code opens. The boards there are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { contextOf, goesWith, KINDS, momentLine, writeUrl } from '../src/report/words.ts'

test('three kinds, and only something wrong takes the printer\'s report', () => {
  assert.deepEqual(KINDS.map((k) => k.kind), ['wrong', 'idea', 'other'])
  assert.match(KINDS[0].line, /logs and settings go with it/)
  assert.match(KINDS[1].line, /Nothing from the printer unless you add it/)
})

test('a report from a problem carries the minutes before it; from Care it doesn\'t', () => {
  const problem = { state: 'problem', headline: "The nozzle or bed isn't heating properly.", detail: 'I stopped the print.',
    job: { name: 'Phone stand', progress: 0.4 } } as any
  const c = contextOf(problem, new Date('2026-10-18T11:14:00'))!
  assert.equal(c.headline, "The nozzle or bed isn't heating properly.")
  assert.equal(momentLine(c), '11:14 am, 40% into Phone stand')
  assert.equal(goesWith(c)[0].title, 'The minutes before it stopped')
  assert.equal(goesWith(null).length, 3)
  assert.equal(contextOf({ state: 'ready', headline: 'Ready' } as any), null)
  assert.match(goesWith(null).at(-1)!.line, /without passwords, keys or the Wi-Fi's details/)
})

test('the panel\'s code opens the public form with the printer named', () => {
  assert.equal(writeUrl('idea', { name: 'Workshop', release: '2026.10.18-abc', board: 'Raspberry Pi 5' }),
    'https://bench.elyir.com/write#kind=idea&printer=Workshop&release=2026.10.18-abc&board=Raspberry+Pi+5')
  assert.equal(writeUrl('other', {}), 'https://bench.elyir.com/write#kind=other')
})
