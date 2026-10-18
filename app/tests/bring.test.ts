// Bring it over (design/printer-setup/, A, agreed 5 October 2026; docs/bring-it-over.md): which screen when, and
// the words, as the boards a-start, a-bring, a-bring-what and a-done draw them.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  planNotes, EMPTY, screenFor, shown, resultKey, pollMs, stepOf, STEPS, startSub, ways, foundPill, sourceRows, dayWords, agoWords,
  addressProblem, isBackup, backupUpload, planTitle, comesOver, gcodesOffer, sizeWords, chipWords, boardLine,
  progressWords, resultWords, failedWords, bringFromWifi, bringingNote, START_TITLE, SOURCES_TITLE, BOARDS_TITLE, APPLY,
  type BringInfo, type BringPlan, type BringSource, type Here,} from '../src/intent/bring.ts'

const NOW = new Date(2026, 9, 5, 14, 0).getTime()                 // 5 Oct 2026, 2 pm local
const at = (d: Date) => d.getTime() / 1000
const CARD: BringSource = { id: 'card-sda2', kind: 'card', name: 'Voron', detail: 'In a USB reader', when: at(new Date(2026, 9, 3, 21, 14)),
  files: 19, gcodes: 46, history: 212, boards: ['stm32f446xx', 'can 6cc850bbec73'] }
const STUDIO: BringSource = { id: 'printer-studio', kind: 'printer', name: 'Studio', detail: 'Elyir Bench', when: NOW / 1000 - 2 * 3600,
  files: 14, gcodes: 23, history: 96, boards: ['stm32f446xx'] }
const PLAN: BringPlan = { id: 'card-sda2', config: 19, history: 212, spools: true, mainsail: true, gcodes: { count: 46, bytes: 812_000_000 },
  boards: [{ name: 'Main board', chip: 'stm32f446xx', match: 'same' }, { name: 'Toolhead board', can: '6cc850bbec73', match: 'same' }] }
const I = (o: Partial<BringInfo>): BringInfo => ({ ...EMPTY, sources: [CARD, STUDIO], ...o })
const start: Here = { at: 'start' }, sources: Here = { at: 'sources' }

test('a fresh card shows the first screen; the person moves through the sources, the address and the file', () => {
  assert.equal(screenFor(I({}), start, false), 'start')
  assert.equal(screenFor(I({}), sources, false), 'sources')
  assert.equal(screenFor(I({ state: 'scanning' }), sources, false), 'sources')
  assert.equal(screenFor(I({}), { at: 'address' }, false), 'address')
  assert.equal(screenFor(I({}), { at: 'file' }, false), 'file')
})

test('a source picked: reading it until its plan is the one picked, then what comes over', () => {
  const pick: Here = { at: 'plan', id: 'card-sda2' }
  assert.equal(screenFor(I({ state: 'planning' }), pick, false), 'planning')
  assert.equal(screenFor(I({ plan: { ...PLAN, id: 'printer-studio' } }), pick, false), 'planning')
  assert.equal(screenFor(I({ plan: PLAN }), pick, false), 'plan')
  // an address typed in: no id yet, the first plan that comes back is it
  assert.equal(screenFor(I({ plan: PLAN }), { at: 'plan' }, false), 'plan')
  assert.equal(screenFor(I({ state: 'failed', why: 'Nothing answered.' }), { at: 'plan' }, false), 'failed')
  // a failure from earlier doesn't follow the person back to the list
  assert.equal(screenFor(I({ state: 'failed', why: 'x' }), sources, false), 'sources')
})

test('bringing wins over where the person is (the phone follows the panel); the result is said once', () => {
  assert.equal(screenFor(I({ state: 'bringing' }), start, false), 'bringing')
  const ready = I({ state: 'done', plan: PLAN, result: { klipper: 'ready', message: 'Klipper is running.' } })
  assert.equal(screenFor(ready, start, false), 'done')
  assert.equal(screenFor(ready, start, true), 'start')
  assert.equal(screenFor(I({ state: 'done', result: { klipper: 'error', message: 'mcu: Unable to connect' } }), start, false), 'stopped')
})

test('shown instead of the app: setup, the Wi-Fi link, a copy going on, a result not seen; else the normal Now', () => {
  assert.equal(shown({ state: 'setup', info: null, requested: false, seen: false }), true)
  assert.equal(shown({ state: 'ready', info: null, requested: true, seen: false }), true)
  assert.equal(shown({ state: 'preparing', info: I({ state: 'bringing' }), requested: false, seen: false }), true)
  const done = I({ state: 'done', plan: PLAN, result: { klipper: 'ready', message: 'm' } })
  assert.equal(shown({ state: 'ready', info: done, requested: false, seen: false }), true)
  assert.equal(shown({ state: 'ready', info: done, requested: false, seen: true }), false)
  assert.equal(shown({ state: 'ready', info: I({}), requested: false, seen: false }), false)
  assert.equal(shown({ state: 'problem', info: null, requested: false, seen: false }), false)
  assert.equal(resultKey(done), 'card-sda2|ready|m')
  assert.equal(resultKey(I({})), '')
})

