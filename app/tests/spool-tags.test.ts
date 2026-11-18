import { test } from 'node:test'
import assert from 'node:assert/strict'
import { chipLine, productName, quickChoices, readersLine, swatch, type TagChoice } from '../src/intent/tags.ts'

const slot = (n: number): TagChoice => ({ kind: 'slot', slot: n, label: `Slot ${n}`, color: 'FF0000', sub: '' })
const hist = (n: number): TagChoice => ({ kind: 'history', index: n, label: `Old ${n}`, color: '00FF00', sub: '' })

test('the quick answers are the slots first, then ones written before, three at most (design/spool-tags/)', () => {
  assert.deepEqual(quickChoices([hist(0), slot(1), slot(2)]).map((c) => c.label), ['Slot 1', 'Slot 2', 'Old 0'])
  assert.equal(quickChoices([slot(0), slot(1), slot(2), slot(3), hist(0)]).length, 3)
  assert.deepEqual(quickChoices(undefined), [])
})

test('a library row names its product line with the material once', () => {
  assert.equal(productName({ brand: 'Polymaker', material: 'PETG', line: 'PolyLite PETG' }), 'PolyLite PETG')
  assert.equal(productName({ brand: 'ELEGOO', material: 'PLA', line: 'Matte' }), 'Matte PLA')
  assert.equal(productName({ brand: 'ELEGOO', material: 'ASA', line: '' }), 'ELEGOO ASA')
})

test('the small lines: what is on the reader, who reads it, a safe swatch', () => {
  assert.equal(chipLine({ chip: 'NTAG213', blank: true, uid: '' }), 'Blank NTAG213')
  assert.equal(chipLine(null), 'Put the tag back on the reader')
  assert.equal(readersLine('Anycubic ACE', 'every ACE here reads it'), 'Anycubic ACE: every ACE here reads it.')
  assert.equal(swatch('f07a2b'), '#f07a2b')
  assert.equal(swatch('nope'), 'transparent')
})
