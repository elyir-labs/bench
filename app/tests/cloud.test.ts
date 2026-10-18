// Bench Cloud on a phone (design/cloud/ C, picked 11 October 2026; docs/cloud.md): the card in Care, turning it on
// (C-phone-join), a second way back (C-phone-backup), the Allow card (C-phone-allow), and talking to the cloud.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  CLOUD_API, JOIN_TITLE, awayLine, panelOff, JOIN_SUB, GETS, EMAIL_HINT, INVITE_HINT, ON_TITLE, SECOND_LABEL, SECOND_LINE,
  allowTitle, allowWhat, allowWhere, cardLine, cardState, cloudCall, codeTitle, digitsOf, loadOwner, onLine, ownerCall, ownerToken,
  saveOwner, secondDone, sendCode, sixDigits, validEmail, validInvite, verifyCode, type DoorCloud, type Owner,
} from '../src/cloud.ts'

const NOW = new Date(2026, 9, 12, 9, 30).getTime()
const at = (d: Date) => d.getTime() / 1000
const OFF: DoorCloud = { joined: false, name: null, house: null, last: null }
const ON: DoorCloud = { joined: true, name: 'Workshop', house: 'h_1', last: { at: at(new Date(2026, 9, 12, 2, 10)), size: 1300 } }
const OWNER = { api: CLOUD_API, token: 'o_x', email: 'alex@example.net' }

test('the card in Care: off, the owner here but this printer not yet in, and on with its last backup', () => {
  assert.equal(cardState(OFF, null), 'off')
  assert.equal(cardState(OFF, OWNER), 'owner')
  assert.equal(cardState(ON, null), 'on')
  assert.equal(cardLine('off', OFF, 'Workshop', NOW), 'Off. Everything here works without it, and always will.')
  assert.equal(cardLine('owner', OFF, 'Workshop', NOW), 'Your Bench Cloud is on. Add Workshop for a backup every night.')
  assert.equal(cardLine('on', ON, 'Workshop', NOW), 'On · backed up last night at 2:10 am')
  assert.equal(cardLine('on', { ...ON, last: null }, 'Workshop', NOW), 'On · the first backup is tonight')
  assert.equal(cardLine('on', { ...ON, last: { at: 1, why: "Bench Cloud can't be reached right now." } }, 'Workshop', NOW),
               "On · the last backup didn't happen: Bench Cloud can't be reached right now.")
  assert.equal(panelOff('Workshop'), 'Off. To turn it on: on your phone, open the Printers app at printers.elyir.app.')
  assert.equal(awayLine('off', 'Workshop'), 'Off. Turn it on from your phone, at home.')
  assert.equal(awayLine('owner', 'Studio'), 'Add Studio from your phone, at home.')
  assert.equal(awayLine('on', 'Workshop'), null)
})

