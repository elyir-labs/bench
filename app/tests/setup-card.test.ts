// Pins "Finish setting up" (design/getting-started/, C "Ready first", chosen 5 October 2026; the contract is
// docs/setup-card.md). The boards c-ready, c-ready-later, c-works, c-include, c-screen-prep, c-screen-cant and
// c-panel-try are the spec, with the product written as it is in this repository; if one of these fails, the card
// has drifted from them. The simulator plays the printer's side (simulator/setup_card.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  ADD_MACRO, GROUP_LABELS, PRODUCT, TRIAL_ASK, WORKS_SUB, cardRows, cardShown, countdown, featureGroups, includeWords,
  leftCount, leftWords, macroParts, nameLine, notifyRow, screenRow, secondsLeft, settling, slicerCopy, trialWords, worksLine,
  type SetupInfo,
} from '../src/intent/setup.ts'

// What setup_new answers on a stranger's printer: the screen offered, include off (docs/setup-card.md)
const info = (over: Partial<SetupInfo> = {}, works: Partial<SetupInfo['works']> = {}): SetupInfo => ({
  name: 'Voron', name_from: 'mainsail',
  rows: [{ id: 'notify' }, { id: 'screen', state: 'offer' }, { id: 'works', now: 3, with_macro: 3 }],
  dismissed: [],
  works: {
    board: { board: 'Raspberry Pi 4, 2 GB, Debian 12', differences: [] },
    features: [
      { id: 'core', group: 'now', label: 'Ready, printing, history, Care' },
      { id: 'runout', group: 'now', label: 'Filament runs out', note: 'Your runout sensor' },
      { id: 'camera', group: 'now', label: 'Camera' },
      { id: 'steps', group: 'with_macro', label: 'The steps while it gets ready', note: 'Rough today, from your messages' },
      { id: 'cancel', group: 'with_macro', label: 'Cancel while it warms up' },
      { id: 'squish', group: 'with_macro', label: 'Squish the first layer more or less' },
      { id: 'unit', group: 'not_here', label: 'Filament unit slots', note: 'No ACE Pro found' },
    ],
    include: 'off', include_why: null, include_text: '[include elyir-bench.cfg]',
    slicer_lines: { before: 'ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer]', after: 'ELYIR_BENCH_PRINT_START_DONE' },
    ...works,
  },
  ...over,
})
const words = (rows: ReturnType<typeof cardRows>) => rows.map((r) => [r.title, r.line, r.button?.label ?? null, r.done])

test('c-ready: three rows in order, notifications, the screen, what works, with three left', () => {
  const rows = cardRows(info(), 'off')
  assert.deepEqual(words(rows), [
    ['Hear when a print needs you', 'On this phone', 'Turn on', false],
    ["Use it on Voron's screen", 'KlipperScreen comes back with a tap', 'Try it', false],
    ['What works on Voron', 'Most of it, and 3 more with one line', null, false],
  ])
  assert.deepEqual(rows.map((r) => r.icon), ['bell', 'screen', 'list'])
  assert.equal(rows[0].button?.primary, true, 'Turn on is the accent button')
  assert.equal(rows[1].button?.primary, false)
  assert.equal(rows[2].opens, 'works', 'the works row opens the sheet')
  assert.equal(leftWords(leftCount(rows)), '3 left')
  assert.equal(nameLine('Voron', 'mainsail'), 'Called Voron, from Mainsail')
  assert.equal(cardShown(true, rows), true)
})

