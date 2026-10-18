// A printer that slices on another machine (design/slicing-elsewhere/, A): what a person is told. The slicer
// says who it is in /slice/options ({name, here}); through a printer that waits for a yes, or was told no, it
// answers 403 with {waiting | refused, slicer}; when it's off, the printer's nginx answers 503 {off, slicer}.

export interface SlicerInfo { name: string; here: boolean | null }
export type SlicerState =
  | { state: 'none' }                                   // nothing slices for this printer: no Print a model
  | { state: 'ready'; slicer: SlicerInfo | null }
  | { state: 'waiting' | 'refused'; name: string }
  | { state: 'down'; name: string | null }

export function stateFrom(status: number, contentType: string, body: any): SlicerState {
  if (status >= 200 && status < 300 && contentType.includes('text/html')) return { state: 'none' }   // the app's own page
  if (status >= 200 && status < 300) return { state: 'ready', slicer: body?.slicer ?? null }
  if (body?.waiting) return { state: 'waiting', name: String(body.slicer ?? 'the slicer') }
  if (body?.refused) return { state: 'refused', name: String(body.slicer ?? 'the slicer') }
  return { state: 'down', name: body?.slicer ?? null }
}

/** The other machine's name when it isn't this printer that slices, else null. */
export const elsewhere = (s: SlicerInfo | null | undefined): string | null => (s && s.here === false ? s.name : null)

export const askingWords = (slicer: string, printer: string) =>
  `Asking ${slicer} to slice for ${printer}, which can't do it itself. Say yes on ${slicer}'s screen.`

/** Ready's line under the time: who sliced it, when it wasn't this printer. */
export function readyNote(note: string, s: SlicerInfo | null | undefined): string {
  const other = elsewhere(s)
  if (!other) return note
  return note === 'Tap a row to change it' ? `Sliced on ${other} · tap a row to change it` : `Sliced on ${other} · ${note[0].toLowerCase()}${note.slice(1)}`
}

/** A slice that waits its turn on a slicer shared by printers: what it waits behind. */
export function waitWords(job: { state: string; ahead?: number; behind?: string | null } | null | undefined,
                          s: SlicerInfo | null | undefined): { title: string; note: string } | null {
  if (!job || job.state !== 'queued' || !job.ahead) return null
  const other = elsewhere(s)
  const behind = job.behind ?? null
  if (other) {
    return { title: `Waiting for ${other}`,
             note: behind === other ? "It's slicing one of its own first." : behind ? `It's slicing one for ${behind} first.` : 'Next in line.' }
  }
  return { title: 'Waiting to slice', note: behind ? `${behind}'s slice goes first.` : 'Next in line.' }
}

/** Care's row on a printer that slices elsewhere. Null on a printer that slices for itself. */
export function careLine(st: SlicerState, printer: string): string | null {
  if (st.state === 'ready') { const o = elsewhere(st.slicer); return o ? `${o} slices for ${printer}. Its own prints come first.` : null }
  if (st.state === 'waiting') return `Waiting for ${st.name} to say yes on its screen.`
  if (st.state === 'refused') return `${st.name} said no. ${printer} asks again tomorrow.`
  if (st.state === 'down' && st.name) return `${st.name} slices for ${printer}, and isn't answering right now.`
  return null
}

/** Care's row on the slicer: the printers that send their models here. */
export function hostLine(joined: string[], me: string): string | null {
  if (!joined.length) return null
  const who = joined.length === 1 ? joined[0] : `${joined.slice(0, -1).join(', ')} and ${joined[joined.length - 1]}`
  return `${who} send${joined.length === 1 ? 's' : ''} ${joined.length === 1 ? 'its' : 'their'} models here. ${me} slices them when it has a moment.`
}

/** The problem page when the slicer is off: its name, not an address. */
export const offTitle = (info: { slicer?: string | null; off?: boolean } | null | undefined): string | null =>
  info?.off && info.slicer ? `${info.slicer} is off.` : null
