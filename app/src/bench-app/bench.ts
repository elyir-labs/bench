// The Bench Box's home (design/bench-box/, D, agreed 4 October 2026): every printer in the house, the one
// that needs you first, the tiles getting smaller as the bench grows, the printers that are off in one line,
// and one sentence across the top. Pure, so tests/bench.test.ts can pin it; the pages draw what it says.
// Each printer's words are its own (the intent layer); the box only orders them and joins them up.

import type { Intent } from '../intent/types'
import { queueTitle } from './shelf.ts'

export type Tone = 'red' | 'amber' | 'blue' | 'green' | 'off'

/** A printer as the box sees it: reached and live, still connecting, or off. */
export interface BenchPrinter {
  id: string
  name: string
  live: boolean
  intent: Intent | null
}

export interface Tile {
  id: string
  name: string
  tone: Tone
  word: string            // the chip: Needs you, Done, Printing, Ready...
  says: string            // the printer's own sentence, or when it's done
  what: string            // the part and its material, or what's loaded
  frac: number            // how far, for the ring (0 when there's nothing on the bed)
  thumbnail: string | null   // the job's picture, a path under the printer's gcodes
  action: string | null   // the one next thing, in the printer's words (it opens the printer to do it)
  actionId?: string | null   // its intent action, which the away list is checked against
  rank: number            // needs you first, then printing by when it's done, then ready
  remaining: number | null
  queued?: string         // a queued print waiting for this printer's bed (withQueue)
  queuedName?: string
}

export function tileOf(p: BenchPrinter): Tile {
  const base = { id: p.id, name: p.name, frac: 0, thumbnail: null, action: null, remaining: null }
  const i = p.intent
  if (!p.live || !i) return { ...base, tone: 'off', word: 'Off', says: '', what: '', rank: 9 }
  const job = i.job
  const part = job ? [job.name, job.material?.toUpperCase()].filter(Boolean).join(' · ') : ''
  const firstAct = i.actions.find((a) => a.primary && !a.hold) ?? i.actions.find((a) => !a.hold) ?? null
  const first = firstAct?.label ?? null
  const withJob = { frac: job?.progress ?? 0, thumbnail: job?.thumbnail ?? null, remaining: job?.remaining_s ?? null }
  switch (i.state) {
    case 'problem':
      return { ...base, ...withJob, tone: 'red', word: 'Stopped', says: i.headline, what: part, action: first, actionId: firstAct?.id ?? null, rank: 0 }
    case 'needs_you':
      return { ...base, ...withJob, tone: 'amber', word: 'Needs you', says: i.headline, what: part, action: first, actionId: firstAct?.id ?? null, rank: 1 }
    case 'finished': {
      // done, and the bed has to be cleared before the next one: it needs a person too
      // the bed first: on the bench, the next thing is taking it off, not printing another
      const off = i.actions.find((a) => a.id === 'taken_off') ?? firstAct
      return { ...base, ...withJob, frac: 1, tone: 'amber', word: 'Done', says: i.headline, what: part, rank: 2,
               action: off?.label ?? null, actionId: off?.id ?? null }
    }
    case 'printing':
    case 'preparing':
      return { ...base, ...withJob, tone: 'blue', word: i.state === 'printing' ? 'Printing' : 'Getting ready',
               says: job?.eta_clock ? `Done at ${job.eta_clock}` : i.headline, what: part, rank: 3 }
    default:
      return { ...base, tone: 'green', word: 'Ready', says: 'Ready to print', what: i.detail, action: 'Print a model', actionId: 'print_model', rank: 4 }
  }
}

/** A queued print set up for a printer and waiting for its bed (design/bench-queue/, Queue A): that printer's tile asks
 *  for the bed, beside whoever else needs a person. */
export interface QueuedTile { id: string; printer: string | null; name: string; copies: number; state: string; bed?: boolean }
export function withQueue(tiles: Tile[], queue: QueuedTile[]): Tile[] {
  return tiles.map((t) => {
    const q = queue.find((x) => x.state === 'ready' && x.printer === t.id)
    if (!q || t.tone === 'off' || t.rank < 2) return t
    return { ...t, tone: 'amber', word: 'Next up', says: 'Clear the bed', what: `${queueTitle(q)} · from the queue`,
             action: "It's clear, start", actionId: null, rank: 1, frac: 0, thumbnail: null, queued: q.id, queuedName: q.name }
  })
}

/** The order never changes under a finger: needs you, then printing by finish, then ready, then off. */
export function ordered(printers: BenchPrinter[]): Tile[] {
  return printers.map(tileOf).sort((a, b) =>
    a.rank - b.rank || (a.rank === 3 ? (a.remaining ?? 9e9) - (b.remaining ?? 9e9) : 0) || a.name.localeCompare(b.name))
}

/** How big each printer is drawn: big tiles up to four, compact tiles up to nine, then rows. */
export type Size = 'big' | 'compact' | 'rows'
export function sizeFor(on: number): Size {
  return on <= 4 ? 'big' : on <= 9 ? 'compact' : 'rows'
}

const NUMBERS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']
const count = (n: number) => NUMBERS[n] ?? String(n)
const and = (names: string[]) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`)

/** The sentence across the top: who needs you, and when the next print is done. A guest reads it about the person who
 *  invited them (`waitingFor`): "Two are waiting for Alex: …". */
export function sentence(tiles: Tile[], waitingFor?: string): string {
  const on = tiles.filter((t) => t.tone !== 'off')
  if (!on.length) return tiles.length ? 'No printer is on.' : 'No printers yet.'
  const need = on.filter((t) => t.rank <= 2)
  const next = on.find((t) => t.rank === 3 && t.says.startsWith('Done at'))
  const then = next ? ` ${next.name} is ${next.says.replace('Done at', 'done at')}.` : ''
  const w = waitingFor
  if (need.length === 1 && need[0].queued) {
    return w ? `${need[0].name} is waiting for ${w} to clear its bed.${then}`
      : `${need[0].name} is next: clear its bed to start the ${need[0].queuedName!.toLowerCase()}.${then}`
  }
  if (need.length === 1) return `${need[0].name} ${need[0].tone === 'red' ? 'stopped' : w ? `is waiting for ${w}` : 'needs you'}.${then}`
  if (need.length) return `${count(need.length)} ${w ? `are waiting for ${w}` : 'need you'}: ${and(need.map((t) => t.name))}.${then}`
  const calm = w ? 'Nothing is waiting for anyone.' : 'Nothing needs you.'
  if (next) return `${calm}${then}`
  return on.every((t) => t.rank === 4) ? 'Everything is ready to print.' : calm
}

/** The line at the foot for the printers that are off: "2 off · Kobra 3 #2 · Monoprice SLA". */
export function offLine(tiles: Tile[]): string | null {
  const off = tiles.filter((t) => t.tone === 'off').map((t) => t.name)
  return off.length ? [`${off.length} off`, ...off].join(' · ') : null
}
