// How a printer's state reads in the list and the switcher.
import type { LivePrinter } from './printers.ts'

import { AWAY_LINE, AWAY_WORD } from './you.ts'

/** homeOnly: the house has no plan that carries its printers from away (design/one-cloud/), so out of reach means at home. */
export function statusOf(p: LivePrinter, homeOnly = false): { word: string; tone: 'calm' | 'busy' | 'amber' | 'green' | 'red' | 'off'; line: string } {
  if (p.reach === 'checking') return { word: 'Looking…', tone: 'off', line: '' }
  if (p.reach === 'unpaired') return { word: 'Not paired', tone: 'off', line: 'This phone was removed from the printer.' }
  if (p.reach === 'offline' && homeOnly) return { word: AWAY_WORD, tone: 'off', line: AWAY_LINE }
  if (p.reach === 'offline') return { word: 'Out of reach', tone: 'off', line: "Can't reach it at home or through the internet." }
  const i = p.intent
  if (!i || !p.connected) return { word: 'Connecting…', tone: 'off', line: '' }
  const pct = Math.floor((i.job?.progress ?? 0) * 100)
  switch (i.state) {
    case 'printing': return { word: `Printing · ${pct}%`, tone: 'busy', line: i.job?.eta_clock ? `${i.job.name} · done at about ${i.job.eta_clock}` : (i.job?.name ?? '') }
    case 'preparing': return { word: i.change ? (i.change.kind === 'slot' ? 'Swapping a spool' : 'Changing filament') : (i.phase === 'carrying_on' ? 'Carrying on' : i.phase === 'power_back' ? "Power's back" : 'Getting ready'), tone: 'busy', line: i.headline }
    case 'needs_you': return { word: i.phase === 'power_hold' ? 'On battery' : 'Needs you', tone: 'amber', line: i.headline }
    case 'finished': return { word: 'Finished', tone: 'green', line: i.detail || i.headline }
    case 'problem': return { word: 'Stopped', tone: 'red', line: i.headline }
    default: return { word: 'Ready', tone: 'calm', line: i.detail }
  }
}
