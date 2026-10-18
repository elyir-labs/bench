// Up next: what fills Now under the spools when the printer is Ready, off the panel
// (design/ready-phone/, C, picked 5 October 2026), on the phone only: a tablet or laptop shows the Print
// tab beside Now, and the rows would repeat it. Up to three rows, each the next thing you'd
// likely do, in this order:
//   1. a file sent from the slicer since the last print (the newest one)
//   2. Print again: the last thing printed, while its file is on the printer (not when the new file is
//      the same model sliced again: that one is what you'd print)
//   3. Care that's due
// With nothing printed and nothing new, the second row is Print a model. Only what applies is shown.
// The panel keeps its own Print again card.
//
// Pure, so tests/up-next.test.ts can pin it; NowScreen feeds it from useLibrary and the intent's care.
import { ago, isNew, metaLine, onPrinter, slicerShort, type Item } from './library.ts'
import type { CareItem } from '../intent/care.ts'

export const UP_NEXT_MAX = 3

export type UpRow =
  | { kind: 'new' | 'again'; item: Item; label: string; name: string; meta: string }
  | { kind: 'care'; care: CareItem; label: string; name: string; meta: string }
  | { kind: 'start'; label: string; name: string; meta: string }

/** "PLA", or "PLA + PETG" for a file that uses two. */
function material(i: Item): string {
  const types = [...new Set(String(i.meta?.filament_type ?? '').split(';').map(t => t.trim()).filter(Boolean))]
  return types.slice(0, 2).join(' + ')
}

const meta = (i: Item) => [metaLine(i), material(i)].filter(Boolean).join(' · ')

export function upNext(items: Item[], care: CareItem[] | null | undefined, now: number): UpRow[] {
  const rows: UpRow[] = []
  // the last print started, finished or not; a file sent before it isn't news any more
  const lastStart = items.reduce<number | null>((m, i) => (i.lastJob != null && (m == null || i.lastJob > m) ? i.lastJob : m), null)
  const fresh = onPrinter(items).find(i => isNew(i, now) && (lastStart == null || (i.modified ?? 0) > lastStart))
  if (fresh) {
    // short enough for a phone's row: "New from Prusa · 6 min ago"
    const from = slicerShort(fresh.slicer)?.replace(/^PrusaSlicer$/i, 'Prusa')
    const when = ago(fresh.modified!, now)
    rows.push({ kind: 'new', item: fresh, label: from ? `New from ${from} · ${when}` : `New · sent ${when}`, name: fresh.name, meta: meta(fresh) })
  }
  const last = items.filter(i => i.lastJob != null).sort((a, b) => (b.lastJob ?? 0) - (a.lastJob ?? 0))[0]
  if (last?.onPrinter && last.name !== fresh?.name) {
    const finished = last.lastPrinted != null && last.lastPrinted >= (last.lastJob ?? 0)
    const label = finished ? `Print again · ${ago(last.lastPrinted!, now)}` : `Try again · stopped ${ago(last.lastJob!, now)}`
    rows.push({ kind: 'again', item: last, label, name: last.name, meta: meta(last) })
  } else if (!last && !fresh) {
    rows.push({ kind: 'start', label: 'Nothing printed yet', name: 'Print a model', meta: 'An STL or 3MF file' })
  }
  const due = (care ?? []).find(c => c.due && !c.snoozed)
  if (due) rows.push({ kind: 'care', care: due, label: 'Care · due now', name: due.name, meta: due.label })
  return rows.slice(0, UP_NEXT_MAX)
}
