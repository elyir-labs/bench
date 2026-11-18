// A USB stick (design/usb/: 1 A, all of 2, 3 A): the sheet that asks when a stick goes in, the line over a print, its
// progress and result, and Care's USB stick row. The printer's intent carries `usb` (printer/printer_intent.py), the
// box's /bench/box/usb the same (bench/box.py); both read what the installer's `usb in` / `usb run` wrote.
// Pinned by tests/usb.test.ts.

import { versionWords } from './update.ts'

export type UsbWhy = 'unsigned' | 'other_build' | 'older' | 'same' | 'with_os' | 'not_card' | 'board'
export type TakeState = 'copying' | 'report' | 'waiting' | 'checking' | 'installing' | 'restarting' | 'done' | 'failed' | 'skipped'

export interface UsbItem { file?: string; version: string; why: UsbWhy | null; size?: number; board?: string; on?: string | null }
export interface UsbKey { id: string; kind: string; name: string; fp: string }
export interface UsbTake {
  state: TakeState
  done?: number | null
  of?: number | null
  /** copied: the stick can come out */
  out?: boolean
  why?: string | null
  /** print: copied during a print, waits for it; screen: no screen said it saw the stick */
  auto?: 'print' | 'screen' | null
  app?: string | null
  os?: string | null
  keys?: number
  wifi?: string | null
  report?: string | null
  result?: string | null
}
export interface UsbView {
  id: string
  label?: string
  present: boolean
  readable: boolean
  why?: string | null
  folder?: boolean
  app: UsbItem | null
  os: UsbItem | null
  keys: UsbKey[]
  wifi: { name: string; can: boolean } | null
  seen: boolean
  skipped: boolean
  take: UsbTake | null
}

export type UsbActKey = 'skip' | 'take' | 'close' | 'hide'
export interface UsbChoice { key: string; title: string; line: string; on: boolean }
export interface UsbSheet {
  tone: 'usb' | 'done' | 'bad'
  title: string
  line: string
  small: string | null
  /** a line with a spinner under the text: what it's doing now */
  status: string | null
  progress: number | null
  choices: UsbChoice[]
  acts: { key: UsbActKey; label: string; go: boolean }[]
}
export interface UsbBanner { title: string; line: string; act: string | null }
export interface UsbRow { title: string; line: string; buttons: { key: 'look' | 'report'; label: string }[] }

export interface UsbOpts {
  /** the release it runs now, for "Has …" */
  have?: string | null
  /** the Bench Box: its own words, and the Kobras' screens with it */
  box?: boolean
  kobras?: boolean
  printing?: boolean
  /** Care's Look: the ask again, after Not now */
  force?: boolean
}

const GOING: TakeState[] = ['copying', 'report', 'waiting', 'checking', 'installing', 'restarting']
const mb = (n: number | null | undefined) => Math.max(1, Math.round((n ?? 0) / 1e6))
const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const board = (b: string | null | undefined) => (b ? b.replace(/^pi(\d+)$/, 'Pi $1') : 'another board')
const one = (v: string | null | undefined) => versionWords(v).replace(/ version$/, ' one')
const osWords = (v: string | null | undefined) => versionWords(v).replace(/ version$/, ' Elyir Bench OS')

/** What the stick has that can be taken here. */
export function usbOffers(u: UsbView) {
  return {
    app: !!u.app && u.app.why === null,
    os: !!u.os && u.os.why === null,
    keys: u.keys ?? [],
    wifi: !!u.wifi?.can,
  }
}

export const usbGoing = (u: UsbView | null | undefined) => !!u?.take && GOING.includes(u.take.state)

function shortFp(fp: string): string {
  const s = fp.replace(/^SHA256:/, '')
  return s.length > 10 ? `SHA256:${s.slice(0, 4)}…${s.slice(-3)}` : fp
}

/** Why nothing on the stick can be taken, when that's worth saying (an older or the same version says nothing). */
function refusal(u: UsbView, name: string): { title: string; line: string } | null {
  if (!u.readable) return { title: "Couldn't read the stick", line: 'Try a stick formatted FAT32 or exFAT (most are).' }
  const whys = [u.app?.why, u.os?.why]
  if (whys.includes('unsigned')) return { title: "It isn't signed by Elyir", line: 'Nothing on the stick was installed.' }
  if (u.os?.why === 'board') {
    return { title: "It's for another kind of board", line: `The stick's system is for a ${board(u.os.board)}. ${name} is a ${board(u.os.on)}.` }
  }
  if (u.os?.why === 'not_card' && !u.app) {
    return { title: 'That system is for a flashed card', line: `${name} was set up with the install command, so it takes the app's release (elyir-bench-….tar.gz) instead.` }
  }
  if (u.app?.why === 'other_build') {
    return { title: "It's another kind of build", line: 'A developer build only takes developer builds, and a release only releases, so nothing was installed.' }
  }
  return null
}

