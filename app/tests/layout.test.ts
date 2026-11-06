// Pins the arrangements chosen on 1 October 2026 (design/responsive/, B "Now stays with you").
// The boards there are the spec; if one of these fails, the screens have drifted from them.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { layoutFor, panelFit, unitFor } from '../src/shell/layout.ts'

const off = (width: number, height: number) => layoutFor({ panel: false, width, height })

test('a printer panel left tall gets the phone layout (design/small-screens/, tall B)', () => {
  assert.equal(layoutFor({ panel: true, width: 480, height: 853 }), 'compact')   // 720x1280 at the kiosk's 1.5x
  assert.equal(layoutFor({ panel: true, width: 480, height: 800 }), 'compact')
  assert.equal(layoutFor({ panel: true, width: 1280, height: 720 }), 'panel')    // the same panel turned
})

test('taps are 9 mm whatever the panel, and a size nobody knows changes nothing', () => {
  const at = (inches: number | null) => panelFit({ inches, width: 800, height: 480 })
  assert.equal(at(null), null)
  assert.equal(at(7)?.tap, 48)
  assert.equal(at(5)?.tap, 67)
  assert.equal(at(3.5)?.tap, 95)
})

test('only a short landscape panel gets the rail, with its type grown', () => {
  const at = (inches: number, width = 800, height = 480) => panelFit({ inches, width, height })
  assert.deepEqual(at(3.5), { tap: 95, rail: true, unit: '1.40px' })
  assert.equal(at(4.3)?.rail, false)
  assert.equal(at(5)?.rail, false)
  assert.equal(at(7)?.rail, false)
  assert.equal(at(3.5, 480, 800)?.rail, false)                                  // tall: the phone layout instead
  assert.equal(at(3.5, 480, 320)?.unit, '0.86px')                               // the same size, fewer pixels
})

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
