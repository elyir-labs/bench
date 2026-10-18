// The Printers list, grouped by what a person has to do (design/printers-home/, A, picked 15 October 2026).
import type { LivePrinter } from './printers.ts'
import { statusOf } from './status.ts'

export type Group = 'attention' | 'busy' | 'done' | 'ready' | 'off'
export const ORDER: Group[] = ['attention', 'busy', 'done', 'ready', 'off']

export function groupOf(p: LivePrinter): Group {
  if ((p.reach !== 'home' && p.reach !== 'away') || !p.connected || !p.intent) return 'off'
  switch (p.intent.state) {
    case 'problem': case 'needs_you': return 'attention'
    case 'printing': case 'preparing': return 'busy'
    case 'finished': return 'done'
    default: return 'ready'
  }
}

/** Every group with printers in it, in ORDER; inside a group, the order they were added. */
export function grouped(list: LivePrinter[]): { group: Group; printers: LivePrinter[] }[] {
  const by = new Map<Group, LivePrinter[]>()
  for (const p of [...list].sort((a, b) => a.added - b.added)) {
    const g = groupOf(p)
    by.set(g, [...(by.get(g) ?? []), p])
  }
  return ORDER.filter((g) => by.has(g)).map((group) => ({ group, printers: by.get(group)! }))
}

/** The group's heading. homeOnly: out of reach means "at home only" (design/one-cloud/). */
export function groupLabel(group: Group, printers: LivePrinter[], homeOnly = false): string {
  switch (group) {
    case 'attention': return 'Needs you'
    case 'busy': return printers.every((p) => p.intent?.state === 'printing') ? 'Printing' : 'Busy'
    case 'done': return printers.length > 1 ? 'Done · lift them off' : 'Done · lift it off'
    case 'ready': return 'Ready'
    case 'off':
      if (printers.every((p) => p.reach === 'checking' || (p.reach !== 'offline' && p.reach !== 'unpaired'))) return 'Looking…'
      return homeOnly ? 'At home only' : 'Out of reach'
  }
}

/** "2:30 pm" today, "Yesterday", or the weekday; as the intent layer writes eta_clock. */
export function clock(iso: string | null | undefined, now = Date.now()): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ''
  const day = (t: number) => new Date(t).toDateString()
  if (day(d.getTime()) === day(now)) {
    const h = d.getHours() % 12 || 12
    return `${h}:${String(d.getMinutes()).padStart(2, '0')} ${d.getHours() < 12 ? 'am' : 'pm'}`
  }
  if (day(d.getTime()) === day(now - 86_400_000)) return 'Yesterday'
  return d.toLocaleDateString('en-US', { weekday: 'long' })
}

/** What one row says: the word on the right and the line under the name. The group already says the rest. */
export function rowOf(p: LivePrinter, homeOnly = false, now = Date.now()): { word: string; line: string; progress: number | null } {
  const s = statusOf(p, homeOnly)
  const i = p.intent
  if (!i || groupOf(p) === 'off') return { word: s.word, line: s.line, progress: null }
  const job = i.job
  switch (i.state) {
    case 'printing': return { word: `${Math.floor((job?.progress ?? 0) * 100)}%`, line: s.line, progress: job?.progress ?? 0 }
    case 'finished': return { word: clock(i.since, now), line: job?.name || s.line, progress: null }
    case 'needs_you': return { word: '', line: s.line, progress: null }   // its group already says Needs you
    default: return { word: s.word, line: s.line, progress: null }
  }
}

/** A card on the wide overview (design/printers-open/, A): no group headings there, so the card says the group. */
export function cardOf(p: LivePrinter, homeOnly = false, now = Date.now()): { word: string; line: string; progress: null | number } {
  const r = rowOf(p, homeOnly, now)
  if (groupOf(p) !== 'done') return r
  return { word: 'Done', line: [p.intent?.job?.name, 'lift it off', clock(p.intent?.since, now)].filter(Boolean).join(' · '), progress: null }
}

/** The heading over the printers that need you takes their color: red if one has stopped, amber otherwise. */
export const attentionTone = (list: LivePrinter[]) => (list.some((p) => p.intent?.state === 'problem') ? 'red' : 'amber')

/** One printer and nothing else in the list: the app opens on it, with no list of one in front. */
export function straightIn(list: LivePrinter[], benchCount: number): string | null {
  return list.length === 1 && benchCount === 0 ? list[0].id : null
}

/** The chips across a wide printer page (as on the Bench Box): the printers that answer, in the list's order, and how many don't. */
export function chipsOf(list: LivePrinter[]): { on: LivePrinter[]; off: number } {
  const g = grouped(list)
  return { on: g.filter((x) => x.group !== 'off').flatMap((x) => x.printers), off: g.find((x) => x.group === 'off')?.printers.length ?? 0 }
}

/** A busy printer's camera, as a still from its door's /webcam (null when there's no print to watch); a printer without a
 *  camera fails it once and keeps its job's picture. */
export function snapshotOf(p: LivePrinter, tick = 0): string | null {
  if (!p.base || !p.intent || !['printing', 'preparing'].includes(p.intent.state)) return null
  return `${p.base}/webcam/?action=snapshot&access_token=${encodeURIComponent(p.token)}&t=${tick}`
}

/** The picture beside a printer: its job's, while there is one to look at. */
export function pictureOf(p: LivePrinter): string | null {
  const path = p.intent?.job?.thumbnail
  if (!path || !p.base || !['printing', 'preparing', 'finished'].includes(p.intent!.state)) return null
  return `${p.base}/server/files/gcodes/${path.split('/').map(encodeURIComponent).join('/')}?access_token=${encodeURIComponent(p.token)}`
}

/** The spool in the head of a Ready printer, for its swatch. */
export function loadedColor(p: LivePrinter): string | null {
  const spools = p.intent?.spools ?? []
  return (spools.find((s) => s.in_use) ?? (spools.length === 1 ? spools[0] : undefined))?.color ?? null
}

/** Every reachable printer answered through the internet: the page says "Away from home" once instead of per row. */
export const allAway = (list: LivePrinter[]) => {
  const reached = list.filter((p) => p.reach === 'home' || p.reach === 'away')
  return reached.length > 0 && reached.every((p) => p.reach === 'away')
}
/** Mixed: only the printers reached the unusual way get marked. */
export const markAway = (p: LivePrinter, list: LivePrinter[]) => p.reach === 'away' && !allAway(list)
