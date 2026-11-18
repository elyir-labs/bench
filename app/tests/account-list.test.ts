import { test } from 'node:test'
import assert from 'node:assert/strict'
import { follow, fromAccountWords, toJoin } from '../src/shell-app/account-list.ts'

const door = (printer: string) => ({ printer, name: printer, addresses: { home: null, away: `https://${printer}.elyir.app` } })
const dev = (id: string, printer: string | null, name = id) => ({ id, name, kind: 'printer', door: printer ? door(printer) : null })

test('a printer in the account that this phone lacks is let in; one it has is remembered as the account\'s', () => {
  const devices = [dev('p_1', 'p-aaaa1111'), dev('p_2', 'p-bbbb2222'), dev('p_3', null), { id: 'b_1', name: 'Box', kind: 'box', door: door('box') }]
  const f = follow(devices, 'h_1', [{ id: 'p-aaaa1111', name: 'Workshop' }])
  assert.deepEqual(f.letIn.map((d) => d.id), ['p_2'])
  assert.deepEqual(f.link, [{ id: 'p-aaaa1111', device: 'p_1' }])
  assert.deepEqual(f.drop, [])
  const settled = follow(devices, 'h_1', [{ id: 'p-aaaa1111', name: 'Workshop', account: 'p_1', house: 'h_1' },
    { id: 'p-bbbb2222', name: 'Studio', account: 'p_2', house: 'h_1' }])
  assert.deepEqual(settled, { letIn: [], link: [], drop: [] })
})

test('a printer that took this phone off is let in again', () => {
  const f = follow([dev('p_1', 'p-aaaa1111')], 'h_1', [{ id: 'p-aaaa1111', name: 'Workshop', account: 'p_1', house: 'h_1', reach: 'unpaired' }])
  assert.deepEqual(f.letIn.map((d) => d.id), ['p_1'])
})

test('gone from the account, gone from this phone: only what that account put here', () => {
  const have = [
    { id: 'p-aaaa1111', name: 'Workshop', account: 'p_1', house: 'h_1' },
    { id: 'p-gone0000', name: 'Old', account: 'p_9', house: 'h_1' },
    { id: 'p-hand0000', name: 'Paired by hand' },
    { id: 'p-other000', name: "A friend's", account: 'p_7', house: 'h_2' },
    { id: 'box', name: 'Bench Box', kind: 'bench' as const, account: 'p_9', house: 'h_1' },
  ]
  assert.deepEqual(follow([dev('p_1', 'p-aaaa1111')], 'h_1', have).drop, ['p-gone0000'])
  assert.deepEqual(follow([], 'h_3', have).drop, [], 'another account empties nothing')
})

test('what the account lacks: by its door, or by name before its door has reported', () => {
  const have = [{ id: 'p-aaaa1111', name: 'Workshop' }, { id: 'p-bbbb2222', name: 'Studio' }, { id: 'p-cccc3333', name: 'Desk' },
    { id: 'box', name: 'Bench Box', kind: 'bench' as const }]
  assert.deepEqual(toJoin([dev('p_1', 'p-aaaa1111'), dev('p_2', null, 'Studio')], have).map((p) => p.id), ['p-cccc3333'])
})

test('the line under the list', () => {
  assert.equal(fromAccountWords(7, 0), 'From your account · 7 printers')
  assert.equal(fromAccountWords(1, 6), "6 more join your account the next time this phone is home with them.")
  assert.equal(fromAccountWords(1, 1), "1 more joins your account the next time this phone is home with it.")
  assert.equal(fromAccountWords(0, 0), null)
})
