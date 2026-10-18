// Scanning the printer's code from inside the Printers app (design/scan/, 2 October 2026).
//
// On an iPhone the Camera app opens a scanned code in Safari, whose storage isn't the Home Screen
// app's, so the app itself never gets paired. Scanning here pairs this app with the code, at home
// or away (POST /door/pair is open on both names).
//
// No Vue and no DOM in here, so the rules run under `npm test`: what a code may say, and the
// camera -> decode -> pair hand-off with the camera and the decoder passed in.

/** The Printers app's own names: a code that opens Add has to come from one of them. */
const SHELL_HOST = 'printers.elyir.app'
const LOCAL = /^(localhost|127\.0\.0\.1)(:\d{1,5})?$/

export const NOT_A_PRINTER = "That code isn't from a printer. Scan the one on the printer's screen."

/** "workshop", "workshop.elyir.app" or a full address: the printer's public name, as a URL. */
export function addressOf(text: string): string {
  const t = text.trim().replace(/\/+$/, '')
  if (/^https?:\/\//i.test(t)) return t
  return 'https://' + (t.includes('.') ? t : `${t.toLowerCase()}.elyir.app`)
}

/** A printer's short name for a sentence: "workshop.elyir.app" -> "workshop". */
export function shortName(p: string): string {
  try {
    return new URL(addressOf(p)).hostname.split('.')[0] || p
  } catch {
    return p.split('.')[0]
  }
}

export type Scanned =
  | { ok: true; address: string; code: string }   // address as the Have-a-code box takes it
  | { ok: false; message: string }

const refuse = (): Scanned => ({ ok: false, message: NOT_A_PRINTER })

/** A printer named in a code: a name under elyir.app, or (in development) a localhost door. */
function printerAddress(host: string, allowLocal: boolean, scheme?: string): string | null {
  const h = host.trim().toLowerCase()
  // a local test door is plain http unless the code said otherwise
  if (LOCAL.test(h)) return allowLocal ? `${scheme === 'https:' ? 'https' : 'http'}://${h}` : null
  if (scheme && scheme !== 'https:') return null
  const labels = h.split('.')
  if (labels.length < 3 || !h.endsWith('.elyir.app')) return null
  if (!labels.every((l) => /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(l))) return null
  if (h === SHELL_HOST) return null   // the Printers app isn't a printer
  return h
}

function cleanCode(c: string | null | undefined): string | null {
  const code = (c ?? '').replace(/[^a-z0-9]/gi, '').toUpperCase()
  return /^[A-Z0-9]{8}$/.test(code) ? code : null
}

/**
 * What the printer's QR holds, read as a printer and a code. Two forms:
 *   https://printers.elyir.app/add#p=workshop.elyir.app&c=ABCD2345   (the panel's shell_url)
 *   https://workshop.elyir.app/pair#ABCD2345                          (the older pairing page)
 * Anything else, or a printer not under elyir.app, is refused. allowLocal lets a localhost door
 * through, for the development rig only.
 */
export function parsePairingQr(text: string, opts: { allowLocal?: boolean } = {}): Scanned {
  const allowLocal = !!opts.allowLocal
  let u: URL
  try {
    u = new URL(String(text ?? '').trim())
  } catch {
    return refuse()
  }
  if (u.protocol !== 'https:' && !(allowLocal && u.protocol === 'http:')) return refuse()
  if (u.username || u.password) return refuse()
  const path = u.pathname.replace(/\/+$/, '')
  const fragment = u.hash.slice(1)

  if (path === '/add') {
    const fromShell = u.host === SHELL_HOST || (allowLocal && LOCAL.test(u.host))
    if (!fromShell) return refuse()
    const q = new URLSearchParams(fragment)
    const p = q.get('p') ?? ''
    // p is a bare name; a scheme is only accepted for a local door
    const m = /^(https?):\/\/([^/]+)\/?$/i.exec(p.trim())
    const address = m ? printerAddress(m[2], allowLocal, m[1].toLowerCase() + ':') : printerAddress(p, allowLocal)
    const code = cleanCode(q.get('c'))
    return address && code ? { ok: true, address, code } : refuse()
  }
  if (path === '/pair') {
    const address = printerAddress(u.host, allowLocal, u.protocol)
    let raw = fragment
    try { raw = decodeURIComponent(fragment) } catch { /* a broken escape: cleanCode refuses it */ }
    const code = cleanCode(raw)
    return address && code ? { ok: true, address, code } : refuse()
  }
  return refuse()
}

// ---------- the camera, the decoder and the hand-off ----------

export interface CameraTrack { stop(): void }
export interface CameraStream { getTracks(): CameraTrack[] }
export interface Media { getUserMedia(c: { video: unknown; audio: boolean }): Promise<CameraStream> }
export type CameraTrouble = 'denied' | 'unavailable'

/** The back camera, or why there isn't one. Called straight from the tap, so iOS counts it as one. */
export async function openCamera(media: Media | undefined): Promise<{ stream: CameraStream } | { trouble: CameraTrouble }> {
  if (!media || typeof media.getUserMedia !== 'function') return { trouble: 'unavailable' }   // no camera API, or not https
  try {
    return { stream: await media.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false }) }
  } catch (e) {
    const name = (e as { name?: string } | null)?.name
    // NotAllowedError: said no, now or before. NotFound/NotReadable/Overconstrained: none, or in use.
    return { trouble: name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable' }
  }
}

export interface ScanDeps {
  media: Media | undefined
  /** Show the stream (a <video>) and start it playing. */
  attach(stream: CameraStream): Promise<void> | void
  /** Read whatever code is in the current frame, or null. */
  decode(): Promise<string | null>
  /** A printer's code was read: the camera is already off. */
  found(address: string, code: string): Promise<void> | void
  trouble(t: CameraTrouble): void
  /** A code was read, but not a printer's; scanning goes on. */
  refused(message: string): void
  allowLocal?: boolean
  everyMs?: number
  wait?(ms: number): Promise<void>
}

export interface Scan {
  stop(): void
  readonly done: Promise<void>
}

/** Open the camera and read frames until a printer's code turns up or stop() is called. */
export function startScan(d: ScanDeps): Scan {
  let stopped = false
  let stream: CameraStream | null = null
  const off = () => {
    stream?.getTracks().forEach((t) => { try { t.stop() } catch { /* already ended */ } })
    stream = null
  }
  const wait = d.wait ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)))
  const every = d.everyMs ?? 200

  const done = (async () => {
    const opened = await openCamera(d.media)   // getUserMedia is called before the first await
    if ('trouble' in opened) {
      if (!stopped) d.trouble(opened.trouble)
      return
    }
    stream = opened.stream
    if (stopped) { off(); return }             // cancelled while the permission prompt was up
    try {
      await d.attach(stream)
    } catch {
      // play() refused (it can be, without a tap): the frames may still come; keep going
    }
    let lastRefused = ''
    while (!stopped) {
      let text: string | null = null
      try {
        text = await d.decode()
      } catch {
        text = null
      }
      if (stopped) break
      if (text) {
        const s = parsePairingQr(text, { allowLocal: d.allowLocal })
        if ('address' in s) {   // ('in', not s.ok: the app's tsconfig isn't strict, so ok doesn't narrow)
          stopped = true
          off()
          await d.found(s.address, s.code)
          return
        }
        if (text !== lastRefused) {
          lastRefused = text
          d.refused(s.message)
        }
      }
      await wait(every)
    }
    off()
  })()

  return {
    stop() {
      stopped = true
      off()
    },
    done,
  }
}
