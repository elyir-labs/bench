// Taking a printer out of the Printers app (design/printers-remove/, A, picked 22 October 2026): the picked boards are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canUndo, caseOf, sheetWords, toastWords } from '../src/shell-app/remove.ts'

test('which sheet: answering, out of reach, or already took this phone off', () => {
  assert.equal(caseOf({ reach: 'home', base: 'https://a' }), 'reachable')
  assert.equal(caseOf({ reach: 'away', base: 'https://a' }), 'reachable')
  assert.equal(caseOf({ reach: 'offline', base: null }), 'gone')
  assert.equal(caseOf({ reach: 'checking', base: null }), 'gone')
  assert.equal(caseOf({ reach: 'unpaired', base: null }), 'dropped')
})

test('the sheet as drawn: the switch only when it answers, the truth when it does not', () => {
  const on = sheetWords('Workshop', 'reachable')
  assert.equal(on.title, 'Remove Workshop from this phone?')
  assert.equal(on.body, 'It goes from your list here. Workshop keeps its prints, files and other phones.')
  assert.equal(on.offer, 'Also take this phone off Workshop')
  assert.equal(on.offerSub, 'Workshop forgets this phone. To use it here again, scan its code once more.')
  assert.equal(on.note, null)
  const gone = sheetWords('Kobra 3', 'gone')
  assert.equal(gone.body, 'It goes from your list here.')
  assert.equal(gone.offer, null)
  assert.equal(gone.note, "Kobra 3 can't be reached, so it will still know this phone. To take it off there too, use Care › Phones on its screen.")
  assert.match(sheetWords('Garage', 'dropped').note!, /already took this phone off/)
})

test('undo only while nothing changed on the printer', () => {
  assert.equal(canUndo('reachable', true, false), false)
  assert.equal(canUndo('reachable', false, false), true)
  assert.equal(canUndo('reachable', true, true), true)     // it couldn't forget this phone: still paired, so undo works
  assert.equal(canUndo('gone', false, false), true)
  assert.equal(canUndo('dropped', false, false), false)
})

test('the toast says when the printer may still know this phone', () => {
  assert.equal(toastWords('Workshop', false), 'Workshop is off this phone.')
  assert.match(toastWords('Workshop', true), /Care › Phones/)
})
