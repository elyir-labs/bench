// Pins the Bench Box from away (design/bench-remote/, C, picked 9 October 2026; A built as part of it): who the page is
// for, what each of them is offered, the invite's defaults, the guest's link and bench, and the box's Phones and
// watching line. The service side is bench/away.py (bench/tests/test_away.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { HOME, INVITE, INVITE_DEFAULT, LASTS_WORDS, REACH_WORDS, atHomeLine, awayShelfFoot, chipFor, dayLong, dayShort, guestLine, hereOf,
         hostOf, joinCard, joinFoot, joinTitle, lookingOnly, mayPlan, ownerOf, phoneRows, remoteRow, tabsFor, tileAct, watchingLine,
         type Here } from '../src/bench-app/away.ts'
import { ordered, sentence, tileOf, type BenchPrinter } from '../src/bench-app/bench.ts'
import { footOf } from '../src/bench-app/several.ts'

const intent = (state: string, extra: Record<string, unknown> = {}) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools: [], ...extra }) as any
const P = (name: string, i: any): BenchPrinter => ({ id: name.toLowerCase(), name, live: true, intent: i })
const BENCH = [
  P('Studio', intent('needs_you', { headline: 'White PLA ran out.', actions: [{ id: 'swap_slot', label: 'Use slot 6 instead', primary: true, style: 'amber' }] })),
  P('Kobra Max', intent('finished', { headline: 'Done.', actions: [{ id: 'print_another', label: 'Print another', primary: true, style: 'green' },
                                                                   { id: 'taken_off', label: "I've taken it off", primary: false, style: 'default' }] })),
  P('Desk', intent('ready', { detail: 'White PLA loaded' })),
]
const AWAY_LIST = ['cancel', 'cool_down', 'pause', 'resume', 'skip_part', 'stop_now', 'swap_slot']
const me = (extra: Record<string, unknown>) => hereOf({ paired: true, role: 'away', away: true, actions: AWAY_LIST, may: { queue: true, invite: true },
                                                     box: { name: 'Bench Box', address: 'bench-hillside.elyir.app' }, ...extra })
const PHONE = me({ kind: 'phone', reach: 'step_in', name: "Alex's iPhone" })
const GUEST = me({ kind: 'guest', reach: 'watch', name: 'Jo', invited_by: "Alex's iPhone", actions: [], may: { queue: false, invite: false },
                   until: new Date(2026, 9, 16, 19, 33).getTime() / 1000 })
const STEP_IN = { ...GUEST, reach: 'step_in', actions: AWAY_LIST } as Here
const NOW = new Date(2026, 9, 9, 19, 33)

test('at home /door/me is not there (or not JSON), and the page is exactly as before', () => {
  assert.deepEqual(hereOf(null), HOME)
  assert.deepEqual(hereOf('<!doctype html>'), HOME)
  assert.deepEqual(hereOf({ paired: true, role: 'home' }), HOME)
  assert.equal(HOME.away, false)
  assert.equal(hereOf({ paired: false, role: 'away', kind: null }).paired, false)
})

test('a guest gets Printers and Print; a phone away and home get every tab', () => {
  assert.deepEqual(tabsFor(GUEST), ['/', '/print'])
  assert.deepEqual(tabsFor(STEP_IN), ['/', '/print'])
  assert.deepEqual(tabsFor(PHONE), ['/', '/print', '/spools', '/care'])
  assert.deepEqual(tabsFor(HOME), ['/', '/print', '/spools', '/care'])
})

test('the chip: Away for a phone and a guest who steps in, Watching for a guest who watches, none at home', () => {
  assert.equal(chipFor(HOME), null)
  assert.deepEqual(chipFor(PHONE), { label: 'Away', icon: 'lock' })
  assert.deepEqual(chipFor(GUEST), { label: 'Watching', icon: 'eye' })
  assert.deepEqual(chipFor(STEP_IN), { label: 'Away', icon: 'lock' })
  assert.equal(chipFor(hereOf({ paired: false, role: 'away' })), null)
  assert.deepEqual([PHONE.may, GUEST.may], [{ queue: true, invite: true }, { queue: false, invite: false }])
})