test('turning it on, as C-phone-join draws it (free for testers: an invite code, no payment, no Face ID yet)', () => {
  assert.equal(JOIN_TITLE, 'Bench Cloud for this house')
  assert.equal(JOIN_SUB, 'Every phone at home gets it, with no sign-in.')
  assert.deepEqual(GETS.map((g) => g.title), ['A backup every night', 'A new card comes back as it was'])
  assert.match(EMAIL_HINT, /You'll be the owner.*No password\.$/)
  assert.equal(INVITE_HINT, 'Bench Cloud is free for testers for now, by invite.')
  assert.equal(codeTitle('a•••x@example.net'), 'Type the code we sent to a•••x@example.net')
  assert.ok(validEmail(' alex@example.net ') && !validEmail('alex@') && !validEmail('alex example.net'))
  assert.ok(validInvite('S37F-GQA4') && validInvite('s37fgqa4') && !validInvite('S37F'))
  assert.ok(sixDigits('482 913') && !sixDigits('48291'))
  assert.equal(digitsOf('48-29 13x9'), '482913')
})

test('a second way back, as C-phone-backup draws it', () => {
  assert.equal(ON_TITLE, 'Bench Cloud is on.')
  assert.equal(onLine('alex@example.net', 'Workshop'), "Workshop's first backup is tonight. You're the owner, as alex@example.net.")
  assert.equal(SECOND_LABEL, 'A second way back')
  assert.equal(SECOND_LINE, "If this phone is lost and you can't get into your email, a second owner gets you back in.")
  assert.equal(secondDone('jo@example.net'), 'We emailed jo@example.net an invite. They become an owner when they accept it, signed in with that email.')
})

test('the Allow card for a new card, as C-phone-allow draws it', () => {
  assert.equal(allowTitle('Workshop'), "Allow Workshop's backup onto a new card?")
  assert.equal(allowWhat(at(new Date(2026, 9, 12, 2, 10)), NOW),
               'From last night at 2:10 am: settings, print history and spools. Its address from away and its paired phones come back too.')
  assert.match(allowWhat(NOW / 1000 - 30, NOW), /^Made just now: /)
  assert.match(allowWhat(NOW / 1000 - 20 * 60, NOW), /^Made 20 minutes ago: /)
  assert.match(allowWhat(null, NOW), /^Its last backup: /)
  assert.equal(allowWhere('Workshop', NOW / 1000 - 20, NOW), "Asked from Workshop's own screen, at home, just now")
})

test('the owner is kept on this phone, and a broken or missing record is no owner', () => {
  const box = new Map<string, string>()
  const store = { getItem: (k: string) => box.get(k) ?? null, setItem: (k: string, v: string) => void box.set(k, v),
                  removeItem: (k: string) => void box.delete(k) }
  assert.equal(loadOwner(store), null)
  saveOwner(store, OWNER)
  assert.deepEqual(loadOwner(store), OWNER)
  box.set('elyir.cloud.owner', '{nope')
  assert.equal(loadOwner(store), null)
  saveOwner(store, null)
  assert.equal(loadOwner(store), null)
  assert.equal(loadOwner(null), null)
})

test("the cloud's own words when it refuses, and words when it can't be reached", async () => {
  const answer = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as typeof fetch
  assert.deepEqual(await cloudCall('https://c', 'POST', '/v1/start', { email: 'a@b.c' }, undefined, answer(200, { pending: 'c_1' })), { pending: 'c_1' })
  await assert.rejects(cloudCall('https://c', 'POST', '/v1/start', {}, undefined, answer(403, { error: "That code isn't one." })),
                       { message: "That code isn't one." })
  await assert.rejects(cloudCall('https://c', 'GET', '/v1/me', undefined, 'o_x', (async () => { throw new TypeError('offline') }) as typeof fetch),
                       { message: "Bench Cloud can't be reached right now." })
  let sent: RequestInit | undefined
  await cloudCall('https://c', 'GET', '/v1/asks', undefined, 'o_x', (async (_u: unknown, i?: RequestInit) => { sent = i; return new Response('{}') }) as typeof fetch)
  assert.deepEqual(sent?.headers, { Authorization: 'Bearer o_x' })
})


const CFG = { supabase_url: 'https://sb.example', anon_key: 'anon' }
const fake = (routes: Record<string, (body: any, init: RequestInit) => [number, unknown]>, seen: [string, RequestInit][] = []) =>
  (async (url: string, init: RequestInit = {}) => {
    seen.push([url, init])
    const key = Object.keys(routes).find((k) => url.endsWith(k))
    if (!key) return new Response('{}', { status: 404 })
    const [status, body] = routes[key](init.body ? JSON.parse(String(init.body)) : null, init)
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch

test('signing in with Supabase Auth: the code is sent, then verified into a session kept on this phone', async () => {
  const seen: [string, RequestInit][] = []
  const f = fake({ '/v1/config': () => [200, CFG], '/auth/v1/otp': () => [200, {}],
                   '/auth/v1/verify': (b) => b.token === '482913' ? [200, { access_token: 'a1', refresh_token: 'r1', expires_at: 2_000_000_000 }]
                                                                  : [403, { msg: 'Token has expired or is invalid' }] }, seen)
  const cfg = await sendCode('https://cloud.example', 'alex@example.net', f)
  assert.deepEqual(JSON.parse(String(seen[1][1].body)), { email: 'alex@example.net', create_user: true })
  await assert.rejects(verifyCode('https://cloud.example', cfg, 'alex@example.net', '000000', f),
                       { message: "That code isn't right, or it has run out. Ask for a new one." })
  const o = await verifyCode('https://cloud.example', cfg, 'alex@example.net', '482 913', f)
  assert.deepEqual(o, { api: 'https://cloud.example', email: 'alex@example.net', access: 'a1', refresh: 'r1', until: 2_000_000_000, supabase: CFG })
  const box = new Map<string, string>()
  const store = { getItem: (k: string) => box.get(k) ?? null, setItem: (k: string, v: string) => void box.set(k, v), removeItem: (k: string) => void box.delete(k) }
  saveOwner(store, o)
  assert.deepEqual(loadOwner(store), o)
})

test("a session about to run out is refreshed first; one Supabase has ended means signing in again", async () => {
  const o: Owner = { api: 'https://cloud.example', email: 'alex@example.net', access: 'a1', refresh: 'r1', until: 1000, supabase: CFG }
  let kept: Owner | null | undefined
  const keep = (x: Owner | null) => { kept = x }
  assert.equal(await ownerToken({ ...o, until: 5000 }, keep, 1000), 'a1')
  const ok = fake({ '/auth/v1/token?grant_type=refresh_token': () => [200, { access_token: 'a2', refresh_token: 'r2', expires_in: 3600 }] })
  assert.equal(await ownerToken(o, keep, 990, ok), 'a2')
  assert.equal(kept?.refresh, 'r2')
  const gone = fake({ '/auth/v1/token?grant_type=refresh_token': () => [400, { msg: 'Invalid Refresh Token' }] })
  assert.equal(await ownerToken(o, keep, 990, gone), null)
  assert.equal(kept, null)
  assert.equal(await ownerToken({ api: 'x', email: 'e', token: 'o_old' }, keep), 'o_old')
})

test("an owner's call carries the token and this phone's name", async () => {
  const seen: [string, RequestInit][] = []
  const f = fake({ '/v1/asks': () => [200, { asks: [] }] }, seen)
  const o: Owner = { api: 'https://cloud.example', email: 'alex@example.net', access: 'a1', refresh: 'r1', until: 4_000_000_000, supabase: CFG }
  assert.deepEqual(await ownerCall(o, () => {}, "Alex's iPhone", 'GET', '/v1/asks', undefined, f), { asks: [] })
  assert.deepEqual(seen[0][1].headers, { Authorization: 'Bearer a1', 'X-Bench-Device': "Alex's iPhone" })
})