test('c-ready-later: done rows tick off, and the card leaves when none are left', () => {
  const later = cardRows(info({ rows: [{ id: 'notify' }, { id: 'screen', state: 'done' }, { id: 'works', now: 3, with_macro: 3 }] }), 'on')
  assert.deepEqual(words(later).slice(0, 2), [
    ['Notifications on', 'This phone', null, true],
    ["Voron's screen runs Elyir Bench", 'Care › Printer screen to change', null, true],
  ])
  assert.deepEqual(later.map((r) => r.icon), ['check', 'check', 'list'])
  assert.equal(leftWords(leftCount(later)), '1 left')
  assert.equal(cardShown(true, later), true)
  const allDone = cardRows(info({ rows: [{ id: 'notify' }, { id: 'screen', state: 'done' }, { id: 'works', now: 6, with_macro: 0 }] }, { include: 'on' }), 'on')
  assert.equal(leftCount(allDone), 0)
  assert.equal(cardShown(true, allDone), false, 'nothing left: the card is gone')
  assert.equal(cardShown(false, cardRows(info(), 'off')), false, 'the printer closed it')
})

test('rows closed with × stay hidden, and a row the printer leaves out (no screen) is not drawn', () => {
  assert.deepEqual(cardRows(info({ dismissed: ['notify', 'screen'] }), 'off').map((r) => r.id), ['works'])
  assert.deepEqual(cardRows(info({ rows: [{ id: 'notify' }, { id: 'works', now: 3, with_macro: 3 }] }), 'off').map((r) => r.id), ['notify', 'works'])
})

test('the notifications row waits for this phone, is done when it has push, and says why when it cannot', () => {
  assert.deepEqual(cardRows(info(), null).map((r) => r.id), ['screen', 'works'], 'still asking: no row yet')
  assert.equal(notifyRow('on').done, true)
  for (const s of ['needs-install', 'insecure', 'no-door', 'blocked', 'unsupported'] as const) {
    const r = notifyRow(s)
    assert.equal(r.done, false)
    assert.equal(r.button, undefined, `${s}: no Turn on that can't work`)
    assert.ok(r.line.length > 10, `${s}: says why`)
  }
  assert.match(notifyRow('needs-install').line, /Add to Home Screen/)
})

test('the screen row in each state (c-screen-prep, c-screen-cant, the contract)', () => {
  const why = 'Debian 11 no longer offers the Chromium it needs. Nothing changed.'
  assert.deepEqual(
    (['offer', 'fetching', 'trial', 'done', 'kept_klipperscreen', 'cant'] as const).map((s) => {
      const r = screenRow(s, 'Voron', why)
      return [s, r.title, r.line, r.button?.label ?? null, r.done]
    }),
    [
      ['offer', "Use it on Voron's screen", 'KlipperScreen comes back with a tap', 'Try it', false],
      ['fetching', "Getting Voron's screen ready", 'Fetching what it needs. KlipperScreen stays on until then.', null, false],
      ['trial', "Trying it on Voron's screen", "Keep or go back on the printer's screen", null, false],
      ['done', "Voron's screen runs Elyir Bench", 'Care › Printer screen to change', null, true],
      ['kept_klipperscreen', "Voron's screen stays on KlipperScreen", '', 'Try again', true],
      ['cant', "Voron's screen stays on KlipperScreen", why, 'OK', false],
    ],
  )
  assert.equal(screenRow('fetching', 'Voron').progress, true, 'a bar, with no percentage')
  assert.equal(screenRow('cant', 'Voron', why).amber, true)
  assert.equal(screenRow('cant', 'Voron', why).button?.press, 'screen_ok', 'OK dismisses the row')
})

