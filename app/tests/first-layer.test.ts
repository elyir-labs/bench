// Pins "First layer: squish more, squish less" chosen on 3 October 2026 (design/first-layer/, B "a first-layer
// sheet"). The boards there are the spec; if one of these fails, the sheet has drifted from them. The engine
// side (when it's offered, what's saved) is pinned by printer/tests/test_first_layer.py.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { BEADS, BEAD_VIEWBOX, SHEET_TITLE, WHERE_KEPT, beadShapes, canPress, checkShown, keptLine, sheetChoice, sheetLine, sheetNote, sheetSub } from '../src/intent/firstLayer.ts'
import type { Intent, IntentFirstLayer } from '../src/intent/types.ts'

const act = (id: string, label: string) => ({ id, label, primary: false, style: 'default' as const })
const amount = (z: number, words: string, mm: string) => ({ z, words, mm })
const fl = (over: Partial<IntentFirstLayer> = {}): IntentFirstLayer => ({
  can_keep: true,
  adjust: { total: 0.3, words: 'A little further', mm: '+0.300 mm', moved: 0.3, actions: [act('squish_less', 'Further'), act('squish_more', 'Closer')] },
  keep: null, kept: null, ask: null, ...over,
})
const intent = (state: string, first_layer: IntentFirstLayer | null) => ({ state, first_layer } as unknown as Intent)
const everywhere = () => true
const away = (id: string) => ['pause', 'resume', 'cancel'].includes(id)

test('the sheet asks how the first line looks, with three drawings of a line seen end on', () => {
  assert.equal(SHEET_TITLE, 'How does the first line look?')
  assert.deepEqual(BEADS.map((b) => [b.title, b.note]), [
    ['Too far', 'Round, with gaps'], ['Right', 'Flat and joined'], ['Too close', 'Thin, see-through'],
  ])
  assert.equal(BEAD_VIEWBOX, '0 0 96 56')
  for (const b of BEADS) {
    const shapes = beadShapes(b.kind)
    assert.equal(shapes.length, 4, 'the bed and three lines')
    assert.equal(shapes[0].attrs.class, 'bed')
  }
  assert.deepEqual(beadShapes('far').slice(1).map((s) => s.tag), ['ellipse', 'ellipse', 'ellipse'])   // round, apart
  assert.deepEqual(beadShapes('right').slice(1).map((s) => [s.tag, s.attrs.width]), [['rect', 32], ['rect', 32], ['rect', 32]])   // flat, touching
  assert.ok(beadShapes('close').slice(1).every((s) => s.tag === 'path' && String(s.attrs.class).includes('thin')))
})

test('the panel says where to look; the phone has the camera for that', () => {
  assert.equal(sheetSub(true), "Look at the line going down now. Move it until it's flat and joined.")
  assert.equal(sheetSub(false), "Move it until it's flat and joined.")
})

test('Check the first layer shows only while printing on layers 1 to 3, and not from away', () => {
  assert.equal(checkShown(intent('printing', fl()), everywhere), true)
  assert.equal(checkShown(intent('printing', fl({ adjust: null })), everywhere), false)
  assert.equal(checkShown(intent('needs_you', fl()), everywhere), false)
  assert.equal(checkShown(intent('printing', fl()), away), false)   // home only (3 October 2026)
  assert.equal(checkShown(null, everywhere), false)
})

test('Further and Closer press only when offered and nothing else is running', () => {
  assert.equal(canPress(fl(), 'squish_less', null), true)
  assert.equal(canPress(fl(), 'squish_less', 'squish_less'), false)
  const atLimit = fl({ adjust: { total: 0.5, words: 'A lot further', mm: '+0.500 mm', moved: 0.5, actions: [act('squish_more', 'Closer')] } })
  assert.equal(canPress(atLimit, 'squish_less', null), false)
  assert.equal(canPress(atLimit, 'squish_more', null), true)
})

test('Care says what is kept, in words first, and when it is not used', () => {
  const kept = (z: number, words: string, mm: string, used = true, against: 'scan' | 'tap' = 'scan') =>
    fl({ kept: { ...amount(z, words, mm), against, used, at: '2026-10-01T09:00:00', back: amount(0, 'As the printer finds it', '0.000 mm'), actions: [act('first_layer_back', 'Back to how it was')] } })
  assert.equal(keptLine(kept(0.3, 'A little further', '+0.300 mm'), 'Workshop'), 'A little further (+0.300 mm), kept 1 October.')
  assert.equal(keptLine(kept(0, 'As the printer finds it', '0.000 mm'), 'Workshop'),
    "As Workshop finds it. Change it from Now while a print's first layers go down.")
  assert.equal(keptLine(kept(0.3, 'A little further', '+0.300 mm', false), 'Workshop'),
    'A little further (+0.300 mm), kept 1 October. Not used: it was kept before Workshop found its own first layer.')
  assert.equal(keptLine(fl({ can_keep: false }), 'Desk'), "This printer can't keep a first layer yet.")
})

test('a sheet says its value and when it was kept; Print names the sheet, or any other', () => {
  assert.equal(sheetLine({ words: 'A little closer', mm: '−0.050 mm', at: '2026-10-22T12:00:00Z' }), 'A little closer (−0.050 mm), kept 22 October.')
  assert.equal(sheetChoice('Textured PEI'), 'Textured PEI')
  assert.equal(sheetChoice(''), 'Another sheet')
  assert.equal(sheetNote({ name: 'Textured PEI', words: 'A little closer', mm: '−0.050 mm' }, ['Textured PEI']), 'A little closer (−0.050 mm). Same as last time.')
  assert.equal(sheetNote({ name: '', words: 'As the printer finds it', mm: '0.000 mm' }, ['Textured PEI']), 'As the printer finds it (0.000 mm): not Textured PEI.')
  assert.match(WHERE_KEPT, /Klipper's variables file\. printer\.cfg isn't changed\./)
})
