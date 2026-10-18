// Bring it over (design/printer-setup/, A, agreed 5 October 2026; the contract with the printer's side is
// docs/bring-it-over.md). A fresh card has Klipper and no printer.cfg, so the intent says `setup` and the panel and
// the phone show "Now the printer itself" instead of Problem: bring the old printer's setup over, or write your own.
// Which screen shows when, and every word on them, live here, pure, so tests/bring.test.ts can pin them to the
// boards (a-start, a-bring, a-bring-what, a-done); components/bring/ only draws them.

import { PRODUCT } from './setup.ts'

export type BringState = 'idle' | 'scanning' | 'planning' | 'bringing' | 'done' | 'failed' | 'asking'
export type SourceKind = 'card' | 'printer' | 'file' | 'cloud'
export type BoardMatch = 'same' | 'changed' | 'missing' | 'unchecked'

/** One place a setup can come from (`bring scan`). `when` is the newest config file's time, in seconds. */
export interface BringSource {
  id: string
  kind: SourceKind
  name: string
  detail: string
  when: number | null
  files: number
  gcodes: number
  history: number
  boards: string[]
  /** A Bench Cloud backup (docs/cloud.md): who allows it, for the owner screen */
  owner_phone?: string | null
  owner_email?: string | null
}
export interface BringBoard { name: string; chip?: string; can?: string; match: BoardMatch; words?: string; to?: string }
export interface BringPlan {
  id: string
  config: number
  history: number | boolean
  spools: boolean
  mainsail: boolean
  gcodes: { count: number; bytes: number } | null
  boards: BringBoard[]
  /** What stays behind or needs doing after, in words (the printer's side writes them): history left on a plain
   *  Moonraker, an older database, an add-on this card doesn't have */
  notes?: string[]
}
export interface BringProgress { step: string; done: number; of: number }
export interface BringResult { klipper: 'ready' | 'error'; message: string }

/** GET /printer/intent/bring. `found` (what this Pi sees plugged in, a-start's chips) is optional: the app
 *  shows the chips when the printer sends them (docs/bring-it-over.md, "As built in the app"). */
export interface BringInfo {
  state: BringState
  sources: BringSource[]
  plan: BringPlan | null
  progress: BringProgress | null
  result: BringResult | null
  why: string | null
  found?: string[]
  /** Printer boards plugged in (Klipper serials, USB-serial chips, CAN boards or a CAN adapter), from the scan; absent
   *  from a printer side older than design/role/, and null until it has looked. */
  boards?: number | null
  /** Becoming a Bench Box (design/role/, B): null when not; absent from a printer side that can't. */
  role?: RoleInfo | null
  /** A Bench Cloud backup being asked for; absent from a printer side without Bench Cloud */
  cloud?: CloudAsk | null
}

/** A new card asking the house's owner for a Bench Cloud backup (docs/cloud.md, design/cloud/ C). `file`: the backup
 *  file's source once allowed, planned and brought over like any other. */
export interface CloudAsk {
  id: string
  name: string
  state: 'waiting' | 'allowed' | 'refused' | 'expired'
  owner_phone?: string | null
  owner_email?: string | null
  emailed?: string | null
  file?: string
}

/** `elyir-bench role controller`, followed: its steps, then Moonraker stops and the Bench app takes the screen. */
export interface RoleInfo { state: 'switching' | 'failed'; progress: BringProgress | null; why: string | null; url: string | null }

export const EMPTY: BringInfo = { state: 'idle', sources: [], plan: null, progress: null, result: null, why: null }

/** Where the person is, which the printer doesn't need to know. `applied`: Bring it over was pressed. */
export type Here =
  | { at: 'start' }
  | { at: 'sources' }
  | { at: 'address' }
  | { at: 'file' }
  | { at: 'plan'; id?: string; applied?: boolean }
  | { at: 'cloud'; id: string }
  | { at: 'printer' }   // "It's a printer" on Nothing's plugged in: the three ways after all

export type Screen = 'start' | 'none' | 'box' | 'sources' | 'address' | 'file' | 'planning' | 'plan' | 'bringing' | 'done' | 'stopped' | 'failed' | 'cloud'

