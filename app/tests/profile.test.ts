// Pins "Slicing like your prints" (design/getting-started/, C, chosen 5 October 2026; the contract is
// docs/slicer-profile.md). The boards c-slice-found and c-slice-newer are the spec, with the product written as it
// is in this repository; c-slice-pick is phase 2, so only its "none" message is here. The simulator plays the
// printer's side (simulator/slicer_profile.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  LIKE_YOURS, NONE_WORDS, bedWords, checkWords, firstSheet, foundView, inUse, learned, listView, materialsNote,
  newerOffer, printerName, shortProcess, slicingWaits, type FoundProfile, type ProfileInfo,
} from '../src/intent/profile.ts'

const profile = (over: Partial<FoundProfile> = {}): FoundProfile => ({
  id: 'a1b2', printer: 'Voron 2.4 350', process: '0.20mm Standard @Voron', nozzle: 0.4, bed: [350, 350], files: 15,
  slicer: 'OrcaSlicer 2.3', newest: 1_791_000_000,
  materials: { PETG: { preset: 'Generic PETG @Voron', files: 3 }, PLA: { preset: 'Generic PLA @Voron', files: 12 } },
  start: 'PRINT_START', checks: { bed_ok: true, bed_klipper: [350, 350], start_ok: true },
  ...over,
})
// profile_found in the simulator: using, not told, two older settings beside it
const found = (over: Partial<ProfileInfo> = {}): ProfileInfo => ({
  state: 'using', told: false, using: 'a1b2', bed_klipper: [350, 350],
  found: [
    profile(),
    profile({ id: 'c3d4', process: '0.20mm Strength @Voron', files: 1, newest: 1_787_000_000 }),
    profile({ id: 'e5f6', printer: 'Voron 2.4 300', bed: [300, 300], files: 1, newest: 1_780_000_000,
              checks: { bed_ok: false, bed_klipper: [350, 350], start_ok: true } }),
  ],
  ...over,
})

test('c-slice-found: once, before the first model, with what it found in their files', () => {
  const info = found()
  assert.equal(firstSheet(info), 'found')
  const v = foundView(info, inUse(info)!, ['ASA'])
  assert.equal(v.title, 'Slicing like your prints')
  assert.equal(v.sub, 'Found in 15 of your files, made with OrcaSlicer 2.3. Nothing to set up.')
  assert.deepEqual(v.rows.map((r) => [r.label, r.value, r.note ?? null]), [
    ['Printer', 'Voron 2.4 350', '0.4 mm nozzle · 350 × 350 bed, as Klipper says'],
    ['Settings', '0.20mm Standard @Voron', null],
    ['Materials', 'PLA, PETG', "From your files. ASA: Orca's own for this printer."],
    ['Starts with', 'PRINT_START', "Your own macro, as your slicer's files do"],
  ])
  assert.equal(v.rows[0].ok, true, 'the bed agrees with Klipper: a green tick')
  assert.equal(v.button, 'Pick a model')
  assert.equal(v.others, 'Other settings in your files (2)')
})

test('told: Print a model goes straight to the model, as before', () => {
  assert.equal(firstSheet(found({ told: true })), null)
  assert.equal(firstSheet(found({ state: 'yours', using: null, found: [] })), null, "a hand-made printer.json: nothing learned")
  assert.equal(firstSheet(null), null, "a printer whose intent layer doesn't answer: as before")
})

test('materials: what is loaded and not in their files is sliced with Orca\'s own', () => {
  const p = profile()
  assert.equal(materialsNote(p, ['PLA']), "From your files. Others: Orca's own for this printer.")
  assert.equal(materialsNote(p, ['asa', 'TPU', null, 'ASA']), "From your files. ASA, TPU: Orca's own for this printer.")
})

test('only one profile: no other settings to offer', () => {
  const info = found({ found: [profile()] })
  assert.equal(foundView(info, profile(), []).others, null)
})

test('checks that fail are said in words, and drop "Nothing to set up"', () => {
  const p = profile({ bed: [300, 300], checks: { bed_ok: false, bed_klipper: [350, 350], start_ok: false } })
  assert.deepEqual(checkWords(p), [
    'Made for a 300 × 300 bed; Klipper says this one is 350 × 350.',
    "Starts with PRINT_START, which Klipper here doesn't have.",
  ])
  const v = foundView(found({ found: [p] }), p, [])
  assert.equal(v.sub, 'Found in 15 of your files, made with OrcaSlicer 2.3.')
  assert.equal(v.rows[0].note, '0.4 mm nozzle · 300 × 300 bed; Klipper says 350 × 350')
  assert.equal(v.rows[0].problem, true)
  assert.equal(v.rows[3].note, "Klipper here doesn't have it")
  assert.equal(v.rows[3].problem, true)
})

