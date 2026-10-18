// A new printer's first Wi-Fi on its panel (design/setup/, direction C, picked 4 October 2026).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { OFF, screenFor, stepOf, bars, hostnameFor, passwordProblem, wrongWords, homeAddress, type WifiState, type Here } from '../src/setup/wifi.ts'

const S = (o: Partial<WifiState>): WifiState => ({ ...OFF, host: 'raspberrypi', port: '8088', ...o })
const start: Here = { at: 'start' }, list: Here = { at: 'list' }
const typePw: Here = { at: 'type', what: 'password', ssid: 'Hartley Home' }, typeName: Here = { at: 'type', what: 'name' }

test('first boot: both ways side by side, then the list or the keyboard only when asked', () => {
  assert.equal(screenFor(S({ mode: 'looking' }), start), 'looking')
  assert.equal(screenFor(S({ mode: 'open' }), start), 'start')
  assert.equal(screenFor(S({ mode: 'open' }), list), 'list')
  assert.equal(screenFor(S({ mode: 'open' }), typePw), 'keyboard')
})

test("a phone that sends the password moves the panel on too: it asks the name while it joins", () => {
  assert.equal(screenFor(S({ mode: 'joining', ssid: 'Hartley Home' }), start), 'name')
  assert.equal(screenFor(S({ mode: 'joining', ssid: 'Hartley Home' }), typePw), 'name')
  assert.equal(screenFor(S({ mode: 'joining' }), typeName), 'keyboard')
})

test('a wrong password shows the same Wi-Fi code again, unless the person is typing here', () => {
  assert.equal(screenFor(S({ mode: 'failed', reason: 'password' }), start), 'wrong')
  assert.equal(screenFor(S({ mode: 'failed', reason: 'password' }), typePw), 'keyboard')
  assert.equal(screenFor(S({ mode: 'failed' }), list), 'list')
})

test('connected: the phone code once it has a name, the name first if it has none', () => {
  assert.equal(screenFor(S({ mode: 'connected', name: null }), start), 'name')
  assert.equal(screenFor(S({ mode: 'connected', name: 'Workshop' }), start), 'done')
  assert.equal(screenFor(S({ mode: 'connected', name: 'Workshop' }), typeName), 'keyboard')
})

test('the step bar: Wi-Fi, then Name, then Phone', () => {
  assert.equal(stepOf('start', start), 0)
  assert.equal(stepOf('keyboard', typePw), 0)
  assert.equal(stepOf('wrong', start), 0)
  assert.equal(stepOf('name', start), 1)
  assert.equal(stepOf('keyboard', typeName), 1)
  assert.equal(stepOf('done', start), 2)
})

test('signal in three bars, the way the phone page draws them', () => {
  assert.deepEqual([bars(90), bars(67), bars(66), bars(34), bars(33), bars(0)], [3, 3, 2, 2, 1, 1])
})

test("names become the printer's name on the network the way the installer makes them", () => {
  assert.equal(hostnameFor('Workshop'), 'workshop')
  assert.equal(hostnameFor("Mia's Desk"), 'mia-s-desk')
  assert.equal(hostnameFor('  '), 'printer')
})

test('the keyboard refuses a password Wi-Fi never accepts, before the setup Wi-Fi closes', () => {
  assert.equal(passwordProblem('1234567', 'wpa'), 'Wi-Fi passwords are 8 to 63 characters.')
  assert.equal(passwordProblem('12345678', 'wpa'), null)
  assert.equal(passwordProblem('', 'open'), null)
  assert.equal(passwordProblem('ab'.repeat(32), 'wpa'), null)
})

test('what went wrong, in words', () => {
  assert.match(wrongWords(S({ ssid: 'Hartley Home', reason: 'password' })).headline, /^Hartley Home didn't take that password\.$/)
  assert.match(wrongWords(S({ ssid: 'Hartley Home', reason: 'not_found' })).headline, /can't hear Hartley Home/)
  assert.match(wrongWords(S({ ssid: 'Hartley Home', reason: 'timeout' })).headline, /didn't answer/)
})

test("without a door, the phone code is the printer's own address at home", () => {
  assert.equal(homeAddress(S({ host: 'workshop', port: '8088' })), 'http://workshop.local:8088/')
  assert.equal(homeAddress(S({ host: 'workshop.lan', port: '80' })), 'http://workshop.local/')
})
