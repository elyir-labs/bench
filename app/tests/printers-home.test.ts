// The Printers list grouped by what to do (design/printers-home/, A, picked 15 October 2026): the picked board is the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { allAway, attentionTone, cardOf, chipsOf, clock, grouped, groupLabel, loadedColor, markAway, pictureOf, rowOf, snapshotOf, straightIn } from '../src/shell-app/home.ts'
import type { LivePrinter } from '../src/shell-app/printers.ts'
import type { Intent } from '../src/intent/types.ts'

const NOW = new Date(2026, 9, 15, 15, 0).getTime()
const iso = (h: number, m: number, day = 15) => new Date(2026, 9, day, h, m).toISOString()
let added = 0
function printer(name: string, intent: Partial<Intent> | null, reach: LivePrinter['reach'] = 'home'): LivePrinter {
  return {
    id: name.toLowerCase(), name, token: 't0k', added: ++added, reach, connected: !!intent,
    addresses: { home: `https://${name.toLowerCase()}.home.elyir.app`, away: null }, base: reach === 'home' || reach === 'away' ? `https://${name.toLowerCase()}.home.elyir.app` : null,
    intent: intent ? ({ state: 'ready', headline: '', detail: '', since: iso(12, 0), spools: [], job: null, ...intent } as Intent) : null,
  }
}
const job = (name: string, progress = 1, extra = {}) => ({ name, thumbnail: '.thumbs/stand-300x300.png', progress, eta_clock: '3:10 pm', ...extra }) as Intent['job']

const Workshop = printer('Workshop', { state: 'printing', job: job('Phone stand', 0.62) })
const Studio = printer('Studio', { state: 'problem', headline: 'The print head lost contact for a moment.' })
const Desk = printer('Desk', { state: 'ready', detail: 'Black ASA loaded.', spools: [{ slot: 0, color: '#1b1b1f', in_use: true } as Intent['spools'][0]] })
const K3 = printer('Kobra 3', { state: 'finished', since: iso(13, 52), job: job('Cable clip') })
const K3M = printer('Kobra 3 Max', { state: 'finished', since: iso(14, 30), job: job('Planter') })
const GONE = printer('Garage', null, 'offline')

test('who needs you first, then printing, done, ready, out of reach; added order inside a group', () => {
  const g = grouped([Desk, K3M, GONE, Workshop, K3, Studio])
  assert.deepEqual(g.map((x) => [x.group, x.printers.map((p) => p.name)]), [
    ['attention', ['Studio']], ['busy', ['Workshop']], ['done', ['Kobra 3', 'Kobra 3 Max']], ['ready', ['Desk']], ['off', ['Garage']],
  ])
})

test('each group says what to do once', () => {
  assert.equal(groupLabel('attention', [Studio]), 'Needs you')
  assert.equal(groupLabel('busy', [Workshop]), 'Printing')
  assert.equal(groupLabel('busy', [Workshop, printer('X', { state: 'preparing' })]), 'Busy')
  assert.equal(groupLabel('done', [K3, K3M]), 'Done · lift them off')
  assert.equal(groupLabel('done', [K3]), 'Done · lift it off')
  assert.equal(groupLabel('off', [GONE]), 'Out of reach')
  assert.equal(groupLabel('off', [GONE], true), 'At home only')
  assert.equal(groupLabel('off', [printer('Y', null, 'checking')]), 'Looking…')
})

test('a row: the object and when, not the same sentence again', () => {
  assert.deepEqual(rowOf(Workshop, false, NOW), { word: '62%', line: 'Phone stand · done at about 3:10 pm', progress: 0.62 })
  assert.deepEqual(rowOf(K3, false, NOW), { word: '1:52 pm', line: 'Cable clip', progress: null })
  assert.deepEqual(rowOf(Studio, false, NOW), { word: 'Stopped', line: 'The print head lost contact for a moment.', progress: null })
  assert.deepEqual(rowOf(Desk, false, NOW), { word: 'Ready', line: 'Black ASA loaded.', progress: null })
  assert.equal(rowOf(GONE, true, NOW).word, 'At home only')
  assert.equal(clock(iso(9, 5), NOW), '9:05 am')
  assert.equal(clock(iso(23, 0, 14), NOW), 'Yesterday')
  assert.equal(clock(iso(10, 0, 12), NOW), 'Monday')
})

test('pictures: the job while there is one; a swatch for Ready; nothing for a stopped printer', () => {
  assert.equal(pictureOf(Workshop), 'https://workshop.home.elyir.app/server/files/gcodes/.thumbs/stand-300x300.png?access_token=t0k')
  assert.ok(pictureOf(K3))
  assert.equal(pictureOf(Studio), null)
  assert.equal(pictureOf(Desk), null)
  assert.equal(loadedColor(Desk), '#1b1b1f')
})

test('away is said once, or only on the exception', () => {
  const awayA = printer('A', { state: 'ready' }, 'away'), awayB = printer('B', { state: 'ready' }, 'away')
  assert.equal(allAway([awayA, awayB, GONE]), true)
  assert.equal(markAway(awayA, [awayA, awayB]), false)
  assert.equal(allAway([awayA, Workshop]), false)
  assert.equal(markAway(awayA, [awayA, Workshop]), true)
  assert.equal(markAway(Workshop, [awayA, Workshop]), false)
})

// A printer, opened in the Printers app (design/printers-open/, A, picked 17 October 2026): the picked boards are the spec.
const DESK = printer('Desk', { state: 'needs_you', headline: 'White PLA ran out.' })

test('a printer that needs you: the heading says so, the row says why', () => {
  assert.deepEqual(rowOf(DESK, false, NOW), { word: '', line: 'White PLA ran out.', progress: null })
  assert.equal(attentionTone([DESK]), 'amber')
  assert.equal(attentionTone([DESK, Studio]), 'red')
})

test('overview cards say their group themselves', () => {
  assert.deepEqual(cardOf(K3, false, NOW), { word: 'Done', line: 'Cable clip · lift it off · 1:52 pm', progress: null })
  assert.deepEqual(cardOf(Workshop, false, NOW), rowOf(Workshop, false, NOW))
})

test('one printer goes straight in; two, or a Bench Box, get the list', () => {
  assert.equal(straightIn([Workshop], 0), 'workshop')
  assert.equal(straightIn([Workshop, Desk], 0), null)
  assert.equal(straightIn([Workshop], 1), null)
  assert.equal(straightIn([], 0), null)
})

test('chips: the printers that answer in the list order, the rest counted', () => {
  const c = chipsOf([Desk, GONE, Workshop, Studio])
  assert.deepEqual(c.on.map((p) => p.name), ['Studio', 'Workshop', 'Desk'])
  assert.equal(c.off, 1)
})

test('a camera still only while there is a print to watch', () => {
  assert.equal(snapshotOf(Workshop, 3), 'https://workshop.home.elyir.app/webcam/?action=snapshot&access_token=t0k&t=3')
  assert.equal(snapshotOf(K3), null)
  assert.equal(snapshotOf(GONE), null)
})
