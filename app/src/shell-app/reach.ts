// When a printer's live connection isn't up, what the list does about it (printers.ts connect()). Pure, for
// tests/printers-reach.test.ts.

export const NEVER_UP_MS = 8000     // a connection that hasn't come up in this long: try the printer's other name
export const LOOK_AGAIN_MS = 60_000 // still down on both names: look for the printer again this often

export interface LinkState {
  connected: boolean
  everUp: boolean     // this connection came up at least once
  sinceStart: number  // ms since this connection was made
  gaveUp: boolean     // its other name was already tried
  sinceLook: number   // ms since the printer was last looked for
}

/** 'other': try the other name; 'again': look for the printer again; null: leave it. A connection that was up and
 *  dropped is not one that never came up: the drop looks again on its own (27 October 2026: one Wi-Fi blip at home
 *  sent every Kobra to the relay, where nothing then looked at home again). */
export function nextStep(s: LinkState): 'other' | 'again' | null {
  if (s.connected) return null
  if (!s.everUp && !s.gaveUp && s.sinceStart > NEVER_UP_MS) return 'other'
  if (s.gaveUp && s.sinceLook > LOOK_AGAIN_MS) return 'again'
  return null
}

export const HOME_LOOK_MS = 30_000  // on the public name with home known: look for it at home this often

export interface AwayState {
  away: boolean        // connected through the public name
  connected: boolean
  homeKnown: boolean   // the printer has a home name
  homeAvoided: boolean // its home name answered but the live connection never came up there, lately
  sinceHomeLook: number
}

/** On the public name and working, look at home again now and then: a slow first look at home (a phone waking, a
 *  Wi-Fi moment) otherwise leaves a printer "away" in the house for as long as the app stays open. */
export function lookHomeNow(s: AwayState): boolean {
  return s.away && s.connected && s.homeKnown && !s.homeAvoided && s.sinceHomeLook > HOME_LOOK_MS
}

// "Look on this Wi-Fi" (design/printers-away/, A + B): the sheet's and the note's words for one printer or several.
const named = (names: string[], several: string) => (names.length === 1 ? names[0] : several)

export function awayTitle(names: string[]): string {
  return `${named(names, 'Your printers')} ${names.length === 1 ? 'is' : 'are'} reached through the internet`
}
export function notFoundTitle(names: string[]): string {
  return `Couldn't find ${named(names, 'your printers')} on this Wi-Fi`
}
export function stillAway(names: string[]): string {
  return `Until then ${names.length === 1 ? `${names[0]} works` : 'they work'} from away: watch, pause, stop.`
}
export function foundWords(names: string[]): string {
  const who = names.length === 1 ? names[0] : names.length === 2 ? `${names[0]} and ${names[1]}` : `${names.length} printers`
  return `Found ${who} on your Wi-Fi`
}