/** The screen: what the printer is doing first (bringing, a result not seen here yet), then where the person is. */
export function screenFor(info: BringInfo, here: Here, seen: boolean): Screen {
  if (info.role) return 'box'
  if (info.state === 'bringing') return 'bringing'
  if (info.state === 'done' && info.result && !seen) return info.result.klipper === 'ready' ? 'done' : 'stopped'
  if (here.at === 'plan') {
    if (info.state === 'failed') return 'failed'
    if (info.state === 'planning' || !info.plan || (here.id && info.plan.id !== here.id)) return 'planning'
    return 'plan'
  }
  if (here.at === 'printer') return 'start'
  // design/role/, B: nothing plugged in, so the Bench Box leads
  if (here.at === 'start' && info.boards === 0 && info.role !== undefined) return 'none'
  return here.at
}

/** Shown instead of the app: a printer with no config, the link from the Wi-Fi's Connected, a copy going on,
 *  or its result not yet seen on this screen. After that, the printer's normal Now. */
export function shown(o: { state: string | null | undefined; info: BringInfo | null; requested: boolean; seen: boolean }): boolean {
  if (o.state === 'setup' || o.requested || o.info?.role) return true
  const i = o.info
  return !!i && (i.state === 'bringing' || (i.state === 'done' && !!i.result && !o.seen))
}

/** Which result a screen has seen (kept in the browser), so Done is said once and then it's the normal Now. */
export const resultKey = (i: BringInfo | null): string =>
  i?.result ? `${i.plan?.id ?? ''}|${i.result.klipper}|${i.result.message}` : ''

/** How often to ask the printer again: quickly while it works, now and then while the screens show. */
export function pollMs(info: Pick<BringInfo, 'state' | 'role' | 'cloud'> | null, onScreen: boolean): number {
  const s = info?.state
  if (s === 'scanning' || s === 'planning' || s === 'bringing' || s === 'asking' || info?.role?.state === 'switching') return 1000
  if (info?.cloud?.state === 'waiting') return 1000
  return onScreen ? 3000 : 0
}

// ---- the step bar ---------------------------------------------------------------------------------

/** Wi-Fi, then Printer. The boards' third step, Check, comes with Check the printer (not built yet). */
export const STEPS = ['Wi-Fi', 'Printer']
export const stepOf = (screen: Screen): number => (screen === 'done' || screen === 'stopped' ? 2 : 1)

// ---- a-start: three ways to a config, under what it found plugged in ------------------------------

export const START_TITLE = 'Now the printer itself.'
export function startSub(found: string[] | undefined): string {
  return found?.length
    ? "It found these. It can't see how they're wired, so it needs a config, once."
    : "It can't see how the printer is wired, so it needs a config, once."
}
export const START_FOOT = 'Ran Klipper on this printer before? Bring it over: nothing to pick or write.'

export interface Way { id: 'bring' | 'known' | 'own'; title: string; line: string; pill: string | null; later: boolean }

/** The three ways, as drawn. A printer it knows isn't built: shown muted, "Later", and not a button. */
export function ways(sources: BringSource[]): Way[] {
  return [
    { id: 'bring', title: 'Bring it over', line: 'From your old card, another printer, or a backup. Everything comes with it.',
      pill: foundPill(sources), later: false },
    { id: 'known', title: 'A printer I know', line: "Pick it from pictures. Settings we've tested for it.", pill: 'Later', later: true },
    { id: 'own', title: 'Write my own', line: "In Mainsail's editor. When Klipper starts, it's ready.", pill: null, later: false },
  ]
}

/** The pill on Bring it over: what it already sees, the old card first. */
export function foundPill(sources: BringSource[]): string | null {
  if (sources.some((s) => s.kind === 'cloud')) return 'Your backup found'
  if (sources.some((s) => s.kind === 'card')) return 'Old card found'
  if (sources.some((s) => s.kind === 'printer')) return 'Printer found'
  if (sources.some((s) => s.kind === 'file')) return 'Backup found'
  return null
}

// ---- a-bring: what it can see, newest first ---------------------------------------------------------

export const SOURCES_TITLE = 'Bring it over from…'
export const SOURCES_SUB = 'Your config, macros, calibration and history come with it.'
export const SOURCES_NOTE = 'An old card is only read, never changed. Plug a USB card reader into the printer and it shows up here.'
export const LOOK_AGAIN = 'Look again'
export const LOOKING = 'Looking…'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