test('tiles away offer only what the away list allows (A-phone-bench); a guest who watches gets no buttons (C-guest-watch)', () => {
  const [r2, kmax, c3] = ordered(BENCH)
  assert.deepEqual([r2.actionId, kmax.actionId, c3.actionId], ['swap_slot', 'taken_off', 'print_model'])
  assert.deepEqual(tileAct(r2, HOME), { button: 'Use slot 6 instead', note: null })
  assert.deepEqual(tileAct(kmax, HOME), { button: "I've taken it off", note: null })
  assert.deepEqual(tileAct(r2, PHONE), { button: 'Use slot 6 instead', note: null })
  assert.deepEqual(tileAct(kmax, PHONE), { button: null, note: 'Take it off at home' })
  assert.deepEqual(tileAct(c3, PHONE), { button: null, note: null })
  for (const t of [r2, kmax, c3]) assert.deepEqual(tileAct(t, GUEST), { button: null, note: null })
  assert.deepEqual(tileAct(r2, STEP_IN), { button: 'Use slot 6 instead', note: null })
  assert.deepEqual(tileAct({ ...c3, action: "It's clear, start", actionId: null, queued: 'q1' }, PHONE), { button: null, note: 'Starts at home' })
  assert.deepEqual(tileAct({ ...r2, actionId: 'load' }, PHONE), { button: null, note: 'Needs someone at home' })
})

test("a guest's sentence names who they're waiting for, and the line under says until when", () => {
  assert.equal(ownerOf("Alex's iPhone"), 'Alex')
  assert.equal(ownerOf('Pixel 8'), 'Pixel 8')
  assert.equal(hostOf(GUEST), 'Alex')
  assert.equal(hostOf({ ...GUEST, invitedBy: 'Bench Box' }), 'someone at home')
  const tiles = ordered([...BENCH, P('Kobra 3', intent('printing', { job: { name: 'Clip', eta_clock: '7:58 pm', remaining_s: 100, progress: 0.4 } }))])
  assert.equal(sentence(tiles, hostOf(GUEST)), 'Two are waiting for Alex: Studio and Kobra Max. Kobra 3 is done at 7:58 pm.')
  assert.equal(sentence(tiles), 'Two need you: Studio and Kobra Max. Kobra 3 is done at 7:58 pm.')
  assert.equal(sentence(ordered([BENCH[0]]), 'Alex'), 'Studio is waiting for Alex.')
  assert.equal(guestLine({ ...GUEST, until: new Date(2026, 9, 15, 19, 33).getTime() / 1000 }, NOW),
    "You're watching until Thursday. Tap a printer to see its camera. Pausing or stopping is up to Alex.")
  assert.equal(guestLine({ ...STEP_IN, until: null }, NOW),
    'You can watch and step in until Alex ends it. Tap a printer to see its camera, and to pause or stop its print.')
})

test('days: today and tomorrow with the time, the rest of the week by name, later with the date', () => {
  const at = (d: number, h = 19, m = 33) => new Date(2026, 9, d, h, m).getTime() / 1000
  assert.equal(dayLong(at(9, 21, 5), NOW), 'today at 9:05 pm')
  assert.equal(dayLong(at(10), NOW), 'tomorrow at 7:33 pm')
  assert.equal(dayLong(at(16), NOW), 'Friday, October 16')
  assert.equal(dayShort(at(15), NOW), 'Thursday')
  assert.equal(dayShort(at(16), NOW), 'Friday, October 16')
})

test('Invite someone starts on Watch, for a week, and says the link works once (C-phone-invite)', () => {
  assert.deepEqual(INVITE_DEFAULT, { reach: 'watch', lasts: 'week' })
  assert.equal(INVITE.title, 'Invite someone')
  assert.equal(INVITE.go, 'Share the link')
  assert.equal(INVITE.foot, 'The link works once. If nobody opens it, it stops working tomorrow.')
  assert.deepEqual(Object.values(REACH_WORDS).map((r) => r.label), ['Watch', 'Watch and step in'])
  assert.equal(REACH_WORDS.watch.line, 'See every printer, its camera and the shelf. Touch nothing.')
  assert.deepEqual(Object.values(LASTS_WORDS), ['A day', 'A week', 'Until I remove it'])
})

test('opening the link: who invited you, what you can do, until when (C-guest-open)', () => {
  const look = { box: { name: 'Bench Box' }, invited_by: "Alex's iPhone", reach: 'watch' as const, until: new Date(2026, 9, 16, 19, 33).getTime() / 1000 }
  assert.equal(joinTitle(look), 'Alex invited you to see their printers.')
  assert.deepEqual(joinCard(look, NOW), { chip: 'Watch', until: 'until Friday, October 16',
    line: "See every printer, its camera and the shelf. You can't change anything." })
  assert.equal(joinFoot(look), 'Alex sees your name, and can end this at any time. To come back easily: Share, then Add to Home Screen.')
  assert.equal(joinTitle({ ...look, invited_by: 'Bench Box' }), "You're invited to see the printers.")
  assert.equal(joinCard({ ...look, reach: 'step_in', until: null }, NOW).until, 'until they end it')
})

