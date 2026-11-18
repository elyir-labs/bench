// A printer the Bench Box added beside one this phone has (design/new-kobra/, B, picked 7 November 2026): the box
// carried this phone to it, and the sibling's door lists it in /door/me. The phone adds it with the token it already
// holds for that sibling, once: a printer taken off this phone (Remove or Not mine) never comes back this way.

import type { Addresses, PrinterRecord } from './printers'

export const NEW_FOR_MS = 24 * 3600_000

export interface Joined {
  id: string
  name: string
  addresses: Addresses
  at: number               // seconds, the box's clock
}

/** The records to add: not on this phone and never offered before. */
export function toAdd(joined: Joined[] | undefined, token: string, have: Set<string>, offered: Set<string>, now: number): PrinterRecord[] {
  return (joined ?? [])
    .filter((j) => j && j.id && !have.has(j.id) && !offered.has(j.id))
    .map((j) => ({ id: j.id, name: j.name, addresses: { home: j.addresses?.home ?? null, away: j.addresses?.away ?? null },
      token, added: now, joined: Math.min(now, Math.round(j.at * 1000)) }))
}

/** Records to drop: the box took the printer off the bench, and this phone only had it because the box carried it here
 *  with this door's token. One the phone paired with itself stays. */
export function toDrop(left: string[] | undefined, token: string, have: Pick<PrinterRecord, 'id' | 'token' | 'joined'>[]): string[] {
  const gone = new Set(left ?? [])
  return have.filter((p) => gone.has(p.id) && !!p.joined && p.token === token).map((p) => p.id)
}

/** Shown under New on your bench, with Not mine, for a day after it joined. */
export function isNew(p: Pick<PrinterRecord, 'joined'>, now: number): boolean {
  return !!p.joined && now - p.joined < NEW_FOR_MS
}

export function notMineWords(name: string, why: 'confirm' | 'unreachable' | 'refused' | 'failed'): string {
  return {
    confirm: `Take ${name} off the Bench Box? It won't be added again.`,
    unreachable: `${name} can't be reached yet. Try again in a minute, or take it off on the Bench Box's screen.`,
    refused: `Only Remove works for ${name} now: Not mine is for its first days.`,
    failed: `The Bench Box didn't answer. Try again.`,
  }[why]
}
