// Scanning the printer's code in the Printers app (design/scan/, 2 October 2026).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parsePairingQr, startScan, openCamera, addressOf, shortName, NOT_A_PRINTER, type CameraStream } from '../src/shell-app/scan.ts'

const SHELL_URL = 'https://printers.elyir.app/add#p=workshop.elyir.app&c=ABCD2345'   // what the door's pair/new returns
const OLD_URL = 'https://workshop.elyir.app/pair#ABCD2345'
const refused = { ok: false, message: NOT_A_PRINTER }

// ---------- what a code may say ----------

test("the panel's code: the Printers app's add page with the printer and the code", () => {
  assert.deepEqual(parsePairingQr(SHELL_URL), { ok: true, address: 'workshop.elyir.app', code: 'ABCD2345' })
  // a code typed with its dash, lower case, a trailing slash: the same code
  assert.deepEqual(parsePairingQr('https://printers.elyir.app/add/#p=Studio.elyir.app&c=abcd-2345'), { ok: true, address: 'studio.elyir.app', code: 'ABCD2345' })
  assert.deepEqual(parsePairingQr('  https://printers.elyir.app/add#c=ABCD2345&p=workshop.elyir.app\n'), { ok: true, address: 'workshop.elyir.app', code: 'ABCD2345' })
})

test("the older code: the printer's own pairing page", () => {
  assert.deepEqual(parsePairingQr(OLD_URL), { ok: true, address: 'workshop.elyir.app', code: 'ABCD2345' })
  assert.deepEqual(parsePairingQr('https://desk.elyir.app/pair#abcd-2345'), { ok: true, address: 'desk.elyir.app', code: 'ABCD2345' })
})

test('a printer outside elyir.app is refused, whichever form names it', () => {
  for (const t of [
    'https://printers.elyir.app/add#p=evil.example.net&c=ABCD2345',
    'https://printers.elyir.app/add#p=workshop.elyir.app.evil.com&c=ABCD2345',
    'https://printers.elyir.app/add#p=elyir.app&c=ABCD2345',
    'https://printers.elyir.app/add#p=workshop.notelyir.app&c=ABCD2345',
    'https://printers.elyir.app/add#p=http://workshop.elyir.app&c=ABCD2345',   // not https
    'https://printers.elyir.app/add#p=workshop.elyir.app:8443&c=ABCD2345',
    'https://printers.elyir.app/add#p=printers.elyir.app&c=ABCD2345',      // the app isn't a printer
    'https://printers.elyir.app/add#p=workshop&c=ABCD2345',                    // a bare name: not what a panel shows
    'https://evil.example.net/add#p=workshop.elyir.app&c=ABCD2345',           // an add page that isn't the app's
    'https://printers.elyir.app.evil.com/add#p=workshop.elyir.app&c=ABCD2345',
    'https://evil.example.net/pair#ABCD2345',
    'http://workshop.elyir.app/pair#ABCD2345',
    'https://user:pw@workshop.elyir.app/pair#ABCD2345',
  ]) assert.deepEqual(parsePairingQr(t), refused, t)
})

test('localhost only for the development rig', () => {
  assert.deepEqual(parsePairingQr('https://printers.elyir.app/add#p=localhost:8089&c=ABCD2345'), refused)
  assert.deepEqual(parsePairingQr('https://printers.elyir.app/add#p=localhost:8089&c=ABCD2345', { allowLocal: true }),
    { ok: true, address: 'http://localhost:8089', code: 'ABCD2345' })
  assert.deepEqual(parsePairingQr('http://localhost:5173/add#p=http://127.0.0.1:8089&c=ABCD2345', { allowLocal: true }),
    { ok: true, address: 'http://127.0.0.1:8089', code: 'ABCD2345' })
  assert.deepEqual(parsePairingQr('http://localhost:8089/pair#ABCD2345', { allowLocal: true }),
    { ok: true, address: 'http://localhost:8089', code: 'ABCD2345' })
  assert.deepEqual(parsePairingQr('http://localhost:8089/pair#ABCD2345'), refused)
})

test('garbage, other links and broken codes are refused', () => {
  for (const t of [
    '', 'hello', 'ABCD2345', 'WIFI:S:home;T:WPA;P:secret;;', 'https://elyir.app', 'https://workshop.elyir.app/',
    'https://printers.elyir.app/', 'https://printers.elyir.app/add', 'https://printers.elyir.app/add#p=workshop.elyir.app',
    'https://printers.elyir.app/add#p=workshop.elyir.app&c=ABC', 'https://printers.elyir.app/add#p=workshop.elyir.app&c=ABCD23456',
    'https://workshop.elyir.app/pair', 'https://workshop.elyir.app/pair#', 'https://workshop.elyir.app/pair#ABCD%2', 'javascript:alert(1)',
  ]) assert.deepEqual(parsePairingQr(t), refused, t)
  assert.deepEqual(parsePairingQr(undefined as unknown as string), refused)
})