/** "today", "yesterday", "Oct 3", "Oct 3, 2025" (local time; `when` in seconds, `now` in ms). */
export function dayWords(when: number, now: number): string {
  const d = new Date(when * 1000), n = new Date(now)
  const days = Math.round((startOfDay(n) - startOfDay(d)) / 86_400_000)
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  const md = `${MONTHS[d.getMonth()]} ${d.getDate()}`
  return d.getFullYear() === n.getFullYear() ? md : `${md}, ${d.getFullYear()}`
}

/** "2:10 am", "9:05 pm" (local time). */
export function clockWords(d: Date): string {
  const h = d.getHours()
  return `${h % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`
}

/** When a backup was made: "just now", "20 minutes ago", "2 hours ago" for the last three hours; then "last night at
 *  2:10 am", "today at 9:05 am", "yesterday at 3:00 pm", "Oct 3 at …". */
export function backupWords(when: number, now: number): string {
  if (now / 1000 - when < 3 * 3600) return agoWords(when, now)
  const d = new Date(when * 1000), n = new Date(now)
  const days = Math.round((startOfDay(n) - startOfDay(d)) / 86_400_000)
  const at = clockWords(d)
  if (days === 0) return d.getHours() < 6 ? `last night at ${at}` : `today at ${at}`
  if (days === 1) return d.getHours() >= 18 ? `last night at ${at}` : `yesterday at ${at}`
  return `${dayWords(when, now)} at ${at}`
}

/** "just now", "5 minutes ago", "2 hours ago", then the day. */
export function agoWords(when: number, now: number): string {
  const s = Math.max(0, now / 1000 - when)
  if (s < 60) return 'just now'
  if (s < 3600) { const m = Math.floor(s / 60); return `${m} minute${m === 1 ? '' : 's'} ago` }
  if (s < 86_400) { const h = Math.floor(s / 3600); return `${h} hour${h === 1 ? '' : 's'} ago` }
  return dayWords(when, now)
}

export type RowIcon = 'card' | 'printer' | 'file' | 'address' | 'backup' | 'cloud'
export interface SourceRow { id: string; icon: RowIcon; title: string; line: string; press: 'plan' | 'address' | 'file' | 'cloud'; lit: boolean }

/** One row per source: a Bench Cloud backup first (design/cloud/ C), then an old card (the printer being reflashed, as
 *  a-bring draws it), then newest first; then the two ways to add one, an address and a backup file. */
export function sourceRows(sources: BringSource[], now: number): SourceRow[] {
  const first = (s: BringSource) => (s.kind === 'cloud' ? 0 : s.kind === 'card' ? 1 : 2)
  const rows: SourceRow[] = [...sources].sort((a, b) => first(a) - first(b) || (b.when ?? 0) - (a.when ?? 0)).map((s) => {
    const day = s.when ? `from ${dayWords(s.when, now)}` : ''
    if (s.kind === 'cloud') {
      return { id: s.id, icon: 'cloud', title: 'Your Bench Cloud backup', line: join([s.name, s.when ? backupWords(s.when, now) : '']),
               press: 'cloud', lit: true }
    }
    if (s.kind === 'card') {
      return { id: s.id, icon: 'card', title: 'Your old card', line: join([s.detail, day, s.name]), press: 'plan', lit: true }
    }
    if (s.kind === 'printer') {
      return { id: s.id, icon: 'printer', title: `${s.name}, on your Wi-Fi`,
               line: join([s.detail, s.when ? `changed ${agoWords(s.when, now)}` : '']), press: 'plan', lit: false }
    }
    return { id: s.id, icon: 'file', title: s.name, line: join([s.detail, day]), press: 'plan', lit: false }
  })
  rows.push({ id: 'address', icon: 'address', title: "Another printer's address", line: 'Any printer with Klipper and Moonraker', press: 'address', lit: false })
  rows.push({ id: 'backup', icon: 'backup', title: 'A backup file', line: 'From your phone or computer', press: 'file', lit: false })
  return rows
}
const join = (parts: string[]) => parts.filter(Boolean).join(' · ')

