// Pins the box's own rows at the foot of its Care (design/power/, A: Turn off with Restart; design/role/, B: the way
// back, Make it a printer). bench/box.py is the service side.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ROLE_ASK, ROLE_STEPS, osRow, powerAsk, powerGoing, roleSteps, sshRow } from '../src/bench-app/box.ts'

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

test('the update row says what it runs and offers Update now only when there is newer', () => {
  assert.deepEqual(osRow({ version: '2026.10.21-a', latest: '2026.10.22-b', update: null }),
    { title: 'Updates', line: '2026.10.22-b is out. This box runs 2026.10.21-a.', newer: true })
  assert.equal(osRow({ version: '2026.10.22-b', latest: '2026.10.22-b', update: null }).newer, false)
  assert.equal(osRow({ version: '2026.10.22-b', latest: null, update: null }).line,
    'It runs 2026.10.22-b, and looks for a new one by itself at night.')
})

test('the SSH row says who the keys sign in as, and that there is no password without one', () => {
  assert.equal(sshRow('pi', []).line, "Add your public key to sign in as pi from a computer on your Wi-Fi. There's no password.")
  assert.equal(sshRow('pi', [{ id: 'a', kind: 'ssh-ed25519', name: 'laptop' }]).line, 'This key signs in as pi, from a computer on your Wi-Fi.')
  assert.match(sshRow('pi', [{ id: 'a', kind: 'k', name: '' }, { id: 'b', kind: 'k', name: '' }]).line, /^These 2 keys sign in as pi/)
})