test('the address it gives is one the Have-a-code box and the pairing already take', () => {
  assert.equal(addressOf('workshop.elyir.app'), 'https://workshop.elyir.app')
  assert.equal(addressOf('http://localhost:8089'), 'http://localhost:8089')
  assert.equal(addressOf('workshop'), 'https://workshop.elyir.app')
  assert.equal(shortName('workshop.elyir.app'), 'workshop')
  assert.equal(shortName('http://localhost:8089'), 'localhost')
})

// ---------- the camera -> decode -> pair hand-off ----------

function fakeCamera(opts: { fail?: string; slow?: Promise<void> } = {}) {
  const tracks = [{ stopped: 0, stop() { this.stopped++ } }]
  const calls: unknown[] = []
  const media = {
    async getUserMedia(c: unknown): Promise<CameraStream> {
      calls.push(c)
      if (opts.slow) await opts.slow
      if (opts.fail) throw Object.assign(new Error(opts.fail), { name: opts.fail })
      return { getTracks: () => tracks }
    },
  }
  return { media, tracks, calls, off: () => tracks.every((t) => t.stopped > 0) }
}

/** A decoder that reads these, one per frame, then nothing. */
const frames = (...xs: (string | null)[]) => async () => (xs.length ? xs.shift()! : null)
const noWait = () => Promise.resolve()

test("a printer's code: the camera goes off, then it pairs with that printer and code", async () => {
  const cam = fakeCamera()
  const log: string[] = []
  let attached: CameraStream | null = null
  const s = startScan({
    media: cam.media, wait: noWait,
    attach: (st) => { attached = st },
    decode: frames(null, null, SHELL_URL),
    found: (address, code) => { log.push(`pair ${address} ${code} camera ${cam.off() ? 'off' : 'on'}`) },
    trouble: (t) => log.push('trouble ' + t),
    refused: (m) => log.push('refused ' + m),
  })
  await s.done
  assert.ok(attached)
  assert.deepEqual(log, ['pair workshop.elyir.app ABCD2345 camera off'])
  assert.deepEqual(cam.calls, [{ video: { facingMode: { ideal: 'environment' } }, audio: false }])   // the back camera, no microphone
})

test("someone else's code is said once, and scanning goes on to the printer's", async () => {
  const cam = fakeCamera()
  const log: string[] = []
  await startScan({
    media: cam.media, wait: noWait, attach: () => {},
    decode: frames('https://example.net/menu', 'https://example.net/menu', null, OLD_URL),
    found: (a, c) => { log.push(`pair ${a} ${c}`) },
    trouble: (t) => log.push('trouble ' + t),
    refused: (m) => log.push('refused ' + m),
  }).done
  assert.deepEqual(log, ['refused ' + NOT_A_PRINTER, 'pair workshop.elyir.app ABCD2345'])
  assert.ok(cam.off())
})

test('a camera that is turned down or missing says which, and nothing is paired', async () => {
  for (const [fail, want] of [['NotAllowedError', 'denied'], ['NotFoundError', 'unavailable'], ['NotReadableError', 'unavailable']] as const) {
    const cam = fakeCamera({ fail })
    const log: string[] = []
    await startScan({
      media: cam.media, wait: noWait, attach: () => { log.push('attach') }, decode: frames(SHELL_URL),
      found: () => { log.push('pair') }, trouble: (t) => log.push(t), refused: () => log.push('refused'),
    }).done
    assert.deepEqual(log, [want], fail)
  }
  assert.deepEqual(await openCamera(undefined), { trouble: 'unavailable' })   // no camera API at all (plain http, old browser)
})

test('Cancel while the permission prompt is up: the camera is turned off as soon as it arrives', async () => {
  let allow!: () => void
  const cam = fakeCamera({ slow: new Promise<void>((r) => { allow = r }) })
  const log: string[] = []
  const s = startScan({
    media: cam.media, wait: noWait, attach: () => { log.push('attach') }, decode: frames(SHELL_URL),
    found: () => { log.push('pair') }, trouble: (t) => log.push(t), refused: () => log.push('refused'),
  })
  assert.equal(cam.calls.length, 1)   // asked straight away, inside the tap
  s.stop()
  allow()
  await s.done
  assert.deepEqual(log, [])
  assert.ok(cam.off())
})

test('Cancel while scanning stops the camera and the frames', async () => {
  const cam = fakeCamera()
  let reads = 0
  let s!: ReturnType<typeof startScan>
  s = startScan({
    media: cam.media, wait: noWait, attach: () => {},
    decode: async () => { if (++reads === 3) s.stop(); return null },
    found: () => assert.fail('nothing to pair'), trouble: () => assert.fail('no trouble'), refused: () => {},
  })
  await s.done
  assert.equal(reads, 3)
  assert.ok(cam.off())
})

test('a decoder that throws on a frame is a frame without a code', async () => {
  const cam = fakeCamera()
  let n = 0
  const got: string[] = []
  await startScan({
    media: cam.media, wait: noWait, attach: () => { throw new Error('play() refused') },
    decode: async () => { if (++n < 3) throw new Error('bad frame'); return SHELL_URL },
    found: (a) => { got.push(a) }, trouble: () => {}, refused: () => {},
  }).done
  assert.deepEqual(got, ['workshop.elyir.app'])
})
