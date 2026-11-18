// Your printers follow your account (design/account-list/, A, picked 11 November 2026). The account's house holds the
// list: a printer in it that this phone doesn't have is opened with a pass from Bench Cloud (no pairing), and one this
// phone has that left the account goes from here too. Pure: the doing is in account-follow.ts.

import type { Addresses, PrinterRecord, Reach } from './printers'

export interface Door { printer: string; name: string; addresses: Addresses }
export interface AccountDevice { id: string; name: string; kind: string; door?: Door | null }
export type Have = Pick<PrinterRecord, 'id' | 'name' | 'kind' | 'account' | 'house'> & { reach?: Reach }

export interface Follow {
  letIn: AccountDevice[]                     // in the account, not (or no longer) open on this phone
  link: { id: string; device: string }[]     // on this phone already: remembered as the account's
  drop: string[]                             // on this phone as the account's, and gone from the account
}

const printersOf = (devices: AccountDevice[]) => devices.filter((d) => d.kind === 'printer')

export function follow(devices: AccountDevice[], house: string, have: Have[]): Follow {
  const mine = have.filter((p) => p.kind !== 'bench')
  const out: Follow = { letIn: [], link: [], drop: [] }
  for (const d of printersOf(devices)) {
    if (!d.door) continue                    // its door hasn't said where it answers yet
    const p = mine.find((x) => x.id === d.door!.printer)
    if (!p || p.reach === 'unpaired') out.letIn.push(d)
    if (p && (p.account !== d.id || p.house !== house)) out.link.push({ id: p.id, device: d.id })
  }
  const live = new Set(devices.map((d) => d.id))
  // only what this same house put here: signing in to another account never empties the list
  out.drop = mine.filter((p) => p.account && p.house === house && !live.has(p.account)).map((p) => p.id)
  return out
}

/** Printers on this phone that the account doesn't have yet: each joins by itself, at home. */
export function toJoin(devices: AccountDevice[], have: Have[]): Have[] {
  const known = printersOf(devices)
  return have.filter((p) => p.kind !== 'bench' && !p.account &&
    !known.some((d) => d.door?.printer === p.id || d.name === p.name))
}

export function fromAccountWords(inAccount: number, waiting: number): string | null {
  if (waiting) return `${waiting} more ${waiting === 1 ? 'joins' : 'join'} your account the next time this phone is home with ${waiting === 1 ? 'it' : 'them'}.`
  return inAccount ? `From your account · ${inAccount} ${inAccount === 1 ? 'printer' : 'printers'}` : null
}
