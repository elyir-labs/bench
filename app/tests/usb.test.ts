// Pins the USB stick round (design/usb/: 1 A, all of 2, 3 A): the sheet's words, the line over a print, Care's row.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { usbBanner, usbRow, usbSheet, usbTakeArgs, type UsbView } from '../src/intent/usb.ts'

const HAVE = '2026.11.08-2ee0dc7'
const NEXT = '2026.11.09-4b1e0a2'
const stick: UsbView = {
  id: 'AB12', present: true, readable: true, folder: true, seen: false, skipped: false, take: null,
  app: { version: NEXT, why: null, size: 21e6 }, os: null, keys: [], wifi: null,
}
const KEY = { id: 'k1', kind: 'ssh-ed25519', name: 'laptop', fp: 'SHA256:q9XcV1mE8rT2k' }

test('a stick with a newer version asks to update, as drawn', () => {
  const s = usbSheet(stick, 'Workshop', { have: HAVE })!
  assert.equal(s.title, 'A USB stick with the 9 November version')
  assert.match(s.line, /^Update Workshop to it\? Its screens are back in about a minute\./)
  assert.equal(s.small, `Has ${HAVE} · the stick has ${NEXT}`)
  assert.deepEqual(s.acts.map((a) => a.label), ['Not now', 'Update'])
})

test('the box says the Kobras come with it', () => {
  assert.match(usbSheet(stick, 'Bench Box', { box: true, kobras: true })!.line, /The Kobras' screens come from the box/)
})

test('a card takes its whole OS', () => {
  const s = usbSheet({ ...stick, app: { version: NEXT, why: 'with_os' },
    os: { version: NEXT, why: null, board: 'pi5', on: 'pi5', size: 923e6, file: `os/elyir-bench-os-${NEXT}-pi5.tar` } }, 'Studio')!
  assert.equal(s.title, 'A USB stick with the 9 November Elyir Bench OS')
  assert.equal(s.small, `A Pi 5 card · the stick has elyir-bench-os-${NEXT}-pi5.tar (923 MB)`)
})

test('a key or Wi-Fi turns it into ticks, never ticked for you', () => {
  const u = { ...stick, keys: [KEY], wifi: { name: 'Home Wi-Fi', can: true } }
  const s = usbSheet(u, 'Workshop', { have: HAVE })!
  assert.equal(s.title, 'On this USB stick')
  assert.deepEqual(s.choices.map((c) => [c.title, c.on]), [
    ['The 9 November version', true], ['An SSH key named “laptop”', false], ['Wi-Fi “Home Wi-Fi”', false]])
  assert.equal(s.choices[0].line, 'Workshop has the 8 November one.')
  assert.equal(s.choices[1].line, 'That computer can sign in to Workshop. SHA256:q9Xc…T2k')
  assert.deepEqual(usbTakeArgs(u, {}), { app: true, os: false, keys: [], wifi: false })
  assert.deepEqual(usbTakeArgs(u, { app: false, 'key:k1': true, wifi: true }), { app: false, os: false, keys: ['k1'], wifi: true })
})

test('not now, older and the same say nothing; Look asks again', () => {
  assert.equal(usbSheet({ ...stick, skipped: true }, 'Workshop'), null)
  assert.ok(usbSheet({ ...stick, skipped: true }, 'Workshop', { force: true }))
  assert.equal(usbSheet({ ...stick, app: { version: '2026.11.02-91c3d0e', why: 'older' } }, 'Workshop'), null)
  assert.equal(usbSheet({ ...stick, present: false }, 'Workshop'), null)
})

test("says why when it can't be used", () => {
  assert.equal(usbSheet({ ...stick, app: { version: NEXT, why: 'unsigned' } }, 'Workshop')!.title, "It isn't signed by Elyir")
  assert.equal(usbSheet({ ...stick, readable: false, app: null }, 'Workshop')!.title, "Couldn't read the stick")
  const b = usbSheet({ ...stick, app: null, os: { version: NEXT, why: 'board', board: 'pi4', on: 'pi5' } }, 'Workshop')!
  assert.equal(b.line, "The stick's system is for a Pi 4. Workshop is a Pi 5.")
  assert.equal(b.tone, 'bad')
})

test('copying, then the stick can come out, then done', () => {
  const t = (take: UsbView['take']) => usbSheet({ ...stick, take }, 'Workshop')!
  const c = t({ state: 'copying', app: NEXT, done: 14e6, of: 21e6 })
  assert.equal(c.line, "Don't take it out yet. Copying the 9 November version, 14 of 21 MB.")
  assert.ok(Math.abs((c.progress ?? 0) - 14 / 21) < 1e-9)
  const i = t({ state: 'installing', app: NEXT, out: true })
  assert.equal(i.line, 'Copied and checked. You can take the stick out now.')
  assert.equal(i.status, 'Starting the 9 November version…')
  const d = t({ state: 'done', app: NEXT, keys: 1, wifi: 'Home Wi-Fi', result: 'done' })
  assert.equal(d.title, 'Workshop has the 9 November version')
  assert.match(d.line, /^That computer can sign in now\. Workshop knows Home Wi-Fi now\. You can take the stick out\./)
  assert.equal(t({ state: 'failed', app: NEXT, why: "It isn't signed by Elyir, so it wasn't installed." }).title, "It didn't update")
})

test('a report onto the stick', () => {
  const s = usbSheet({ ...stick, take: { state: 'done', report: 'workshop-report-2026-11-09-2141.tar.gz' } }, 'Workshop')!
  assert.equal(s.title, 'Report copied to the stick')
  assert.match(s.line, /^workshop-report-2026-11-09-2141\.tar\.gz: the last day of logs/)
})

test('over a print, a line at the top instead of the sheet', () => {
  const u = { ...stick, take: { state: 'waiting' as const, app: NEXT, out: true, auto: 'print' as const, why: "It's printing." } }
  assert.deepEqual(usbBanner(u, 'Workshop', { printing: true }), {
    title: 'The 9 November version is copied from the stick', line: 'You can take the stick out. Workshop updates after this print.',
    act: 'Not this time' })
  assert.equal(usbSheet(u, 'Workshop', { printing: true }), null)
  assert.equal(usbBanner(u, 'Workshop', { printing: false }), null)
  assert.equal(usbBanner(u, 'Bench Box', { printing: true, box: true }), null, 'the box shows its sheet')
  assert.equal(usbSheet(u, 'Bench Box', { box: true })!.line, "You can take the stick out. It's printing. The box updates after that.")
})

test("Care's row", () => {
  assert.deepEqual(usbRow({ ...stick, keys: [KEY], wifi: { name: 'Home Wi-Fi', can: true } }, 'Workshop'), {
    title: 'USB stick', line: 'The 9 November version, an SSH key and Wi-Fi are on it.',
    buttons: [{ key: 'look', label: 'Look' }, { key: 'report', label: 'Copy a report' }] })
  assert.equal(usbRow({ ...stick, app: null, folder: false }, 'Workshop')!.line, 'A stick is in. Nothing on it for Workshop.')
  assert.equal(usbRow({ ...stick, present: false }, 'Workshop'), null)
})