test('the works row follows the include', () => {
  assert.equal(worksLine(3, 'off'), 'Most of it, and 3 more with one line')
  assert.equal(worksLine(4, 'failed'), "The start macro didn't go in")
  assert.match(worksLine(3, 'adding'), /^Adding Elyir Bench's start macro/)
  const on = cardRows(info({}, { include: 'on' }), 'off').find((r) => r.id === 'works')!
  assert.equal(on.done, true, 'with the include on, nothing more is offered')
})

test('c-works: three groups in order, empty ones left out, and the button under the start macro group', () => {
  assert.equal(WORKS_SUB, 'Found by looking at the printer. Nothing here was changed.')
  const g = featureGroups(info().works.features)
  assert.deepEqual(g.map((x) => [x.label, x.items.map((f) => f.label)]), [
    ['Works now', ['Ready, printing, history, Care', 'Filament runs out', 'Camera']],
    ["With Elyir Bench's start macro", ['The steps while it gets ready', 'Cancel while it warms up', 'Squish the first layer more or less']],
    ['Not on this printer', ['Filament unit slots']],
  ])
  assert.equal(ADD_MACRO, "Add Elyir Bench's start macro…")
  assert.equal(GROUP_LABELS.with_macro, `With ${PRODUCT}'s start macro`)
  const on = featureGroups(info().works.features.map((f) => (f.group === 'with_macro' ? { ...f, group: 'now' as const } : f)))
  assert.deepEqual(on.map((x) => x.group), ['now', 'not_here'], 'once on, the start macro group is empty and not drawn')
})

test('c-include: the one line, the two slicer lines around theirs, and the remove state', () => {
  const w = info().works
  assert.equal(w.include_text, '[include elyir-bench.cfg]')
  assert.deepEqual(macroParts(w.slicer_lines.before), ['ELYIR_BENCH_PRINT_START', ' BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer]'])
  assert.deepEqual(macroParts(w.slicer_lines.after), ['ELYIR_BENCH_PRINT_START_DONE', ''])
  assert.equal(slicerCopy(w.slicer_lines).split('\n').length, 3)
  assert.match(slicerCopy(w.slicer_lines).split('\n')[1], /^; /, 'the middle line is a G-code comment, harmless if left in')
  assert.deepEqual(includeWords('off'), { title: 'Add one line to printer.cfg', button: 'Add and restart Klipper', busy: null, removing: false })
  assert.equal(includeWords('adding').busy !== null, true)
  assert.equal(includeWords('on').removing, true)
  assert.equal(includeWords('on').button, 'Remove and restart Klipper')
  assert.equal(includeWords('failed').button, 'Add and restart Klipper', 'failed: try again')
})

test('c-panel-try: the trial bar counts down from what the printer last said', () => {
  assert.equal(TRIAL_ASK, 'Keep Elyir Bench here?')
  assert.equal(trialWords(108), 'Going back in 1:48')
  assert.equal(countdown(120), '2:00')
  assert.equal(countdown(9.2), '0:10', 'rounds up: it never says 0:00 while time is left')
  assert.equal(countdown(-3), '0:00')
  assert.equal(secondsLeft(108, 1_000, 3_500), 105.5)
  assert.equal(secondsLeft(2, 0, 10_000), 0)
})

test('the card asks again by itself while the printer is moving on', () => {
  assert.equal(settling(info()), false)
  assert.equal(settling(info({ rows: [{ id: 'screen', state: 'fetching' }] })), true)
  assert.equal(settling(info({ rows: [{ id: 'screen', state: 'trial' }] })), true)
  assert.equal(settling(info({}, { include: 'adding' })), true)
  assert.equal(nameLine('voron', 'hostname'), 'Called voron, from its network name')
  assert.equal(nameLine('Big Voron', 'you'), 'Called Big Voron')
})

test('on the plain home address, the notifications row says where the secure link is', () => {
  const base = { name: 'Desk', name_from: 'hostname', dismissed: [], rows: [{ id: 'notify' }],
                 works: { features: [], include: 'off', include_text: '', slicer_lines: { before: '', after: '' } } } as unknown as SetupInfo
  const row = (link?: 'off' | 'waiting' | 'on') => cardRows({ ...base, secure_link: link }, 'insecure')[0]
  assert.equal(row('waiting').line, "They come once Elyir approves Desk's secure link, usually within a day.")
  assert.equal(row('waiting').button, undefined)
  assert.deepEqual(row('on').button, { label: 'Set up', press: 'pair_here', primary: true })
  assert.equal(row('off').line, "They need the printer's secure link, which isn't set up yet.")
  assert.equal(row(undefined).line, "They need the printer's secure link, which isn't set up yet.")
})