// ---- a Bench Cloud backup: the house's owner allows it (design/cloud/ C-panel-restore) ----------------

export const CLOUD_TITLE = 'From your Bench Cloud backup'
export const CLOUD_NEEDS = "This needs the house's owner. Either works:"
export const CLOUD_NOTE = "Restoring needs the owner, so a stolen printer can't pull your settings."
export const cloudAllowTitle = (c: Pick<CloudAsk, 'owner_phone'>) => (c.owner_phone ? `Allow on ${c.owner_phone}` : "Allow on the owner's phone")
export const CLOUD_ASKED = 'Asked just now'
export const CLOUD_EMAIL_TITLE = 'A code from the email'
export function cloudEmailLine(c: Pick<CloudAsk, 'emailed' | 'owner_email'>): string {
  if (c.emailed) return `Sent to ${c.emailed}`
  return c.owner_email ? `Goes to ${c.owner_email}` : "Goes to the owner's email"
}
export const CLOUD_TYPE = 'Type the code from the email'
/** On the panel, once the code is sent: only the code to type, and that Allow still works. */
export const cloudTypeLine = (c: Pick<CloudAsk, 'emailed' | 'owner_phone'>) =>
  `Sent to ${c.emailed ?? "the owner's email"}. ${cloudAllowTitle(c)} still works.`
/** The backup file a Bench Cloud backup becomes once allowed (docs/cloud.md: <name>-bench-cloud.tar.gz). */
export const isCloudFile = (s: Pick<BringSource, 'id' | 'kind'>) => s.kind === 'file' && s.id.endsWith('-bench-cloud-tar-gz')
export const CLOUD_SEND = 'Send the code'
export const CLOUD_SEND_AGAIN = 'Send it again'
export const CLOUD_CODE_GO = 'Bring it back'
export const CLOUD_GETTING = 'Getting the backup…'
export const CLOUD_ASK_AGAIN = 'Ask again'
export const isCode = (c: string) => /^\d{6}$/.test(c.replace(/\s/g, ''))
/** A refused or forgotten ask: what happened, and what to do. */
export function cloudEnd(state: CloudAsk['state']): { title: string; line: string } | null {
  if (state === 'refused') return { title: 'The owner said no.', line: 'Nothing was brought over. Ask again if that was a mistake.' }
  if (state === 'expired') return { title: 'Nobody answered in time.', line: 'An ask lasts 30 minutes. Ask again, or use the code from the email.' }
  return null
}

// ---- another printer's address, a backup file --------------------------------------------------------

export const ADDRESS_TITLE = "Another printer's address"
export const ADDRESS_NOTE = 'Its name on the Wi-Fi or its IP address, like voron.local or 192.168.1.40.'
export const ADDRESS_GO = 'Look'

/** Why that can't be an address, or null. */
export function addressProblem(a: string): string | null {
  const t = a.trim().replace(/^https?:\/\//, '').replace(/\/$/, '')
  if (!t) return null
  return /^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d{1,5})?$/.test(t) ? null : 'That doesn\'t look like an address. Try voron.local or 192.168.1.40.'
}

export const FILE_TITLE = 'A backup file'
/** On the panel, where nothing can be picked: send it from the phone. */
export const fileLines = (name: string) => [
  `Send it from your phone: open ${name} there, then Bring it over › A backup file.`,
  "A .zip or .tar.gz of a printer_data or config folder, like KIAUH's backups. It shows up in the list here.",
]
export const BACKUP_ACCEPT = '.zip,.tar.gz,.tgz,application/zip,application/gzip,application/x-gzip'
export const isBackup = (name: string) => /\.(zip|tar\.gz|tgz)$/i.test(name)
export const NOT_A_BACKUP = "That isn't a backup. Pick a .zip or .tar.gz of a printer_data or config folder."

/** Where a backup from the phone goes: Moonraker's config root, elyir-bench-bring/<name> (the next scan lists it). */
export function backupUpload(name: string): { root: 'config'; path: string; name: string } {
  return { root: 'config', path: 'elyir-bench-bring', name: name.split(/[\\/]/).pop() || 'backup.zip' }
}
export const SENDING = (name: string) => `Sending ${name}…`

// ---- a-bring-what: what comes over, and whether the boards match ----------------------------------

