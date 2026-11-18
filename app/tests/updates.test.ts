// Pins the updates round (design/updates/, A + A): the Updates row's words, its button and the dot on Care.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { updateAsk, updateDot, updateRow, versionWords, type UpdateView } from '../src/intent/update.ts'

const HAVE = '2026.11.07-c255b63'
const NEXT = '2026.11.08-c4a961b'
const newer: UpdateView = { version: HAVE, latest: NEXT, newer: true, state: 'idle' }

test('says a version by its day', () => {
  assert.equal(versionWords(NEXT), 'the 8 November version')
  assert.equal(versionWords('weird'), 'version weird')
  assert.equal(versionWords(null), 'a new version')
})

test('offers Update now while a newer version waits, and puts a dot on Care', () => {
  const r = updateRow(newer, 'Workshop')
  assert.equal(r.line, 'The 8 November version is out. Workshop updates by itself tonight, or now.')
  assert.deepEqual(r.button, { label: 'Update now', disabled: false })
  assert.equal(r.small, `Has ${HAVE}`)
  assert.equal(r.tone, 'new')
  assert.equal(updateDot(newer), true)
})

test('waits for the print', () => {
  const r = updateRow(newer, 'Workshop', { printing: true })
  assert.equal(r.line, 'The 8 November version is out. Workshop updates after this print, at night.')
  assert.deepEqual(r.button, { label: 'After this print', disabled: true })
})

test('has no button away from home', () => {
  assert.equal(updateRow(newer, 'Workshop', { canAsk: false }).button, null)
})

test('shows the download, then the start, without a dot', () => {
  const d: UpdateView = { ...newer, state: 'downloading', done: 9e6, of: 21e6 }
  const r = updateRow(d, 'Workshop')
  assert.equal(r.title, 'Updating')
  assert.equal(r.line, 'Downloading the 8 November version. 9 of 21 MB.')
  assert.ok(Math.abs((r.progress ?? 0) - 9 / 21) < 1e-9)
  assert.equal(updateDot(d), false)
  assert.equal(updateRow({ ...newer, state: 'installing' }, 'Workshop').line,
    'Starting the 8 November version. The screens are back in about a minute.')
})

test('says when it went back', () => {
  const f: UpdateView = { ...newer, state: 'failed', went_back: true }
  const r = updateRow(f, 'Workshop')
  assert.equal(r.title, "It didn't update")
  assert.equal(r.line, "The new version didn't start properly, so Workshop went back to the 7 November version. It tries again tomorrow night.")
  assert.equal(r.button?.label, 'Try again')
  assert.equal(updateDot(f), true)
})

test('is up to date', () => {
  const r = updateRow({ version: NEXT, latest: NEXT, newer: false, state: 'done' }, 'Workshop')
  assert.equal(r.line, 'Up to date: the 8 November version. It updates by itself at night.')
  assert.equal(r.button, null)
  assert.equal(updateRow({ version: NEXT, state: 'idle', why: "Couldn't reach releases.elyir.dev. Is it on the internet?" }, 'Workshop').line,
    "It has the 8 November version. Couldn't reach releases.elyir.dev. Is it on the internet?")
})

test('a Kobra updates with the box, with no button and no dot', () => {
  const k: UpdateView = { version: HAVE, with_box: true }
  const r = updateRow(k, 'Kobra 3')
  assert.equal(r.line, "Kobra 3's screens come from the Bench Box, so they update with it.")
  assert.equal(r.button, null)
  assert.equal(updateDot(k), false)
})

test('the box brings the Kobras with it', () => {
  assert.equal(updateRow(newer, 'The box', { kobras: true }).line,
    "The 8 November version is out. The box updates by itself tonight, and the Kobras' screens with it, or now.")
  assert.equal(updateAsk('the box', true).title, 'Update the box now?')
  assert.equal(updateAsk('Workshop').title, 'Update Workshop now?')
})