function asked(u: UsbView, name: string, o: UsbOpts): UsbSheet | null {
  const offer = usbOffers(u)
  const extras = offer.keys.length > 0 || offer.wifi
  const base = { small: null, status: null, progress: null, choices: [] as UsbChoice[] }
  const ask = [{ key: 'skip' as const, label: 'Not now', go: false }]
  if (!extras && offer.app) {
    const line = o.box
      ? o.kobras
        ? "Update the Bench Box to it? The Kobras' screens come from the box, so they update with it. Your printers keep printing."
        : 'Update the Bench Box to it? Its screen is back in about a minute, and your printers keep printing.'
      : `Update ${name} to it? Its screens are back in about a minute. Klipper and the printer's settings aren't touched. If it doesn't start properly, it goes back to this version by itself.`
    return { ...base, tone: 'usb', title: `A USB stick with ${versionWords(u.app!.version)}`, line,
             small: o.have ? `Has ${o.have} · the stick has ${u.app!.version}` : null,
             acts: [...ask, { key: 'take', label: 'Update', go: true }] }
  }
  if (!extras && offer.os) {
    return { ...base, tone: 'usb', title: `A USB stick with ${osWords(u.os!.version)}`,
             line: `Update ${o.box ? 'the Bench Box' : name}'s whole system to it? It restarts once, about 4 minutes. If it doesn't start properly, it goes back to this one by itself.`,
             small: `A ${board(u.os!.on)} card · the stick has ${(u.os!.file ?? '').split('/').pop()} (${mb(u.os!.size)} MB)`,
             acts: [...ask, { key: 'take', label: 'Update', go: true }] }
  }
  if (!extras) return null
  const who = o.box ? 'the Bench Box' : name
  const choices: UsbChoice[] = []
  if (offer.app) choices.push({ key: 'app', title: capital(versionWords(u.app!.version)), line: o.have ? `${capital(who)} has ${one(o.have)}.` : 'A newer version.', on: true })
  if (offer.os) choices.push({ key: 'os', title: capital(osWords(u.os!.version)), line: 'Its whole system. It restarts once, about 4 minutes.', on: true })
  for (const k of offer.keys) {
    choices.push({ key: `key:${k.id}`, title: k.name ? `An SSH key named “${k.name}”` : 'An SSH key',
                   line: `That computer can sign in to ${who}. ${shortFp(k.fp)}`, on: false })
  }
  if (offer.wifi) choices.push({ key: 'wifi', title: `Wi-Fi “${u.wifi!.name}”`, line: `${capital(who)} joins it and remembers it.`, on: false })
  return { ...base, tone: 'usb', title: 'On this USB stick', line: `Tick what ${who} should take. Nothing is taken unless it's ticked here.`,
           choices, acts: [...ask, { key: 'take', label: 'Go', go: true }] }
}

function going(t: UsbTake, name: string, o: UsbOpts): UsbSheet {
  const base = { tone: 'usb' as const, small: null, status: null, progress: null, choices: [] as UsbChoice[], acts: [] as UsbSheet['acts'] }
  const updating = !!(t.app || t.os)
  const title = updating ? 'Updating from the USB stick' : 'Taking from the USB stick'
  const what = t.os ? osWords(t.os) : versionWords(t.app)
  if (t.state === 'copying') {
    const part = t.of ? `, ${mb(t.done)} of ${mb(t.of)} MB` : ''
    return { ...base, title, line: `Don't take it out yet. Copying ${updating ? what : 'from it'}${part}.`,
             progress: t.of ? Math.min(1, (t.done ?? 0) / t.of) : null }
  }
  if (t.state === 'report') return { ...base, title: 'Copying a report to the stick', line: "Don't take it out yet.", status: 'Gathering the logs and settings…' }
  if (t.state === 'waiting') {
    const who = o.box ? 'The box' : name
    return { ...base, title: `${capital(what)} is copied from the stick`,
             line: `You can take the stick out. ${t.why ? t.why + ' ' : ''}${who} updates after that.`,
             acts: [{ key: 'skip', label: 'Not this time', go: false }, { key: 'hide', label: 'OK', go: true }] }
  }
  if (t.state === 'restarting') {
    return { ...base, title, line: "You can take the stick out now. If the new system doesn't start properly, it goes back to this one by itself.",
             status: 'Restarting into it…' }
  }
  return { ...base, title, line: 'Copied and checked. You can take the stick out now.',
           status: t.os ? 'Writing the new system…' : `Starting ${what}…` }
}