export function planTitle(source: BringSource | undefined): string {
  if (!source) return 'From there'
  if (source.kind === 'card') return 'From your old card'
  if (source.kind === 'cloud' || isCloudFile(source)) return CLOUD_TITLE
  if (source.kind === 'file') return 'From your backup'
  return `From ${source.name}`
}
export const COMES_OVER = 'Comes over'
export const PLANNING = 'Reading what it has…'

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** The ticked lines under Comes over. */
export function comesOver(plan: BringPlan): string[] {
  const out = [`Printer config, ${plural(plan.config, 'file')}`]
  if (plan.config > 0) out.push('Macros and calibration')
  if (typeof plan.history === 'number' ? plan.history > 0 : plan.history) {
    out.push(typeof plan.history === 'number' ? `History, ${plural(plan.history, 'print')}` : 'History of prints')
  }
  if (plan.spools && plan.mainsail) out.push('Spools and Mainsail settings')
  else if (plan.spools) out.push('Spools')
  else if (plan.mainsail) out.push('Mainsail settings')
  return out
}

/** "812 MB", "1.4 GB". */
export function sizeWords(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  return `${Math.max(1, Math.round(bytes / 1e6))} MB`
}

/** Its G-code files: offered, never ticked to begin with (they can be many and large). */
export function gcodesOffer(plan: BringPlan): { label: string; line: string } | null {
  const g = plan.gcodes
  if (!g || g.count <= 0) return null
  return { label: `Files, ${g.count}`, line: `${sizeWords(g.bytes)} · takes longer` }
}

export const BOARDS_TITLE = 'The same boards?'

/** "stm32f446xx" -> "STM32F446". */
export const chipWords = (chip: string) => chip.replace(/x+$/i, '').toUpperCase()

export interface BoardLine { name: string; line: string; tone: 'green' | 'blue' | 'amber' }

/** Each board its config names, against what's plugged in: same, changed (set to the one plugged in), missing. */
export function boardLine(b: BringBoard): BoardLine {
  const chip = b.chip ? chipWords(b.chip) : null
  if (b.match === 'same') {
    return { name: b.name, tone: 'green', line: chip ? `${chip}, same serial` : b.can ? 'Same CAN ID' : 'The same' }
  }
  if (b.match === 'changed') {
    return { name: b.name, tone: 'blue', line: chip ? `${chip}, another serial: it will be set to the one plugged in`
      : b.can ? 'Another CAN ID: it will be set to the one found' : 'It will be set to the one plugged in' }
  }
  if (b.match === 'unchecked') {
    // CAN can't be asked until this card's CAN network is set up (that part of the old card doesn't come over)
    return { name: b.name, tone: 'blue', line: b.words || 'Not checked yet: it can be once CAN is set up on this card' }
  }
  return { name: b.name, tone: 'amber', line: 'Not found: plug it in, or it can be changed after' }
}

/** The plan's notes, as they come (already words). */
export const planNotes = (plan: BringPlan | null) => (plan?.notes ?? []).filter((n) => typeof n === 'string' && n.trim())

export const APPLY = 'Bring it over'
export const APPLY_NOTE = 'Then Klipper restarts with it, in about a minute.'

// ---- bringing, and how it ended -------------------------------------------------------------------

export const BRINGING_TITLE = 'Bringing it over…'
export function bringingNote(kind: SourceKind | undefined): string {
  return kind === 'card' ? 'Keep the printer on. Nothing on your old card changes.' : 'Keep the printer on.'
}

/** The step it's on, "Step 3 of 5", and how far along (done steps over all of them). */
export function progressWords(p: BringProgress | null): { step: string; count: string; frac: number } {
  if (!p || p.of <= 0) return { step: 'Getting ready', count: '', frac: 0 }
  return { step: p.step, count: `Step ${Math.min(p.done + 1, p.of)} of ${p.of}`, frac: Math.max(0, Math.min(1, p.done / p.of)) }
}

export interface ResultWords { title: string; line: string; tone: 'green' | 'red'; door: boolean; came: string }

/** a-done without the check list (Check the printer isn't built): what came over instead. With Klipper in
 *  error: its message, and the Advanced door. */
