// Tell Elyir something (design/report/, B): a problem with the printer's report, or an idea, a request, anything.
// The words and the pure parts; src/report/api.ts talks to the printer's door. Pinned by tests/report.test.ts.
import type { Intent } from '@/intent/types'

export type ReportKind = 'wrong' | 'idea' | 'other'

export interface ReportPrinter { name?: string; release?: string; board?: string; os?: string }
export interface ReportPreview { kind: ReportKind; printer: ReportPrinter; files?: string[]; bundle_bytes?: number }
export interface ReportContext { headline: string; detail?: string; at: string; job?: string; progress?: number }

export const KINDS: { kind: ReportKind; title: string; line: string }[] = [
  { kind: 'wrong', title: "Something's wrong", line: 'What it was doing, its logs and settings go with it. You see them first.' },
  { kind: 'idea', title: 'An idea or a request', line: 'Your words. Nothing from the printer unless you add it.' },
  { kind: 'other', title: 'Something else', line: 'Anything at all, the same way.' },
]

/** What goes with a report, in the order the sheet lists it. */
export function goesWith(context: ReportContext | null): { title: string; line: string }[] {
  return [
    ...(context ? [{ title: 'The minutes before it stopped', line: "temperatures, and Klipper's own words" }] : []),
    { title: 'The last day of logs', line: 'from Klipper, Moonraker and Elyir Bench' },
    { title: 'This printer', line: 'its board, system and release, and the install check' },
    { title: 'Its settings', line: "without passwords, keys or the Wi-Fi's details" },
  ]
}

/** What the problem screen showed, for a report sent from it: the moment, not just the printer. */
export function contextOf(intent: Intent | null, now: Date = new Date()): ReportContext | null {
  if (!intent || intent.state !== 'problem') return null
  const at = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase().replace(/\s/g, ' ')
  return {
    headline: intent.headline, ...(intent.detail ? { detail: intent.detail } : {}), at,
    ...(intent.job?.name ? { job: intent.job.name, progress: Math.round((intent.job.progress ?? 0) * 100) } : {}),
  }
}

/** "11:14 am, 40% into Phone stand" under the problem's headline on the sheet. */
export function momentLine(c: ReportContext): string {
  return c.job ? `${c.at}, ${c.progress ?? 0}% into ${c.job}` : c.at
}

/** The address the panel's code opens: the public form, the printer named so the message says which. */
export function writeUrl(kind: ReportKind, p: ReportPrinter, site = 'https://bench.elyir.com'): string {
  const q = new URLSearchParams({ kind, ...(p.name ? { printer: p.name } : {}), ...(p.release ? { release: p.release } : {}),
    ...(p.board ? { board: p.board } : {}) })
  return `${site}/write#${q.toString()}`
}

