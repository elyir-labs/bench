// The one-spool page (design/one-spool/, direction B "The spool is the page", chosen 2 October 2026):
// what a printer without a filament unit says about its spool, and what tapping a material or a
// colour sends. Kept apart from the component so tests can pin it.
import type { IntentSpool } from '../../intent/types.ts'
import { nearestColor } from './palette.ts'

export type Look = 'solid' | 'guess' | 'changed' | 'unknown' | 'empty'

export interface QuickAnswer {
  label: string
  color: string | null
  material: string
}

export interface OneSpoolView {
  title: string
  meta: string
  pill: 'Guess' | 'Spoolman' | null
  look: Look
  /** The guess or "New filament?", above the spool. Its answers are one tap. */
  question: null | {
    tone: 'plain' | 'amber'
    headline: string
    detail: string
    confirm: QuickAnswer | null      // "That's right"
    answers: QuickAnswer[]           // "Same as before" first, then spools that were on before
  }
  /** Which material chip and palette colour show as picked; a guess shows them dashed. */
  material: string | null
  color: string | null
  maybe: boolean
  /** The spool's own colour, kept when only the material is tapped (it may not be in the palette). */
  keepColor: string | null
  /** Spoolman's spool is changed in Spoolman. */
  editable: boolean
  note: string
}

/** "3 days ago", "yesterday", "2 hours ago", "just now". */
export function ago(iso: string | null | undefined, now: Date): string | null {
  if (!iso) return null
  const then = new Date(iso)
  const s = (now.getTime() - then.getTime()) / 1000
  if (!isFinite(s)) return null
  if (s < 90) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`
  if (s < 2 * 3600) return 'an hour ago'
  const days = Math.round((startOfDay(now) - startOfDay(then)) / 86400000)
  if (days <= 0) return `${Math.floor(s / 3600)} hours ago`
  if (days === 1) return 'yesterday'
  return `${days} days ago`
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

export function oneSpoolView(s: IntentSpool, now: Date): OneSpoolView {
  const when = ago(s.since, now)
  const recent: QuickAnswer[] = (s.recent ?? [])
    .filter(r => r.material)
    .map(r => ({ label: r.name ?? r.material!, color: r.color, material: r.material! }))
  const base = { pill: null, question: null, maybe: false, editable: true, keepColor: null,
                 note: 'Load a different spool, then tap what it is. Each tap saves. Nothing will move.' }

  if (s.source === 'spoolman') {
    return { ...base, title: s.name ?? 'Unknown filament', look: 'solid', pill: 'Spoolman',
             meta: [s.grams ? `About ${s.grams} g left` : null, 'from Spoolman'].filter(Boolean).join(' · '),
             material: s.material, color: nearestColor(s.color), editable: false,
             note: 'To change it, pick a different spool in Spoolman.' }
  }
  if (s.status === 'empty') {
    return { ...base, title: 'Empty', look: 'empty',
             meta: s.name ? `Nothing in the head. Last was ${s.name}.` : 'Nothing in the head.',
             material: null, color: null,
             note: 'Load a spool, then tap what it is. Nothing will move.' }
  }
  if (s.changed) {
    const was = s.was?.material ? s.was : null
    const answers = [
      ...(was ? [{ label: 'Same as before', color: was.color, material: was.material! }] : []),
      ...recent,
    ]
    return { ...base, title: 'New filament?', look: 'changed', meta: '',
             question: { tone: 'amber', headline: 'New filament?',
                         detail: was?.name ? `It came out and went back in. Was ${was.name}.` : 'It came out and went back in.',
                         confirm: null, answers },
             material: null, color: null }
  }
  if (s.source === 'guess' && s.material) {
    const from = s.guess_from ? ` from your last print, ${s.guess_from}` : ' from your last print'
    return { ...base, title: `Probably ${s.name}`, look: 'guess', pill: 'Guess',
             meta: `A guess${from}`,
             question: { tone: 'plain', headline: `Is it ${s.name}?`,
                         detail: `That's my guess${from}. If not, tap what it is.`,
                         confirm: { label: "That's right", color: s.color, material: s.material }, answers: [] },
             material: s.material, color: nearestColor(s.color), keepColor: s.color, maybe: true }
  }
  if (s.source === 'told' && s.material) {
    return { ...base, title: s.name ?? s.material, look: 'solid',
             meta: when ? `You told me ${when}` : 'You told me',
             material: s.material, color: nearestColor(s.color), keepColor: s.color }
  }
  return { ...base, title: 'Unknown filament', look: 'unknown',
           meta: 'Tap what it is. Nothing will move.', material: null, color: null }
}

/**
 * What a tap on a material chip or a colour saves. A material saves at once, keeping the colour
 * that's shown. A colour needs a material: with none shown it waits for one (null = nothing to send).
 */
export function tapToSave(view: OneSpoolView, tap: { material?: string; color?: string }, pendingColor: string | null)
  : { send: { material: string; color: string | null } | null; pendingColor: string | null } {
  const color = tap.color ?? pendingColor ?? view.keepColor
  const material = tap.material ?? view.material
  if (!material) return { send: null, pendingColor: tap.color ?? pendingColor }
  return { send: { material, color }, pendingColor: null }
}

/** Undo is offered only when it can put back exactly what was there: something you'd said. */
export function undoTarget(s: IntentSpool): QuickAnswer | null {
  if (s.source !== 'told' || s.changed || s.status === 'empty' || !s.material) return null
  return { label: s.name ?? s.material, color: s.color, material: s.material }
}
