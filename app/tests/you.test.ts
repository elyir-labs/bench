// The Elyir account in the Printers app (design/one-cloud/, A, picked 15 October 2026): the plan, each printer from away
// and its backup, the phones and computers signed in.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { GETS, deviceLine, planOf, initial, notInLine, phoneLine, phoneName, planLine, type CloudDevice, type Plan } from '../src/shell-app/you.ts'

const NOW = new Date(2026, 9, 15, 9, 30).getTime()
const at = (d: Date) => d.getTime() / 1000
const TESTER: Plan = { name: 'tester', on: true, away: true, backups: true }
const NONE: Plan = { name: 'none', on: false, away: false, backups: false }
const Workshop: CloudDevice = { id: 'p_1', name: 'Workshop', kind: 'printer', backup: { id: 'b_1', at: at(new Date(2026, 9, 15, 2, 10)), size: 1300 } }

test('the plan in one line', () => {
  assert.equal(planLine(TESTER), 'Tester · free, by invite')
  assert.equal(planLine({ ...TESTER, name: 'yearly' }), 'Yearly · $50')
  assert.equal(planLine({ ...TESTER, name: 'monthly' }), 'Monthly · $5')
  assert.equal(planLine(NONE), 'Off')
  assert.deepEqual(planOf('tester'), TESTER)
  assert.deepEqual(planOf(null), NONE)
})

test('each printer: from away, and its last backup', () => {
  assert.equal(deviceLine(Workshop, TESTER, NOW), 'From away ✓ · backed up last night at 2:10 am')
  assert.equal(deviceLine({ ...Workshop, backup: null }, TESTER, NOW), 'From away ✓ · first backup tonight')
  assert.equal(deviceLine({ ...Workshop, kind: 'box', name: 'box' }, TESTER, NOW), 'From away ✓')
  assert.equal(deviceLine(Workshop, NONE, NOW), 'At home only')
  assert.equal(notInLine(true), 'Not in Bench Cloud yet.')
  assert.equal(notInLine(false), 'Not in Bench Cloud yet. Add it from home.')
})

test('phones and computers, named from their browser', () => {
  assert.equal(phoneName('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'), 'iPhone')
  assert.equal(phoneName('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit'), 'Mac')
  assert.equal(phoneName('Mozilla/5.0 (Linux; Android 15; Pixel 8) Mobile Safari'), 'Android phone')
  assert.equal(phoneName('Mozilla/5.0 (Windows NT 10.0; Win64; x64)'), 'Windows computer')
  assert.equal(phoneName(''), 'A phone or computer')
  assert.equal(phoneLine({ id: 's', agent: '', seen: NOW / 1000, you: true }, NOW), 'This one · now')
  assert.equal(phoneLine({ id: 's', agent: '', seen: NOW / 1000 - 600, you: false }, NOW), 'Last used 10 minutes ago')
})

test('what Bench Cloud does, and only promises what is built', () => {
  assert.deepEqual(GETS.map((g) => g.title), ['See and stop them from anywhere', 'A backup every night', 'A new phone already knows them'])
  assert.match(GETS[2].line, /^Coming soon/)
  assert.equal(initial('sam@example.net'), 'S')
  assert.equal(initial(undefined), '')
})

test('away without a plan that carries them: "At home only", not "Out of reach"', async () => {
  const { statusOf } = await import('../src/shell-app/status.ts')
  const { homeOnly } = await import('../src/shell-app/you.ts')
  const p = { reach: 'offline' } as Parameters<typeof statusOf>[0]
  assert.deepEqual(statusOf(p, true), { word: 'At home only', tone: 'off', line: "Can't see it from here" })
  assert.equal(statusOf(p).word, 'Out of reach')
  assert.equal(homeOnly(null), false)
  assert.equal(homeOnly(null, true), true)
  assert.equal(homeOnly({ plan: TESTER } as never), false)
  assert.equal(homeOnly({ plan: NONE } as never), true)
})

test('a paid plan: which one, and when it renews or ends', async () => {
  const { dateWords, priceOpen, turnOnLabel } = await import('../src/shell-app/you.ts')
  const until = new Date(2027, 9, 14, 12).getTime() / 1000
  const yearly = { name: 'yearly', on: true, away: true, backups: true, until, cancels: false, manage: true }
  assert.equal(dateWords(until), 'October 14, 2027')
  assert.equal(planLine(yearly), 'Yearly · $50 · renews October 14, 2027')
  assert.equal(planLine({ ...yearly, name: 'monthly', cancels: true }), 'Monthly · $5 · ends October 14, 2027')
  assert.equal(planLine({ ...yearly, on: false }), "Off · the last payment didn't go through")
  assert.equal(turnOnLabel('yearly'), 'Turn on · $50 a year')
  assert.equal(turnOnLabel('monthly'), 'Turn on · $5 a month')
  // once paying is open the words are Stripe's prices, whatever they are then
  const pay = { prices: { monthly: '$6 a month', yearly: '$45 a year' }, amounts: { monthly: '$6', yearly: '$45' } }
  assert.equal(turnOnLabel('yearly', pay), 'Turn on · $45 a year')
  assert.equal(planLine(yearly, pay), 'Yearly · $45 · renews October 14, 2027')
  assert.equal(priceOpen(pay), 'Monthly $6 or yearly $45. Stop any time.')
})

test('the plan says how many printers it covers, and above it Workshop is coming soon', async () => {
  const { planTitle, sizeLine, isOver, workshopLine } = await import('../src/shell-app/you.ts')
  const home: Plan = { ...TESTER, name: 'yearly', covers: 5 }
  const me = (printers: number, plan = home) => ({ plan, printers, you: { email: 'a@b.c' }, owners: [], devices: [] })
  assert.equal(planTitle(home), 'Bench Cloud Home')
  assert.equal(planTitle(TESTER), 'Bench Cloud')
  assert.equal(sizeLine(me(4)), '4 of 5 printers')
  assert.equal(isOver(me(5)), false)
  assert.equal(sizeLine(me(7)), '7 printers · Home covers 5')
  assert.equal(isOver(me(7)), true)
  assert.equal(sizeLine(me(9, TESTER)), null)   // testers have no size
  assert.equal(workshopLine(7, 5), 'For more than 5 printers: orders into the queue, cost per print, several people at once. Until then all 7 keep working on Home.')
})

test('owners: add another by email, take one off with a plain question', async () => {
  const { removeOwnerAsk, ownerLine } = await import('../src/shell-app/you.ts')
  assert.equal(removeOwnerAsk('jo@example.net'), "Take jo@example.net off as an owner? They'll no longer see the printers' backups or plan. We'll email them to say so.")
  assert.equal(ownerLine(false, 2), 'Can get a backup back, and sign in anywhere')
})