function finished(t: UsbTake, name: string, o: UsbOpts): UsbSheet {
  const who = o.box ? 'The box' : name
  const base = { small: null, status: null, progress: null, choices: [] as UsbChoice[] }
  const close = [{ key: 'close' as const, label: 'Done', go: true }]
  if (t.state === 'failed') {
    return { ...base, tone: 'bad', title: t.app || t.os ? "It didn't update" : "It didn't finish", line: t.why ?? "It didn't finish.",
             acts: [{ key: 'close', label: 'OK', go: true }] }
  }
  const also: string[] = []
  if (t.keys) also.push(t.keys === 1 ? 'That computer can sign in now.' : `Those ${t.keys} computers can sign in now.`)
  if (t.wifi) also.push(`${who} knows ${t.wifi} now.`)
  if (t.why) also.push(t.why)
  if (t.report && !t.app && !t.os && !t.keys && !t.wifi) {
    return { ...base, tone: 'done', title: 'Report copied to the stick',
             line: `${t.report}: the last day of logs, printer.cfg and ${o.box ? "the box's" : `${name}'s`} settings. Keep it as a backup, or send it when asking for help.`,
             small: 'Passwords, keys and Wi-Fi details are taken out.', acts: close }
  }
  const title = t.app ? `${who} has ${versionWords(t.app)}` : t.os ? `${who} has ${osWords(t.os)}` : 'Done'
  const out = 'You can take the stick out. Leaving it in does nothing more: a stick is only asked about when it goes in.'
  return { ...base, tone: 'done', title, line: [...also, out].join(' '), acts: close }
}

/** The sheet over any screen, or null. */
export function usbSheet(u: UsbView | null | undefined, name: string, o: UsbOpts = {}): UsbSheet | null {
  if (!u) return null
  const t = u.take
  if (t && t.state !== 'skipped') {
    if (GOING.includes(t.state)) return usbBanner(u, name, o) ? null : going(t, name, o)
    return finished(t, name, o)
  }
  if (!u.present || (u.skipped && !o.force)) return null
  const ask = asked(u, name, o)
  if (ask) return ask
  const no = refusal(u, name)
  return no ? { tone: 'bad', ...no, small: null, status: null, progress: null, choices: [], acts: [{ key: 'skip', label: 'OK', go: true }] } : null
}

/** Over a print, a line at the top in place of the sheet: the print stays in view (a printer, not the box). */
export function usbBanner(u: UsbView | null | undefined, name: string, o: UsbOpts = {}): UsbBanner | null {
  const t = u?.take
  if (!t || o.box || !o.printing || !(t.app || t.os) || !['copying', 'checking', 'waiting'].includes(t.state)) return null
  const what = t.os ? osWords(t.os) : versionWords(t.app)
  if (t.state === 'copying') return { title: `Copying ${what} from the stick`, line: "Don't take the stick out yet.", act: null }
  return { title: `${capital(what)} is copied from the stick`, line: `You can take the stick out. ${name} updates after this print.`,
           act: 'Not this time' }
}

/** Care's USB stick row, while a stick is in. */
export function usbRow(u: UsbView | null | undefined, name: string): UsbRow | null {
  if (!u?.present) return null
  if (usbGoing(u)) return { title: 'USB stick', line: 'Taking what was asked for from the stick.', buttons: [] }
  if (!u.readable) return { title: 'USB stick', line: "Couldn't read the stick. Try one formatted FAT32 or exFAT.", buttons: [] }
  const o = usbOffers(u)
  const parts: string[] = []
  if (o.app) parts.push(capital(versionWords(u.app!.version)))
  if (o.os) parts.push(capital(osWords(u.os!.version)))
  if (o.keys.length) parts.push(o.keys.length === 1 ? 'an SSH key' : `${o.keys.length} SSH keys`)
  if (o.wifi) parts.push('Wi-Fi')
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0]
  const report = { key: 'report' as const, label: 'Copy a report' }
  if (!list) return { title: 'USB stick', line: `A stick is in. Nothing on it for ${name}.`, buttons: [report] }
  return { title: 'USB stick', line: `${capital(list)} ${parts.length > 1 ? 'are' : 'is'} on it.`,
           buttons: [{ key: 'look', label: 'Look' }, report] }
}

/** What Go or Update asks for, from the ticks (an update is ticked unless unticked; a key or Wi-Fi only when ticked). */
export function usbTakeArgs(u: UsbView, ticked: Record<string, boolean>): { app: boolean; os: boolean; keys: string[]; wifi: boolean } {
  const o = usbOffers(u)
  const on = (k: string, dflt: boolean) => (k in ticked ? ticked[k] : dflt)
  return {
    app: o.app && on('app', true),
    os: o.os && on('os', true),
    keys: o.keys.filter((k) => on(`key:${k.id}`, false)).map((k) => k.id),
    wifi: o.wifi && on('wifi', false),
  }
}
