import { test } from 'node:test'
import assert from 'node:assert/strict'
import { lightPlace } from '../src/intent/light.ts'

test('the light switch sits on the camera, else in the top bar (design/chamber-light/, A)', () => {
  assert.equal(lightPlace({ light: true, cameraOnNow: true, embedded: false }), 'camera')
  assert.equal(lightPlace({ light: true, cameraOnNow: true, embedded: true }), 'camera')
  assert.equal(lightPlace({ light: true, cameraOnNow: false, embedded: false }), 'top')
  assert.equal(lightPlace({ light: true, cameraOnNow: false, embedded: true }), 'now')
  assert.equal(lightPlace({ light: false, cameraOnNow: true, embedded: false }), null)
})
