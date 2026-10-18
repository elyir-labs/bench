// Pins the box's own rows at the foot of its Care (design/power/, A: Turn off with Restart; design/role/, B: the way
// back, Make it a printer). bench/box.py is the service side.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ROLE_ASK, ROLE_STEPS, powerAsk, powerGoing, roleSteps } from '../src/bench-app/box.ts'

test('turning the box off says the printers keep going, and where to switch it on', () => {
  assert.deepEqual(powerAsk('off', 'the Bench Box'), { title: 'Turn off the Bench Box?',
    line: 'Your printers keep going without it. It can only be switched on again at the box.', go: 'Turn off' })
  assert.equal(powerAsk('restart', 'the Bench Box').go, 'Restart')
  assert.equal(powerGoing('off', 'the Bench Box'), 'The Bench Box is turning off. When its screen goes dark, switch it off.')
  assert.equal(powerGoing('restart', 'the Bench Box'), 'The Bench Box is restarting. Back in about a minute.')
})

test("making it a printer asks once, then follows the installer's steps", () => {
  assert.equal(ROLE_ASK.go, 'Make it a printer')
  assert.deepEqual(ROLE_STEPS, ['Klipper and Moonraker on', 'The printer app', 'Its screen'])
  assert.deepEqual(roleSteps({ state: 'switching', progress: { step: 'The printer app', done: 1, of: 3 }, why: null }).map(s => s.status),
    ['ok', 'now', 'todo'])
  assert.deepEqual(roleSteps(null).map(s => s.status), ['now', 'todo', 'todo'])
})
