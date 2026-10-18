// Press and hold for the actions that end a print (decided 3 October 2026, AGENTS.md section 2):
// a brush against the panel, or a stray tap on a phone, must never end a long print.
// Pure, so tests/hold.test.ts can pin it. HoldButton.vue does the pressing.

/** How long a press has to last. Long enough that a brush can't do it, short enough for a real stop. */
export const HOLD_MS = 1000

/** "Stop this print" → "Hold to stop this print". */
export function holdLabel(label: string): string {
  return `Hold to ${label.charAt(0).toLowerCase()}${label.slice(1)}`
}

/** What a press that let go early says. */
export const HOLD_HINT = 'Keep holding to stop'
