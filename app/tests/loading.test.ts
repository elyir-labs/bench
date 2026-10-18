// While a page loads (design/loading/, B + A, picked 15 October 2026): last time's answer while it checks, for one week
// and one account; with nothing (or nothing recent) the page draws its shape instead.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WEEK, keep, recall } from '../src/remember.ts'

const NOW = new Date(2026, 9, 15, 21, 0).getTime()
function store() {
  const m = new Map<string, string>()
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), m }
}

test('last time\'s answer comes back for the same account', () => {
  const s = store()
  keep(s, 'k', 'sam@example.net', { plan: 'tester' }, NOW)
  assert.deepEqual(recall(s, 'k', 'sam@example.net', WEEK, NOW + 3600_000), { plan: 'tester' })
})

test('another account on the same phone never sees it', () => {
  const s = store()
  keep(s, 'k', 'sam@example.net', { plan: 'tester' }, NOW)
  assert.equal(recall(s, 'k', 'alex@example.net', WEEK, NOW), null)
})

test('older than a week: nothing, so the page draws its shape', () => {
  const s = store()
  keep(s, 'k', 'sam@example.net', { plan: 'tester' }, NOW)
  assert.notEqual(recall(s, 'k', 'sam@example.net', WEEK, NOW + WEEK - 1), null)
  assert.equal(recall(s, 'k', 'sam@example.net', WEEK, NOW + WEEK), null)
  assert.equal(recall(s, 'k', 'sam@example.net', WEEK, NOW - 60_000), null, 'a clock set back is not trusted either')
})

test('a first launch, a broken store, or forgetting it: nothing', () => {
  const s = store()
  assert.equal(recall(s, 'k', 'sam@example.net', WEEK, NOW), null)
  s.m.set('k', '{not json')
  assert.equal(recall(s, 'k', 'sam@example.net', WEEK, NOW), null)
  keep(s, 'k', 'sam@example.net', { plan: 'tester' }, NOW)
  keep(s, 'k', 'sam@example.net', null, NOW)
  assert.equal(recall(s, 'k', 'sam@example.net', WEEK, NOW), null)
  assert.equal(recall(null, 'k', 'sam@example.net', WEEK, NOW), null)
  assert.doesNotThrow(() => keep({ setItem: () => { throw new Error('full') }, removeItem: () => {} }, 'k', 'x', 1, NOW))
})
