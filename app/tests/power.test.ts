// Pins turning the printer off (design/power/, A, picked 5 October 2026): the sheet's words and what a phone
// says once the printer is gone. The boards there are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { coolMinutes, goneView, nextMemo, sheetWords, RESTART_GRACE_S, UNREACHABLE_AFTER_S } from '../src/intent/power.ts'

const NOW = new Date('2026-10-05T18:24:00').getTime() / 1000

test('the sheet: hot, it says it cools first; from a phone, where to switch it on', () => {
  const w = sheetWords('off', 'Workshop', 186, 50, false)
  assert.equal(w.title, 'Turn off Workshop?')
  assert.equal(w.body, 'The nozzle is 186°. Workshop lets it cool first, about 3 minutes, so its fan keeps the hot end clear. When its screen goes dark, switch it off.')
  assert.equal(w.note, 'It can only be switched on again at the printer.')
  assert.equal(w.confirm, 'Turn off')
  assert.equal(sheetWords('off', 'Workshop', 186, 50, true).note, null)
})

test('the sheet: cool, it goes at once; restart says it comes back', () => {
  assert.equal(sheetWords('off', 'Workshop', 31, 50, false).body, 'Workshop turns off in a few seconds. When its screen goes dark, switch it off.')
  const r = sheetWords('restart', 'Workshop', 31, 50, false)
  assert.deepEqual([r.title, r.body, r.note, r.confirm], ['Restart Workshop?', "Workshop restarts now, and it's back in about a minute.", null, 'Restart'])
  assert.equal(coolMinutes(60, 50), 1)
  assert.equal(coolMinutes(50, 50), 0)
})

test('gone: off is a state, not an error', () => {
  const g = goneView({ connected: false, name: 'Workshop', memo: { name: 'Workshop', kind: 'off', at: NOW }, lostFor: 2, now: NOW + 600 })
  assert.equal(g?.kind, 'off')
  assert.equal(g?.headline, 'Workshop is off')
  assert.match(g!.detail, /^Turned off at 6:24 pm\. Switch it on at the printer/)
})

test('gone: restarting for a while, then like any other printer that does not answer', () => {
  const memo = { name: 'Workshop', kind: 'restart' as const, at: NOW }
  assert.equal(goneView({ connected: false, name: 'Workshop', memo, lostFor: 30, now: NOW + 30 })?.headline, 'Restarting')
  const late = goneView({ connected: false, name: 'Workshop', memo, lostFor: RESTART_GRACE_S + 5, now: NOW + RESTART_GRACE_S + 5 })
  assert.equal(late?.headline, "Can't reach Workshop")
})

test('gone: a short blip keeps the last state; a long one says it may be switched off', () => {
  assert.equal(goneView({ connected: false, name: 'Workshop', memo: null, lostFor: 3, now: NOW }), null)
  const g = goneView({ connected: false, name: 'Workshop', memo: null, lostFor: UNREACHABLE_AFTER_S, now: NOW })
  assert.equal(g?.detail, 'It may be switched off, or off the Wi-Fi. This page keeps trying.')
  assert.equal(goneView({ connected: false, name: '', memo: null, lostFor: 20, now: NOW })?.headline, "Can't reach the printer")
  assert.equal(goneView({ connected: true, name: 'Workshop', memo: { name: 'Workshop', kind: 'off', at: NOW }, lostFor: 0, now: NOW }), null)
})

test('the memo: kept from the moment it goes, cleared once the printer is back', () => {
  const going = { allowed: true, why: null, cool_to: 50, kind: 'off' as const, going: true }
  const m = nextMemo(null, going, 'Workshop', NOW)
  assert.deepEqual(m, { name: 'Workshop', kind: 'off', at: NOW })
  assert.equal(nextMemo(m, going, 'Workshop', NOW + 2), m)
  assert.equal(nextMemo(m, { allowed: true, why: null, cool_to: 50, kind: null }, 'Workshop', NOW + 60), null)
  assert.equal(nextMemo(null, { ...going, going: false }, 'Workshop', NOW), null)
})
