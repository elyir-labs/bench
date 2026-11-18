// Pins the head-switch drawing beside a load (design/filament-units/, A): the board's A-load and A-grip.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { headSwitchesLook } from '../src/components/now/headSwitches.ts'

test('through the extruder: both switches lit, filament down to the hotend', () => {
  const v = headSwitchesLook({ extruder: true, hotend: true, failed: null, color: '#1C1C1E' })
  assert.deepEqual([v.extruder, v.hotend, v.reach], ['lit', 'lit', 'hotend'])
})

test('at the extruder: the first lit, the second dark', () => {
  const v = headSwitchesLook({ extruder: true, hotend: false, failed: null, color: null })
  assert.deepEqual([v.extruder, v.hotend, v.reach], ['lit', 'dark', 'extruder'])
})

test("the gears didn't take it: the hotend switch is red, whatever it reads", () => {
  const v = headSwitchesLook({ extruder: false, hotend: false, failed: 'hotend', color: null })
  assert.equal(v.hotend, 'bad')
  assert.match(v.label, /stopped at the gears/)
  assert.equal(headSwitchesLook({ extruder: true, hotend: true, failed: 'hotend', color: null }).hotend, 'bad')
})

test('the gears turn the way Klipper says the extruder is going, and stand still otherwise', () => {
  assert.equal(headSwitchesLook({ extruder: true, hotend: false, gears: 'in', failed: null, color: null }).gears, 'in')
  assert.equal(headSwitchesLook({ extruder: true, hotend: true, gears: 'out', failed: null, color: null }).gears, 'out')
  assert.equal(headSwitchesLook({ extruder: true, hotend: false, failed: null, color: null }).gears, null)
})

test('no hotend switch: the extruder switch alone, and the filament never drawn past it', () => {
  const v = headSwitchesLook({ extruder: true, hotend: null, hotend_switch: false, failed: null, color: null })
  assert.deepEqual([v.extruder, v.hotend, v.reach], ['lit', null, 'extruder'])
  assert.equal(v.label, 'Filament at the extruder')
})

test("a load that didn't reach the head: the extruder switch is red", () => {
  const v = headSwitchesLook({ extruder: false, hotend: null, hotend_switch: false, failed: 'extruder', color: null })
  assert.equal(v.extruder, 'bad')
  assert.match(v.label, /didn't reach the extruder/)
})
