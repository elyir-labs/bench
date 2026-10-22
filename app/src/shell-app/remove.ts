// Taking a printer out of the Printers app (design/printers-remove/, A, picked 22 October 2026): the picked boards
// are the spec. Remove always takes it off this phone's list; when the printer answers it may also take this phone
// off the printer (DELETE /door/me), on by default.

import type { LivePrinter } from './printers'

/** reachable: it answers, so it can forget this phone too. gone: it can't be reached. dropped: it took this phone off. */
export type RemoveCase = 'reachable' | 'gone' | 'dropped'

export function caseOf(p: Pick<LivePrinter, 'reach' | 'base'>): RemoveCase {
  if (p.reach === 'unpaired') return 'dropped'
  return (p.reach === 'home' || p.reach === 'away') && p.base ? 'reachable' : 'gone'
}

export interface SheetWords {
  title: string
  body: string
  note: string | null
  offer: string | null       // the switch's label, when there is one
  offerSub: string | null
}

export function sheetWords(name: string, c: RemoveCase): SheetWords {
  const title = `Remove ${name} from this phone?`
  if (c === 'reachable') {
    return { title, body: `It goes from your list here. ${name} keeps its prints, files and other phones.`, note: null,
      offer: `Also take this phone off ${name}`, offerSub: `${name} forgets this phone. To use it here again, scan its code once more.` }
  }
  const note = c === 'gone'
    ? `${name} can't be reached, so it will still know this phone. To take it off there too, use Care › Phones on its screen.`
    : `${name} already took this phone off, so nothing changes on it.`
  return { title, body: 'It goes from your list here.', note, offer: null, offerSub: null }
}

/** Undo only puts back what this phone changed: never once the printer forgot it too, nor for one that had already. */
export function canUndo(c: RemoveCase, alsoOff: boolean, stillKnown: boolean): boolean {
  if (c === 'dropped') return false
  return !(c === 'reachable' && alsoOff) || stillKnown
}

export function toastWords(name: string, stillKnown: boolean): string {
  return stillKnown
    ? `${name} is off this phone. It may still know this phone: Care › Phones on its screen takes it off there.`
    : `${name} is off this phone.`
}