test('asked again quickly while the printer works, now and then on screen, never otherwise', () => {
  assert.equal(pollMs(I({ state: 'bringing' }), false), 1000)
  assert.equal(pollMs(I({ state: 'scanning' }), true), 1000)
  assert.equal(pollMs(I({}), true), 3000)
  assert.equal(pollMs(I({}), false), 0)
  assert.equal(pollMs(null, false), 0)
})

test('the step bar: Wi-Fi done, Printer on; both done at the end (Check comes with Check the printer)', () => {
  assert.deepEqual(STEPS, ['Wi-Fi', 'Printer'])
  assert.equal(stepOf('start'), 1)
  assert.equal(stepOf('plan'), 1)
  assert.equal(stepOf('done'), 2)
})

test('a-start: the words, the pill, and a printer it knows shown as later', () => {
  assert.equal(START_TITLE, 'Now the printer itself.')
  assert.equal(startSub(['Main board · STM32F446 on USB']), "It found these. It can't see how they're wired, so it needs a config, once.")
  assert.equal(startSub([]), "It can't see how the printer is wired, so it needs a config, once.")
  const w = ways([CARD, STUDIO])
  assert.deepEqual(w.map((x) => x.title), ['Bring it over', 'A printer I know', 'Write my own'])
  assert.equal(w[0].pill, 'Old card found')
  assert.equal(w[0].line, 'From your old card, another printer, or a backup. Everything comes with it.')
  assert.equal(w[1].later, true)
  assert.equal(w[2].line, "In Mainsail's editor. When Klipper starts, it's ready.")
  assert.equal(foundPill([STUDIO]), 'Printer found')
  assert.equal(foundPill([]), null)
})

test('a-bring: the old card first, then newest first, then an address and a backup file, in the words drawn', () => {
  assert.equal(SOURCES_TITLE, 'Bring it over from…')
  const rows = sourceRows([CARD, STUDIO], NOW)
  assert.deepEqual(rows.map((r) => r.title), ['Your old card', 'Studio, on your Wi-Fi', "Another printer's address", 'A backup file'])
  assert.equal(rows[0].line, 'In a USB reader · from Oct 3 · Voron')
  assert.equal(rows[1].line, 'Elyir Bench · changed 2 hours ago')
  assert.equal(rows[3].line, 'From your phone or computer')
  assert.equal(rows[0].lit, true)
  const older: BringSource = { ...STUDIO, id: 'printer-desk', name: 'Desk', when: NOW / 1000 - 5 * 86_400 }
  assert.deepEqual(sourceRows([older, CARD, STUDIO], NOW).slice(0, 3).map((r) => r.id), ['card-sda2', 'printer-studio', 'printer-desk'])
  const file: BringSource = { ...CARD, id: 'file-x', kind: 'file', name: 'voron-backup.zip', detail: 'A backup file', when: NOW / 1000 - 60 }
  assert.equal(sourceRows([file], NOW)[0].line, 'A backup file · from today')
})

test('days and times: American order, no year unless it differs', () => {
  assert.equal(dayWords(at(new Date(2026, 9, 5, 1)), NOW), 'today')
  assert.equal(dayWords(at(new Date(2026, 9, 4, 23)), NOW), 'yesterday')
  assert.equal(dayWords(at(new Date(2026, 9, 3, 12)), NOW), 'Oct 3')
  assert.equal(dayWords(at(new Date(2025, 11, 30, 12)), NOW), 'Dec 30, 2025')
  assert.equal(agoWords(NOW / 1000 - 10, NOW), 'just now')
  assert.equal(agoWords(NOW / 1000 - 60, NOW), '1 minute ago')
  assert.equal(agoWords(NOW / 1000 - 3 * 3600, NOW), '3 hours ago')
  assert.equal(agoWords(at(new Date(2026, 9, 3, 12)), NOW), 'Oct 3')
})

