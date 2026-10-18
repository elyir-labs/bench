// Pins the one-spool page chosen on 2 October 2026 (design/one-spool/, B "The spool is the page").
// The boards there are the spec; if one of these fails, the page has drifted from them.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ago, oneSpoolView, tapToSave, undoTarget } from '../src/components/materials/oneSpool.ts'
import { nearestColor } from '../src/components/materials/palette.ts'

const NOW = new Date('2026-10-02T13:08:00')
const spool = (over: Record<string, unknown>) => ({
  slot: 0, direct: true, name: null, color: null, material: null, grams: null, status: 'ready',
  in_use: true, rfid: false, source: 'unknown', since: null, changed: false, was: null, guess_from: null,
  recent: [], ...over,
}) as any

test('a guess asks at the top, with the chips dashed underneath', () => {
  const v = oneSpoolView(spool({ source: 'guess', name: 'Black PETG', color: '#1E1E1E', material: 'PETG',
                                  since: '2026-10-02T09:00:00', guess_from: 'Benchy' }), NOW)
  assert.equal(v.title, 'Probably Black PETG')
  assert.equal(v.pill, 'Guess')
  assert.equal(v.question?.headline, 'Is it Black PETG?')
  assert.equal(v.question?.detail, "That's my guess from your last print, Benchy. If not, tap what it is.")
  assert.deepEqual(v.question?.confirm, { label: "That's right", color: '#1E1E1E', material: 'PETG' })
  assert.equal(v.material, 'PETG')
  assert.equal(v.color, '#1C1C1E')   // the palette's black
  assert.ok(v.maybe)
})

test('new filament asks in amber; "Same as before" comes first, then what was on before', () => {
  const v = oneSpoolView(spool({ changed: true, source: 'told',
    was: { name: 'Black PLA', color: '#1E1E1E', material: 'PLA' },
    recent: [{ name: 'White PLA', color: '#F4F4F2', material: 'PLA' }, { name: 'Orange PETG', color: '#FF8800', material: 'PETG' }] }), NOW)
  assert.equal(v.question?.tone, 'amber')
  assert.equal(v.question?.headline, 'New filament?')
  assert.equal(v.question?.detail, 'It came out and went back in. Was Black PLA.')
  assert.deepEqual(v.question?.answers.map(a => a.label), ['Same as before', 'White PLA', 'Orange PETG'])
  assert.deepEqual(v.question?.answers[0], { label: 'Same as before', color: '#1E1E1E', material: 'PLA' })
  assert.equal(v.material, null)
})

test('told says when, with nothing to answer', () => {
  const v = oneSpoolView(spool({ source: 'told', name: 'Black PETG', color: '#1C1C1E', material: 'PETG', since: '2026-09-29T10:00:00' }), NOW)
  assert.equal(v.title, 'Black PETG')
  assert.equal(v.meta, 'You told me 3 days ago')
  assert.equal(v.question, null)
  assert.equal(v.pill, null)
})

test('unknown, empty and Spoolman', () => {
  assert.equal(oneSpoolView(spool({}), NOW).title, 'Unknown filament')
  const e = oneSpoolView(spool({ status: 'empty', name: 'Black PLA', material: 'PLA', source: 'told' }), NOW)
  assert.equal(e.title, 'Empty')
  assert.equal(e.meta, 'Nothing in the head. Last was Black PLA.')
  const s = oneSpoolView(spool({ source: 'spoolman', name: 'Orange PETG', color: '#FF8800', material: 'PETG', grams: 640 }), NOW)
  assert.equal(s.meta, 'About 640 g left · from Spoolman')
  assert.equal(s.editable, false)
})

test('a material saves at once, keeping the colour; a colour waits for a material', () => {
  const told = oneSpoolView(spool({ source: 'told', name: 'Teal PLA', color: '#10A0A0', material: 'PLA' }), NOW)
  assert.deepEqual(tapToSave(told, { material: 'PETG' }, null).send, { material: 'PETG', color: '#10A0A0' })
  assert.deepEqual(tapToSave(told, { color: '#FF8800' }, null).send, { material: 'PLA', color: '#FF8800' })
  const unknown = oneSpoolView(spool({}), NOW)
  const first = tapToSave(unknown, { color: '#FF8800' }, null)
  assert.deepEqual(first, { send: null, pendingColor: '#FF8800' })
  assert.deepEqual(tapToSave(unknown, { material: 'PETG' }, first.pendingColor).send, { material: 'PETG', color: '#FF8800' })
})

test('undo only puts back something you said', () => {
  assert.deepEqual(undoTarget(spool({ source: 'told', name: 'Black PLA', color: '#1C1C1E', material: 'PLA' })),
                   { label: 'Black PLA', color: '#1C1C1E', material: 'PLA' })
  assert.equal(undoTarget(spool({ source: 'guess', name: 'Black PLA', material: 'PLA' })), null)
  assert.equal(undoTarget(spool({ source: 'told', changed: true })), null)
})

test('ago and the palette', () => {
  assert.equal(ago('2026-10-02T13:07:30', NOW), 'just now')
  assert.equal(ago('2026-10-02T12:38:00', NOW), '30 minutes ago')
  assert.equal(ago('2026-10-02T08:00:00', NOW), '5 hours ago')
  assert.equal(ago('2026-10-01T20:00:00', NOW), 'yesterday')
  assert.equal(nearestColor('#FFFFFF'), '#F4F4F2')
  assert.equal(nearestColor('#5AFF00'), null)   // nothing close: no swatch picked
})