test('the other settings: each with its file count, the one in use ticked, a mismatch said', () => {
  const v = listView(found(), 'Voron')
  assert.equal(v.title, 'Settings in your files')
  assert.equal(v.sub, 'Elyir Bench slices like the one you pick.')
  assert.deepEqual(v.rows.map((r) => [r.title, r.line, r.chosen, r.problem]), [
    ['0.20mm Standard @Voron', 'Voron 2.4 350 · 0.4 mm nozzle · 15 files', true, null],
    ['0.20mm Strength @Voron', 'Voron 2.4 350 · 0.4 mm nozzle · 1 file', false, null],
    ['0.20mm Standard @Voron', 'Voron 2.4 300 · 0.4 mm nozzle · 1 file', false, 'Made for a 300 × 300 bed; Klipper says this one is 350 × 350.'],
  ])
})

test('ask: two nozzles, the list before the first slice, most files first', () => {
  const info: ProfileInfo = {
    state: 'ask', told: false, using: null, bed_klipper: [350, 350],
    found: [
      profile({ id: 'b7c8', printer: 'Voron 2.4 350 0.6 nozzle', process: '0.30mm Standard @Voron 0.6 nozzle', nozzle: 0.6, files: 4 }),
      profile({ files: 9 }),
    ],
  }
  assert.equal(firstSheet(info), 'ask')
  const v = listView(info, 'Voron')
  assert.equal(v.title, 'How do you slice for Voron?')
  assert.equal(v.sub, 'Your files were sliced two ways. Elyir Bench slices like the one you pick.')
  assert.deepEqual(v.rows.map((r) => [r.id, r.title, r.line, r.chosen]), [
    ['a1b2', '0.20mm Standard @Voron', '0.4 mm nozzle · 9 files', false],
    ['b7c8', '0.30mm Standard @Voron 0.6 nozzle', '0.6 mm nozzle · 4 files', false],
  ])
})

test('c-slice-newer: one line on Print, Use them or Keep Standard; never a switch', () => {
  const info: ProfileInfo = {
    state: 'newer', told: true, using: 'a1b2', bed_klipper: [350, 350],
    found: [profile({ newest: 1_790_000_000 }), profile({ id: 'c3d4', process: '0.20mm Strength @Voron', files: 6, newest: 1_791_000_000 })],
  }
  assert.equal(firstSheet(info), null, 'Print a model goes on as before')
  assert.deepEqual(newerOffer(info), {
    id: 'c3d4', text: 'Your newer prints use 0.20mm Strength @Voron.', ask: 'Slice like those from now on?',
    use: 'Use them', keep: 'Keep Standard', problem: null,
  })
  assert.equal(newerOffer({ ...info, state: 'using' }), null, 'kept, or used: no card')
})

test('newer: a different nozzle is said as one', () => {
  const info: ProfileInfo = {
    state: 'newer', told: true, using: 'a1b2', bed_klipper: [350, 350],
    found: [profile({ newest: 1 }), profile({ id: 'b7c8', nozzle: 0.6, newest: 2 })],
  }
  const o = newerOffer(info)!
  assert.equal(o.text, 'Your newer prints use a 0.6 mm nozzle.')
  assert.equal(o.keep, 'Keep 0.4 mm')
})

test('c-slice-pick (phase 2 aside): no files with a profile, Print a model says what to do', () => {
  const info: ProfileInfo = { state: 'none', told: false, using: null, found: [], bed_klipper: [350, 350] }
  assert.equal(slicingWaits(info), true)
  assert.equal(firstSheet(info), null)
  assert.equal(NONE_WORDS, 'Slice one file in OrcaSlicer and print it, and Elyir Bench learns your settings from it.')
  assert.equal(slicingWaits(found()), false)
})

test('Print a model says it slices like their prints once it does', () => {
  assert.equal(learned(found({ told: true })), true)
  assert.equal(learned({ state: 'yours', told: true, using: null, found: [] }), false)
  assert.equal(LIKE_YOURS, 'Sliced like your prints.')
})

test('names and sizes as a person says them', () => {
  assert.equal(printerName('Voron 2.4 350 0.6 nozzle'), 'Voron 2.4 350')
  assert.equal(printerName('Voron 2.4 350'), 'Voron 2.4 350')
  assert.equal(shortProcess('0.20mm Standard @Voron'), 'Standard')
  assert.equal(shortProcess('0.30mm Standard @Voron 0.6 nozzle'), 'Standard')
  assert.equal(shortProcess('My PETG'), 'My PETG')
  assert.equal(bedWords([350.0, 349.6]), '350 × 350')
})

test('American spelling and the product name in every word shown', () => {
  const all = JSON.stringify([foundView(found(), inUse(found())!, ['ASA']), listView(found(), 'Voron'), NONE_WORDS])
  assert.doesNotMatch(all, /colour|recognis|organis|Elyir(?! Bench)/)   // the product is Elyir Bench, never bare Elyir
})
