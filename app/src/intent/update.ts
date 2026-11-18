// Updates on every printer and on the box (design/updates/, A + A): the Updates row in Care, its dot on the Care tab,
// and the Update now sheet. The printer's intent carries `update` (printer/printer_intent.py), the box's /bench/box
// carries `app` (bench/box.py); both read what `elyir-bench update` last wrote. Pinned by tests/updates.test.ts.

export type UpdateState = 'idle' | 'checking' | 'waiting' | 'downloading' | 'installing' | 'failed' | 'done'

export interface UpdateView {
  version: string | null
  latest?: string | null
  newer?: boolean
  state?: UpdateState
  why?: string | null
  done?: number | null
  of?: number | null
  went_back?: boolean
  /** A printer the Bench Box speaks for: its screens are the box's, so it updates with the box. */
  with_box?: boolean
}

export interface UpdateRow {
  title: string
  line: string
  small: string | null
  button: { label: string; disabled: boolean } | null
  tone: '' | 'new' | 'bad'
  progress: number | null
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
  'November', 'December']

/** "2026.11.08-c4a961b" -> "the 8 November version". */
export function versionWords(v: string | null | undefined): string {
  const m = /^(\d{4})\.(\d{2})\.(\d{2})/.exec(v ?? '')
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined
  return m && month ? `the ${Number(m[3])} ${month} version` : v ? `version ${v}` : 'a new version'
}

const going = (u: UpdateView) => u.state === 'checking' || u.state === 'downloading' || u.state === 'installing'

/** The dot on Care: a newer version waits, or the last try didn't work. Not while it's updating, nor for a Kobra. */
export function updateDot(u: UpdateView | null | undefined): boolean {
  if (!u || u.with_box) return false
  return u.state === 'failed' || (!!u.newer && !going(u))
}

const mb = (n: number) => Math.max(1, Math.round(n / 1e6))

/**
 * The row. `name` is the printer's name ("Workshop"), or for the box "The box"; `printing` is live from the printer,
 * `canAsk` false where Update now can't be asked (away from home), `kobras` adds what the box brings with it.
 */
export function updateRow(u: UpdateView, name: string, opts: { printing?: boolean; canAsk?: boolean; kobras?: boolean } = {}): UpdateRow {
  const small = u.version ? `Has ${u.version}` : null
  const base = { small, button: null, tone: '' as const, progress: null }
  if (u.with_box) {
    return { ...base, title: 'Updates', line: `${name}'s screens come from the Bench Box, so they update with it.` }
  }
  const next = versionWords(u.latest)
  if (u.state === 'checking') return { ...base, title: 'Updates', line: 'Looking for a new version.' }
  if (u.state === 'downloading') {
    const part = u.of ? ` ${mb(u.done ?? 0)} of ${mb(u.of)} MB.` : ''
    return { ...base, title: 'Updating', line: `Downloading ${next}.${part}`, tone: 'new', small: null,
             progress: u.of ? Math.min(1, (u.done ?? 0) / u.of) : null }
  }
  if (u.state === 'installing') {
    return { ...base, title: 'Updating', line: `Starting ${next}. The screens are back in about a minute.`, tone: 'new', small: null }
  }
  const ask = opts.canAsk !== false
  const nowButton = (label: string) => (ask ? { label: opts.printing ? 'After this print' : label, disabled: !!opts.printing } : null)
  if (u.state === 'failed') {
    const why = u.went_back
      ? `The new version didn't start properly, so ${name === 'The box' ? 'the box' : name} went back to ${versionWords(u.version)}.`
      : (u.why ?? "It didn't finish.")
    return { ...base, title: "It didn't update", line: `${why} It tries again tomorrow night.`, tone: 'bad', button: nowButton('Try again') }
  }
  if (u.newer) {
    const who = name === 'The box' ? `The box updates by itself tonight${opts.kobras ? ", and the Kobras' screens with it" : ''}` : `${name} updates by itself tonight`
    const line = opts.printing ? `${capital(next)} is out. ${name} updates after this print, at night.`
      : u.state === 'waiting' && u.why ? `${capital(next)} is out. ${u.why} It updates when that's done.`
      : `${capital(next)} is out. ${who}, or now.`
    return { ...base, title: 'Updates', line, tone: 'new', button: nowButton('Update now') }
  }
  const have = u.version ? `Up to date: ${versionWords(u.version)}.` : 'Up to date.'
  return { ...base, title: 'Updates', line: u.why && u.state === 'idle' ? `${have.replace('Up to date: ', 'It has ')} ${u.why}` : `${have} It updates by itself at night.` }
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** The Update now sheet. */
export function updateAsk(name: string, box = false): { title: string; line: string; keep: string; go: string } {
  return box
    ? { title: 'Update the box now?', line: "Its screen is back in about a minute, and your printers keep going. If it doesn't start properly, it goes back to this version by itself.", keep: 'Not now', go: 'Update now' }
    : { title: `Update ${name} now?`, line: "Its screens are back in about a minute. Klipper and its printer settings aren't touched. If it doesn't start properly, it goes back to this version by itself.", keep: 'Not now', go: 'Update now' }
}
