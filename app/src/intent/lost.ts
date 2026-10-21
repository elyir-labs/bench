// A print the power took (design/power-loss/, A): its words, pure so tests/power-loss.test.ts can pin them.

import type { LostView, OutageView } from './types'

const mm = (v: number) => (Math.round(v * 10) / 10).toString()

/** "44% done · 12.2 of 28 mm" */
export function doneWords(l: LostView): string {
  return l.z != null && l.height ? `${l.pct}% done · ${mm(l.z)} of ${mm(l.height)} mm` : `${l.pct}% done`
}

/** "The top 15.8 mm prints as its own part, to glue on." */
export function restWords(l: LostView): string {
  const left = l.z != null && l.height ? ` ${mm(l.height - l.z)} mm` : ''
  return `The bottom${l.z != null ? ` ${mm(l.z)} mm` : ''} is done. The top${left} prints as its own part, to glue on.`
}

/** On the hold's ring: the battery, or how long until it carries on. */
export function holdRing(o: OutageView, nozzle: number): { value: number; text: string; label: string } {
  if (!o.back) return { value: (o.battery ?? 100) / 100, text: o.battery != null ? `${Math.round(o.battery)}%` : 'On', label: 'battery' }
  if (o.carry_in != null) return { value: 1 - o.carry_in / 30, text: `0:${String(o.carry_in).padStart(2, '0')}`, label: 'to carry on' }
  const to = o.to || 1
  return { value: Math.min(1, nozzle / to), text: `${Math.round(nozzle)}°`, label: `of ${Math.round(to)}°` }
}

/** The hold's lines, under the headline. */
export function holdFacts(o: OutageView): string[] {
  const out = []
  if (o.bed) out.push(`Bed kept at ${Math.round(o.bed)}° so the part stays stuck.`)
  if (o.runtime_min) out.push(`Battery: about ${o.runtime_min} min like this.`)
  out.push(o.held === 'print' ? 'It carries on by itself when the power is back.'
    : 'It stays paused when the power comes back.')
  return out
}
