// Pins what a person is told when a printer slices on another machine (design/slicing-elsewhere/, A,
// picked 4 October 2026). The painted boards there are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { askingWords, careLine, elsewhere, hostLine, offTitle, readyNote, stateFrom, waitWords } from '../src/slice/elsewhere.ts'

const Workshop = { name: 'Workshop', here: false }
const SELF = { name: 'Workshop', here: true }

test('the printer tells, from /slice/options, whether and how something slices for it', () => {
  assert.deepEqual(stateFrom(200, 'text/html', null), { state: 'none' })              // the app's own page: no slicer
  assert.deepEqual(stateFrom(200, 'application/json', { slicer: Workshop }), { state: 'ready', slicer: Workshop })
  assert.deepEqual(stateFrom(403, 'application/json', { waiting: true, slicer: 'Workshop' }), { state: 'waiting', name: 'Workshop' })
  assert.deepEqual(stateFrom(403, 'application/json', { refused: true, slicer: 'Workshop' }), { state: 'refused', name: 'Workshop' })
  assert.deepEqual(stateFrom(503, 'application/json', { off: true, slicer: 'Workshop' }), { state: 'down', name: 'Workshop' })
  assert.deepEqual(stateFrom(502, 'text/html', null), { state: 'down', name: null })   // the slicer's own nginx page
})

test('the boards: asking, Ready, waiting, off', () => {
  assert.equal(askingWords('Workshop', 'Desk'), "Asking Workshop to slice for Desk, which can't do it itself. Say yes on Workshop's screen.")
  assert.equal(readyNote('Tap a row to change it', Workshop), 'Sliced on Workshop · tap a row to change it')
  assert.equal(readyNote('Tap a row to change it', SELF), 'Tap a row to change it')          // a printer that slices itself: nothing
  assert.equal(readyNote('3 parts, one start', Workshop), 'Sliced on Workshop · 3 parts, one start')
  assert.deepEqual(waitWords({ state: 'queued', ahead: 1, behind: 'Workshop' }, Workshop),
    { title: 'Waiting for Workshop', note: "It's slicing one of its own first." })
  assert.deepEqual(waitWords({ state: 'queued', ahead: 1, behind: 'Studio' }, Workshop), { title: 'Waiting for Workshop', note: "It's slicing one for Studio first." })
  assert.equal(waitWords({ state: 'queued', ahead: 0 }, Workshop), null)                        // first in line: just Slicing…
  assert.equal(waitWords({ state: 'slicing', ahead: 0 }, Workshop), null)
  assert.equal(offTitle({ off: true, slicer: 'Workshop' }), 'Workshop is off.')
  assert.equal(offTitle({ error: 'x' } as any), null)
  assert.equal(elsewhere(null), null)
})

test('Care on both sides says who slices for whom', () => {
  assert.equal(careLine({ state: 'ready', slicer: Workshop }, 'Desk'), 'Workshop slices for Desk. Its own prints come first.')
  assert.equal(careLine({ state: 'ready', slicer: SELF }, 'Workshop'), null)
  assert.equal(careLine({ state: 'waiting', name: 'Workshop' }, 'Desk'), 'Waiting for Workshop to say yes on its screen.')
  assert.equal(careLine({ state: 'refused', name: 'Workshop' }, 'Desk'), 'Workshop said no. Desk asks again tomorrow.')
  assert.equal(careLine({ state: 'none' }, 'Desk'), null)
  assert.equal(hostLine(['Desk'], 'Workshop'), 'Desk sends its models here. Workshop slices them when it has a moment.')
  assert.equal(hostLine(['Desk', 'Studio'], 'Workshop'), 'Desk and Studio send their models here. Workshop slices them when it has a moment.')
  assert.equal(hostLine([], 'Workshop'), null)
})
