// Pins the demo's try page, picked on 22 October 2026 (design/try-page/, B): the moments sit right under the two
// screens in four groups, each one a real simulator scenario with a line on what to watch for, and the playing line
// has words for every phase the simulator reports and for everything a scenario waits on.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../demo/showcase.html', import.meta.url), 'utf8')
const scenarios = readFileSync(new URL('../../simulator/scenarios.py', import.meta.url), 'utf8')
const sim = readFileSync(new URL('../../simulator/sim.py', import.meta.url), 'utf8')
const known = new Set([...scenarios.slice(scenarios.indexOf('SCENARIOS = {')).matchAll(/^\s+"(\w+)":/gm)].map((m) => m[1]))

test('the remote is right under the screens, not in a column beside them', () => {
  const stage = page.slice(page.indexOf('<section class="stage">'), page.indexOf('<section class="facts">'))
  assert.ok(stage.indexOf('class="screens"') < stage.indexOf('class="remote"'))
  assert.ok(!stage.includes('<aside'))
})

test('eleven moments in four groups, each a real scenario that says what to watch for', () => {
  const groups = [...page.matchAll(/<div class="group"><small>([^<]+)<\/small>([\s\S]*?)<\/div>/g)]
  assert.deepEqual(groups.map((g) => g[1]), ['Printing', 'Filament', 'When it goes wrong', 'All of it'])
  const moments = groups.flatMap((g) => [...g[2].matchAll(/<button class="moment" data-s="(\w+)"[^>]* title="([^"]+)" data-look="([^"]+)">/g)])
  assert.equal(moments.length, 11)
  for (const [, s] of moments) assert.ok(known.has(s), `${s} is not a simulator scenario`)
})

test('the playing line has words for every phase and every wait', () => {
  for (const phase of ['playing', 'waiting', 'done']) {
    assert.ok(sim.includes(`"${phase}"`), `sim.py no longer reports ${phase}`)
    assert.match(page, new RegExp(`${phase}: '[^']+'`))
  }
  const waits = new Set([...scenarios.matchAll(/wait_for\("(\w+)"\)/g)].map((m) => m[1]))
  const yourTurn = page.slice(page.indexOf('const YOUR_TURN'), page.indexOf('const PHASE'))
  for (const w of waits) assert.match(yourTurn, new RegExp(`\\b${w}: '`), `nothing to say while a scenario waits for ${w}`)
})
