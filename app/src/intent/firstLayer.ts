// First layer: squish more, squish less (design/first-layer/, B, picked 3 October 2026).
// The words and drawings the sheet, the end-of-print card and Care share. The engine
// (printer/elyir_bench_intent.py, _first_layer_view) decides when each is offered; this only says how.

import type { Intent, IntentFirstLayer } from './types'

export type BeadKind = 'far' | 'right' | 'close'

/** A line seen end on, three ways: what a person actually judges. */
export const BEADS: { kind: BeadKind; title: string; note: string }[] = [
  { kind: 'far', title: 'Too far', note: 'Round, with gaps' },
  { kind: 'right', title: 'Right', note: 'Flat and joined' },
  { kind: 'close', title: 'Too close', note: 'Thin, see-through' },
]

export const BEAD_VIEWBOX = '0 0 96 56'
const Y0 = 46   // the top of the bed in the drawing

/** The drawing, as SVG elements on a 96 × 56 box: the bed, then three lines of plastic. The same shapes as the boards. */
export function beadShapes(kind: BeadKind): { tag: 'ellipse' | 'rect' | 'path'; attrs: Record<string, string | number> }[] {
  const bed = { tag: 'rect' as const, attrs: { x: 0, y: Y0, width: 96, height: 10, rx: 2, class: 'bed' } }
  const lines = [0, 1, 2].map((i) => {
    if (kind === 'far') return { tag: 'ellipse' as const, attrs: { cx: 18 + i * 30, cy: Y0 - 9, rx: 11, ry: 9, class: 'line' } }
    if (kind === 'right') return { tag: 'rect' as const, attrs: { x: 4 + i * 30, y: Y0 - 9, width: 32, height: 9, rx: 4.5, class: 'line' } }
    return { tag: 'path' as const, attrs: { d: `M${2 + i * 30} ${Y0} q4 -7 8 -4 q7 -2 13 0 q5 -3 9 4 z`, class: 'line thin' } }
  })
  return [bed, ...lines]
}

export const SHEET_TITLE = 'How does the first line look?'

/** The panel has room to say where to look; the phone has the camera for that. */
export function sheetSub(panel: boolean): string {
  return panel ? "Look at the line going down now. Move it until it's flat and joined." : "Move it until it's flat and joined."
}

/** "Check the first layer" on Now: layers 1 to 3 of a print, where both buttons may be pressed. */
export function checkShown(intent: Intent | null | undefined, allowed: (action: string) => boolean): boolean {
  const adj = intent?.first_layer?.adjust
  return !!adj && intent?.state === 'printing' && allowed('squish_more') && allowed('squish_less')
}

/** Further / Closer is pressable: offered by the engine (not at the half-millimetre limit) and nothing else running. */
export function canPress(fl: IntentFirstLayer | null | undefined, id: 'squish_less' | 'squish_more', busy: string | null): boolean {
  return !busy && !!fl?.adjust?.actions.some((a) => a.id === id)
}

/** Care › Printer › First layer, the line under the name. */
export function keptLine(fl: IntentFirstLayer | null | undefined, printer: string): string {
  const k = fl?.kept
  if (!fl || !fl.can_keep || !k) return "This printer can't keep a first layer yet."
  if (!k.z) return `As ${printer} finds it. Change it from Now while a print's first layers go down.`
  const when = k.at ? `, kept ${dayOf(k.at)}` : ''
  const line = `${k.words} (${k.mm})${when}.`
  if (k.used) return line
  return `${line} Not used: it was kept ${k.against === 'tap' ? 'while' : 'before'} ${printer} found its own first layer.`
}

/** Care says once where a kept first layer lives (design/first-layer-sheets/: the Reddit question). */
export const WHERE_KEPT = "Saved on the printer, in Klipper's variables file. printer.cfg isn't changed."

/** A sheet's value in Care: "A little closer (−0.050 mm), kept 22 October." */
export function sheetLine(s: { words: string; mm: string; at: string | null }): string {
  return `${s.words} (${s.mm})${s.at ? `, kept ${dayOf(s.at)}` : ''}.`
}

/** The Sheet row on Print: which sheet's first layer this print uses. `""` is any other sheet. */
export function sheetChoice(name: string): string {
  return name || 'Another sheet'
}

export function sheetNote(opt: { name: string; words: string; mm: string } | undefined, others: string[]): string {
  if (!opt) return ''
  const how = `${opt.words} (${opt.mm})`
  return opt.name ? `${how}. Same as last time.` : `${how}: not ${others.join(' or ')}.`
}

function dayOf(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })
}
