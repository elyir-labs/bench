// Pins the arrangements chosen on 1 October 2026 (design/responsive/, B "Now stays with you").
// The boards there are the spec; if one of these fails, the screens have drifted from them.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layoutFor, unitFor } from '../src/shell/layout.ts'

const off = (width: number, height: number) => layoutFor({ panel: false, width, height })

test('the printer panel keeps its own layout whatever its size', () => {
  assert.equal(layoutFor({ panel: true, width: 800, height: 480 }), 'panel')
  assert.equal(layoutFor({ panel: true, width: 1280, height: 800 }), 'panel')
  assert.equal(unitFor('panel'), null)   // --u still grows with the panel
})

test('phones get tabs and the Now bar', () => {
  assert.equal(off(390, 844), 'compact')
  assert.equal(off(430, 932), 'compact')
  assert.equal(off(599, 900), 'compact')
})

test('tablets held upright get the Now card over the other tabs', () => {
  assert.equal(off(820, 1180), 'stacked')
  assert.equal(off(768, 1024), 'stacked')
})

test('tablets on their side and laptops get the Now column beside the other tabs', () => {
  assert.equal(off(1180, 820), 'split')
  assert.equal(off(1440, 900), 'split')
  assert.equal(off(900, 700), 'split')
  assert.equal(off(1366, 1024), 'split')
})

test('off the panel the type scale is fixed, not grown with the window', () => {
  for (const l of ['compact', 'stacked', 'split'] as const) assert.match(unitFor(l) ?? '', /^\d+(\.\d+)?px$/)
})

test('inside a Bench Box a printer is laid out as on its own panel, at the box\'s size (design/bench-box/, D)', () => {
  assert.equal(layoutFor({ panel: false, bench: true, width: 1280, height: 676 }), 'panel')   // the box draws the sections
  assert.equal(layoutFor({ panel: false, bench: true, width: 390, height: 760 }), 'compact')   // a phone opening the box
  assert.equal(layoutFor({ panel: false, width: 1280, height: 676 }), 'split')                // the Printers app, as before
})
