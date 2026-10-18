// Bring it over from a Bench Cloud backup (design/cloud/ C, picked 11 October 2026; docs/cloud.md): the backup first in
// the list, the owner screen (C-panel-restore: Allow on the owner's phone, or the code from the email), and its words.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  EMPTY, screenFor, pollMs, foundPill, sourceRows, backupWords, clockWords, planTitle, cloudAllowTitle, cloudEmailLine,
  cloudEnd, isCode, cloudTypeLine, isCloudFile, CLOUD_TYPE, CLOUD_TITLE, CLOUD_NEEDS, CLOUD_NOTE, type BringInfo, type BringSource, type CloudAsk,
} from '../src/intent/bring.ts'

const NOW = new Date(2026, 9, 12, 9, 30).getTime()                 // 12 Oct 2026, 9:30 am local
const at = (d: Date) => d.getTime() / 1000
const CLOUD: BringSource = { id: 'cloud-p-workshop', kind: 'cloud', name: 'Workshop', detail: 'Your Bench Cloud backup',
  when: at(new Date(2026, 9, 12, 2, 10)), files: 0, gcodes: 0, history: 0, boards: [],
  owner_phone: "Alex's iPhone", owner_email: 'a•••x@example.net' }
const CARD: BringSource = { id: 'card-sda2', kind: 'card', name: 'Voron', detail: 'In a USB reader', when: at(new Date(2026, 9, 3, 21, 14)),
  files: 19, gcodes: 46, history: 212, boards: [] }
const ASK: CloudAsk = { id: 'cloud-p-workshop', name: 'Workshop', state: 'waiting', owner_phone: "Alex's iPhone", owner_email: 'a•••x@example.net' }
const I = (o: Partial<BringInfo>): BringInfo => ({ ...EMPTY, sources: [CARD, CLOUD], ...o })

test('the Bench Cloud backup comes first in the list, with when it was made', () => {
  const rows = sourceRows([CARD, CLOUD], NOW)
  assert.deepEqual(rows[0], { id: 'cloud-p-workshop', icon: 'cloud', title: 'Your Bench Cloud backup',
                              line: 'Workshop · last night at 2:10 am', press: 'cloud', lit: true })
  assert.equal(rows[1].id, 'card-sda2')
  assert.equal(foundPill([CARD, CLOUD]), 'Your backup found')
  assert.equal(planTitle(CLOUD), CLOUD_TITLE)
})

test('a backup is said by when it was made', () => {
  assert.equal(clockWords(new Date(2026, 9, 12, 0, 5)), '12:05 am')
  assert.equal(clockWords(new Date(2026, 9, 12, 13, 0)), '1:00 pm')
  assert.equal(backupWords(at(new Date(2026, 9, 12, 2, 10)), NOW), 'last night at 2:10 am')
  assert.equal(backupWords(at(new Date(2026, 9, 12, 6, 0)), NOW), 'today at 6:00 am')
  assert.equal(backupWords(at(new Date(2026, 9, 11, 23, 40)), NOW), 'last night at 11:40 pm')
  assert.equal(backupWords(at(new Date(2026, 9, 11, 14, 0)), NOW), 'yesterday at 2:00 pm')
  assert.equal(backupWords(at(new Date(2026, 9, 9, 2, 10)), NOW), 'Oct 9 at 2:10 am')
  assert.equal(backupWords(NOW / 1000 - 30, NOW), 'just now')
  assert.equal(backupWords(NOW / 1000 - 20 * 60, NOW), '20 minutes ago')
  assert.equal(backupWords(NOW / 1000 - 2 * 3600 - 60, NOW), '2 hours ago')
})

test('picking it shows the owner screen while it waits, and asks the printer quickly', () => {
  assert.equal(screenFor(I({ cloud: ASK }), { at: 'cloud', id: 'cloud-p-workshop' }, false), 'cloud')
  assert.equal(pollMs({ state: 'asking', role: null, cloud: null }, true), 1000)
  assert.equal(pollMs({ state: 'idle', role: null, cloud: ASK }, true), 1000)
  assert.equal(pollMs({ state: 'idle', role: null, cloud: { ...ASK, state: 'refused' } }, true), 3000)
})

test('the owner screen, as C-panel-restore draws it', () => {
  assert.equal(CLOUD_NEEDS, "This needs the house's owner. Either works:")
  assert.equal(cloudAllowTitle(ASK), "Allow on Alex's iPhone")
  assert.equal(cloudAllowTitle({ owner_phone: null }), "Allow on the owner's phone")
  assert.equal(cloudEmailLine(ASK), 'Goes to a•••x@example.net')
  assert.equal(cloudEmailLine({ ...ASK, emailed: 'a•••x@example.net' }), 'Sent to a•••x@example.net')
  assert.equal(CLOUD_NOTE, "Restoring needs the owner, so a stolen printer can't pull your settings.")
  assert.ok(isCode('482 913') && !isCode('48291') && !isCode('48291x'))
})

test('on the panel, once the code is sent: only the code to type, and Allow still works', () => {
  assert.equal(CLOUD_TYPE, 'Type the code from the email')
  assert.equal(cloudTypeLine({ ...ASK, emailed: 'a•••x@example.net' }), "Sent to a•••x@example.net. Allow on Alex's iPhone still works.")
})

test('once allowed, the backup file it becomes keeps the Bench Cloud title', () => {
  const file: BringSource = { ...CARD, id: 'file-workshop-bench-cloud-tar-gz', kind: 'file', name: 'Workshop' }
  assert.ok(isCloudFile(file) && !isCloudFile({ id: 'file-voron-zip', kind: 'file' }))
  assert.equal(planTitle(file), CLOUD_TITLE)
})

test('a refused or forgotten ask says so', () => {
  assert.equal(cloudEnd('waiting'), null)
  assert.equal(cloudEnd('refused')?.title, 'The owner said no.')
  assert.equal(cloudEnd('expired')?.line, 'An ask lasts 30 minutes. Ask again, or use the code from the email.')
})
