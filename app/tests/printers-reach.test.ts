import { test } from 'node:test'
import assert from 'node:assert/strict'
import { HOME_LOOK_MS, LOOK_AGAIN_MS, NEVER_UP_MS, awayTitle, foundWords, lookHomeNow, nextStep, notFoundTitle, stillAway } from '../src/shell-app/reach.ts'

const down = { connected: false, everUp: false, sinceStart: 0, gaveUp: false, sinceLook: 0 }

test('a connection that never comes up tries the other name once', () => {
  assert.equal(nextStep({ ...down, sinceStart: NEVER_UP_MS - 1 }), null)
  assert.equal(nextStep({ ...down, sinceStart: NEVER_UP_MS + 1 }), 'other')
  assert.equal(nextStep({ ...down, sinceStart: NEVER_UP_MS + 1, gaveUp: true }), null)
})

test('a connection that was up and dropped stays on its name', () => {
  assert.equal(nextStep({ ...down, everUp: true, sinceStart: 60 * 60_000 }), null)
  assert.equal(nextStep({ ...down, connected: true, sinceStart: 60 * 60_000 }), null)
})

test('down on both names, it looks for the printer again instead of staying put', () => {
  assert.equal(nextStep({ ...down, gaveUp: true, sinceStart: 120_000, sinceLook: LOOK_AGAIN_MS - 1 }), null)
  assert.equal(nextStep({ ...down, gaveUp: true, sinceStart: 120_000, sinceLook: LOOK_AGAIN_MS + 1 }), 'again')
})

test('working through the public name with a home name, it looks at home again now and then', () => {
  const away = { away: true, connected: true, homeKnown: true, homeAvoided: false, sinceHomeLook: HOME_LOOK_MS + 1 }
  assert.equal(lookHomeNow({ ...away, sinceHomeLook: HOME_LOOK_MS - 1 }), false)
  assert.equal(lookHomeNow(away), true)
  assert.equal(lookHomeNow({ ...away, away: false }), false)
  assert.equal(lookHomeNow({ ...away, connected: false }), false)
  assert.equal(lookHomeNow({ ...away, homeKnown: false }), false)
  assert.equal(lookHomeNow({ ...away, homeAvoided: true }), false)
})

test('the look-on-this-Wi-Fi words name one printer and count several', () => {
  assert.equal(awayTitle(['Workshop']), 'Workshop is reached through the internet')
  assert.equal(awayTitle(['Workshop', 'Desk']), 'Your printers are reached through the internet')
  assert.equal(notFoundTitle(['Workshop']), "Couldn't find Workshop on this Wi-Fi")
  assert.equal(notFoundTitle(['Workshop', 'Desk']), "Couldn't find your printers on this Wi-Fi")
  assert.equal(stillAway(['Workshop']), 'Until then Workshop works from away: watch, pause, stop.')
  assert.equal(foundWords(['Workshop']), 'Found Workshop on your Wi-Fi')
  assert.equal(foundWords(['Workshop', 'Desk']), 'Found Workshop and Desk on your Wi-Fi')
  assert.equal(foundWords(['Workshop', 'Desk', 'Studio']), 'Found 3 printers on your Wi-Fi')
})