test('the shelf away: prints start at home; a guest is asked nothing', () => {
  assert.equal(atHomeLine({ name: 'Desk', filament: 'gray PETG' }),
    'Someone at the printer checks the bed is clear first. Desk is free now, with gray PETG loaded.')
  assert.equal(lookingOnly('Desk is free. What should it print?'), 'Desk is free.')
  assert.equal(awayShelfFoot(GUEST), 'Every model printed on the bench lands here.')
})

test('several at once (design/bench-several/, C): home and a paired phone away get Select, a guest never', () => {
  assert.deepEqual([HOME, PHONE, GUEST, STEP_IN].map(mayPlan), [true, true, false, false])
  assert.equal(mayPlan({ ...PHONE, may: { queue: false, invite: false } }), false)
  assert.deepEqual(footOf({ checking: false, beds: [{} as never], cant: [], out: [], said: [], free_left: [], printers: 2, done_at: null, ahead: 0 }, PHONE.away),
                   { done: '', line: 'Nothing starts until someone at home says each bed is clear.', go: 'Add to the queue', short: 'Add to the queue', can: true })
})

test("the box's Phones: the household's phones, guests with reach and end, then unopened invites (C-box-phones)", () => {
  const t = (d: number, h = 19, m = 33) => new Date(2026, 9, d, h, m).getTime() / 1000
  const rows = phoneRows({
    address: 'bench-hillside.elyir.app',
    phones: [{ id: 'a', name: "Alex's iPhone", joined: t(1), last_seen: t(9, 19, 32), notifications: true, kind: 'phone', watching: 1 },
             { id: 'p', name: 'Pixel 8', joined: t(1), last_seen: t(8, 12), notifications: false, kind: 'phone', watching: 0 }],
    guests: [{ id: 'j', name: 'Jo', joined: t(9), last_seen: t(9), notifications: false, kind: 'guest', watching: 1, reach: 'watch',
               until: t(16), invited_by: "Alex's iPhone" }],
    invites: [{ id: 'i', reach: 'step_in', lasts: 'week', invited_by: 'Alex', made: t(9, 19, 33), expires: t(10), until: t(16) }],
    watching: ['Jo'],
  }, NOW)
  assert.deepEqual(rows.map((r) => [r.title, r.chip, r.line, r.button]), [
    ["Alex's iPhone", null, 'Seen just now · notifications on', 'Remove'],
    ['Pixel 8', null, 'Seen yesterday', 'Remove'],
    ['Jo', 'Guest · Watch', 'Invited by Alex · until Friday, October 16 · watching now', 'Remove'],
    ['Not opened yet', 'Guest · Watch and step in', 'Invited by Alex · for a week · the link stops working tomorrow at 7:33 pm', 'Cancel the invite'],
  ])
  assert.deepEqual(rows.map((r) => r.watching), [false, false, true, false])   // the household's phones never show as watching
})

test("the box's top line says who is watching, and nothing when nobody is", () => {
  assert.equal(watchingLine([]), null)
  assert.equal(watchingLine(['Jo']), 'Jo is watching')
  assert.equal(watchingLine(['Jo', 'Sam', 'Jo']), 'Jo and Sam are watching')
  assert.equal(watchingLine(['Jo', 'Sam', 'Ana']), 'Jo, Sam and Ana are watching')
})

test('From away in Care says plainly whether the bench can be reached, and asks for a code only without a name', () => {
  const r = { on: true, name: 'bench-hillside', address: 'bench-hillside.elyir.app', open: true, carried: true, link: 'on' }
  assert.deepEqual(remoteRow(r), { title: 'From away', on: true, button: 'Turn off', needsCode: false,
    line: 'On, at bench-hillside.elyir.app. Phones added here, and people you invite, reach the bench there.' })
  assert.equal(remoteRow({ ...r, link: 'waiting' }).line, "bench-hillside.elyir.app isn't reachable yet. The box tries again every minute.")
  assert.deepEqual([remoteRow({ ...r, on: false }).button, remoteRow({ ...r, on: false }).needsCode], ['Turn on', false])
  assert.deepEqual([remoteRow({ ...r, on: false, address: null, name: null }).needsCode, remoteRow({ ...r, address: null }).needsCode], [true, true])
})