export function resultWords(r: BringResult, name: string): ResultWords {
  if (r.klipper === 'ready') {
    return { title: `${name} is set up.`, line: r.message || `Klipper is running. ${PRODUCT} is ready to print.`, tone: 'green', door: false, came: 'Came over' }
  }
  return { title: 'It came over, but Klipper stopped.', line: r.message || "Klipper didn't start with that config.", tone: 'red', door: true, came: 'Came over' }
}
export const DONE = 'Done'
export const OPEN_DOOR = 'Open Mainsail'

/** It didn't come over (or couldn't be read): why, in the printer's words. Nothing was half done. */
export function failedWords(why: string | null, applied: boolean): { title: string; line: string } {
  const line = why || (applied ? 'Something went wrong while copying.' : "It couldn't be read.")
  return applied
    ? { title: "It didn't come over.", line: /nothing (was )?changed/i.test(line) ? line : `${line} Nothing was changed.` }
    : { title: "It can't bring that over.", line }
}

// ---- the link on the Wi-Fi's Connected (design/setup/ S-done) ---------------------------------------

export const WIFI_LINK = 'Bring things over from another printer'

/** Wi-Fi setup ends first (POST /wifi/done, or the panel stays in setup and a reload brings Connected back),
 *  and only then Bring it over opens. Resolves with the service's message when it says no. */
export async function bringFromWifi(done: () => Promise<string | null>, open: () => void): Promise<string | null> {
  const err = await done()
  if (err) return err
  open()
  return null
}

// ---- printer or Bench Box (design/role/, B, picked 5 October 2026) ---------------------------------
// Every fresh card reaches this screen (Wi-Fi or a cable), and a Bench Box has no printer.cfg either. A board found:
// the three ways, and a line to make it a box after all. Nothing plugged in: the box leads, "It's a printer" beside it.

/** The header: what's being set up, and the steps. */
export function headerFor(screen: Screen): { who: string; steps: string[] } {
  if (screen === 'none') return { who: 'New', steps: ['Wi-Fi', 'Printer or box'] }
  if (screen === 'box') return { who: 'New Bench Box', steps: ['Wi-Fi', 'Bench Box'] }
  return { who: 'New printer', steps: STEPS }
}

export const NONE_TITLE = "Nothing's plugged in."
export const NONE_SUB = 'No printer board on USB or CAN. A Pi on its own can be a Bench Box: it looks after your other printers.'
export const NONE_FOOT = "A board without Klipper on it may not show yet. That's still a printer."
export const BOX_WAY = { title: 'A Bench Box', line: 'It slices for your printers, keeps one queue, and shows them all on one screen.', pill: 'Nothing plugged in' }
export const PRINTER_WAY = { title: "It's a printer", line: 'Plug its board in and it looks again. Or carry on to its config.' }
export const BOX_LINK = { before: 'Not a printer?', link: 'Make this a Bench Box', after: ': it looks after your other printers.' }
export const BOX_ASK = {
  title: 'Make this a Bench Box?',
  line: "It found a printer's boards plugged in. A Bench Box doesn't run them: it looks after your other printers.",
  keep: 'Keep it a printer', go: 'Make it a Bench Box',
}

export const BOX_TITLE = 'Becoming a Bench Box'
export const BOX_SUB = 'A minute or two. Then it looks for your printers.'
/** The steps `elyir-bench role controller` reports, in its order: Moonraker goes last, since this screen talks to it. */
export const BOX_STEPS = ['The Bench app', 'Its screen', 'Klipper and Moonraker off']

export function boxSteps(p: BringProgress | null): { label: string; status: 'ok' | 'now' | 'todo' }[] {
  const done = p?.done ?? 0
  return BOX_STEPS.map((label, i) => ({ label, status: i < done ? 'ok' : i === done ? 'now' : 'todo' }))
}

/** Once Moonraker is off, this screen can't hear the box any more: where to find it. */
export function boxGone(url: string | null): string {
  return url ? `Its screen is switching to the Bench app. On this phone, open ${url} in a minute.`
    : 'Its screen is switching to the Bench app. In a minute, this phone finds it at the same address.'
}

export function boxFailed(why: string | null): { title: string; line: string } {
  return { title: "It didn't become a Bench Box.", line: why || 'It stopped without saying why.' }
}