test('an address typed in, a backup picked on the phone', () => {
  assert.equal(addressProblem('voron.local'), null)
  assert.equal(addressProblem('192.168.1.40:7125'), null)
  assert.equal(addressProblem('http://studio.local/'), null)
  assert.equal(addressProblem(''), null)
  assert.match(addressProblem('my printer') ?? '', /doesn't look like an address/)
  assert.ok(isBackup('printer_data.tar.gz') && isBackup('config.ZIP') && isBackup('x.tgz'))
  assert.ok(!isBackup('printer.cfg'))
  assert.deepEqual(backupUpload('Downloads/voron.zip'), { root: 'config', path: 'elyir-bench-bring', name: 'voron.zip' })
})

test('a-bring-what: what comes over, the files offered but not ticked', () => {
  assert.equal(planTitle(CARD), 'From your old card')
  assert.equal(planTitle(STUDIO), 'From Studio')
  assert.deepEqual(comesOver(PLAN), ['Printer config, 19 files', 'Macros and calibration', 'History, 212 prints', 'Spools and Mainsail settings'])
  assert.deepEqual(comesOver({ ...PLAN, history: 0, spools: false, mainsail: true, config: 1 }), ['Printer config, 1 file', 'Macros and calibration', 'Mainsail settings'])
  assert.deepEqual(comesOver({ ...PLAN, history: true }).slice(2, 3), ['History of prints'])
  assert.deepEqual(gcodesOffer(PLAN), { label: 'Files, 46', line: '812 MB · takes longer' })
  assert.equal(gcodesOffer({ ...PLAN, gcodes: null }), null)
  assert.equal(gcodesOffer({ ...PLAN, gcodes: { count: 0, bytes: 0 } }), null)
  assert.equal(sizeWords(1_430_000_000), '1.4 GB')
  assert.equal(APPLY, 'Bring it over')
})

test('the same boards? same, changed (set to the one plugged in), missing', () => {
  assert.equal(BOARDS_TITLE, 'The same boards?')
  assert.equal(chipWords('stm32f446xx'), 'STM32F446')
  assert.equal(chipWords('rp2040'), 'RP2040')
  assert.deepEqual(boardLine(PLAN.boards[0]), { name: 'Main board', tone: 'green', line: 'STM32F446, same serial' })
  assert.deepEqual(boardLine(PLAN.boards[1]), { name: 'Toolhead board', tone: 'green', line: 'Same CAN ID' })
  assert.equal(boardLine({ name: 'Main board', chip: 'stm32f446xx', match: 'changed' }).line, 'STM32F446, another serial: it will be set to the one plugged in')
  assert.equal(boardLine({ name: 'Toolhead board', can: '1f0e', match: 'changed' }).line, 'Another CAN ID: it will be set to the one found')
  const missing = boardLine({ name: 'Toolhead board', can: '1f0e', match: 'missing' })
  assert.equal(missing.line, 'Not found: plug it in, or it can be changed after')
  assert.equal(missing.tone, 'amber')
})

test('bringing: the step, which of how many, how far', () => {
  assert.deepEqual(progressWords({ step: 'Copying the config', done: 2, of: 5 }), { step: 'Copying the config', count: 'Step 3 of 5', frac: 0.4 })
  assert.equal(progressWords({ step: 'Restarting Klipper', done: 5, of: 5 }).count, 'Step 5 of 5')
  assert.equal(progressWords(null).frac, 0)
  assert.equal(bringingNote('card'), 'Keep the printer on. Nothing on your old card changes.')
  assert.equal(bringingNote('printer'), 'Keep the printer on.')
})

test('how it ended: set up; Klipper stopped with the door; failed with nothing changed', () => {
  const ok = resultWords({ klipper: 'ready', message: 'Klipper is running with the config from your old card.' }, 'Voron')
  assert.equal(ok.title, 'Voron is set up.')
  assert.equal(ok.door, false)
  const err = resultWords({ klipper: 'error', message: 'mcu: Unable to connect' }, 'Voron')
  assert.equal(err.title, 'It came over, but Klipper stopped.')
  assert.equal(err.line, 'mcu: Unable to connect')
  assert.equal(err.door, true)
  assert.deepEqual(failedWords('The card was taken out.', true), { title: "It didn't come over.", line: 'The card was taken out. Nothing was changed.' })
  assert.equal(failedWords('Copy failed. Nothing changed.', true).line, 'Copy failed. Nothing changed.')
  assert.equal(failedWords('Nothing answered at x.', false).title, "It can't bring that over.")
})

test("the Wi-Fi's Connected link: Wi-Fi setup ends first, then Bring it over opens; a refusal opens nothing", async () => {
  const order: string[] = []
  const err = await bringFromWifi(async () => { order.push('done'); return null }, () => order.push('bring'))
  assert.equal(err, null)
  assert.deepEqual(order, ['done', 'bring'])
  const said: string[] = []
  const no = await bringFromWifi(async () => { said.push('done'); return "The printer didn't answer. Try again." }, () => said.push('bring'))
  assert.equal(no, "The printer didn't answer. Try again.")
  assert.deepEqual(said, ['done'])
})

test('a CAN board this card can\'t ask yet says so, and the plan\'s notes come through', () => {
  const line = boardLine({ name: 'Toolhead board', can: '6cc850bbec73', match: 'unchecked' })
  assert.equal(line.tone, 'blue')
  assert.match(line.line, /once CAN is set up/)
  assert.equal(boardLine({ name: 'Toolhead board', match: 'unchecked', words: 'Not checked: no CAN adapter yet' }).line, 'Not checked: no CAN adapter yet')
  assert.deepEqual(planNotes({ notes: ['Its print history stays on Studio.', ' '] } as never), ['Its print history stays on Studio.'])
  assert.deepEqual(planNotes(null), [])
})
