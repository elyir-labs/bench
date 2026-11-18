import { test } from 'node:test'
import assert from 'node:assert/strict'
import { NEW_FOR_MS, isNew, toAdd, toDrop } from '../src/shell-app/joined.ts'

const now = Date.UTC(2026, 10, 7, 20)
const j = { id: 'p-newone12', name: 'Kobra 3 #3', addresses: { away: 'https://p-newone12.elyir.app', home: null }, at: now / 1000 - 60 }

test("a printer the box carried this phone to is added with the sibling's token", () => {
  assert.deepEqual(toAdd([j], 'tok', new Set(), new Set(), now), [{
    id: 'p-newone12', name: 'Kobra 3 #3', addresses: { away: 'https://p-newone12.elyir.app', home: null },
    token: 'tok', added: now, joined: now - 60_000,
  }])
})

test('once only: not when it is on the list, nor after it was taken off', () => {
  assert.deepEqual(toAdd([j], 'tok', new Set(['p-newone12']), new Set(), now), [])
  assert.deepEqual(toAdd([j], 'tok', new Set(), new Set(['p-newone12']), now), [])
  assert.deepEqual(toAdd(undefined, 'tok', new Set(), new Set(), now), [])
})

test('new for a day after it joined, and a box clock ahead of the phone never makes it newer than now', () => {
  assert.equal(isNew({ joined: now - 1 }, now), true)
  assert.equal(isNew({ joined: now - NEW_FOR_MS - 1 }, now), false)
  assert.equal(isNew({}, now), false)
  assert.equal(toAdd([{ ...j, at: now / 1000 + 3600 }], 't', new Set(), new Set(), now)[0].joined, now)
})

test('a printer the box took off the bench goes from the phones it was carried to, never one paired by hand', () => {
  const have = [
    { id: 'p-carried1', token: 'tok', joined: now },
    { id: 'p-byhand12', token: 'tok' },
    { id: 'p-otherbox', token: 'other', joined: now },
    { id: 'p-stays123', token: 'tok', joined: now },
  ]
  assert.deepEqual(toDrop(['p-carried1', 'p-byhand12', 'p-otherbox'], 'tok', have), ['p-carried1'])
  assert.deepEqual(toDrop(undefined, 'tok', have), [])
})
