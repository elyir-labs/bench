// Move and heat by hand (design/hands-on/, C, picked 18 October 2026): the jobs first, the controls one tap
// further. The printer does the steps (printer/elyir_bench_intent.py, IntentTracker.hands_input); this is the
// words, which follow what moves when Z goes up, and what each tap sends.
//
// Pure, so tests/hands.test.ts can pin it; Care, the sheet and Now use it.

export type ZMoves = 'head' | 'bed'

export interface HandsPreset { material: string; temp: number }

/** The intent's hands view (IntentTracker._hands_view). */
export interface HandsView {
  why_not: string | null
  z_moves: ZMoves
  /** False for a printer that takes heater settings only (a Kobra over Anycubic's LAN mode). */
  can_move?: boolean
  homed: boolean
  homing: boolean
  position: { x: number; y: number; z: number } | null
  limits: { min: number[]; max: number[] }
  steps: number[]
  /** The nozzle is hot enough for Klipper to push filament (its can_extrude). */
  can_push?: boolean
  pushes?: number[]
  material: string | null
  clean_temp: number
  nozzle_presets: HandsPreset[]
  bed_presets: HandsPreset[]
  held: { kind: 'clean' | 'nozzle' | 'clear'; target?: number; material?: string; z?: number; minutes: number | null } | null
  heat: ('nozzle' | 'bed')[]
}

export interface Job {
  id: 'clear' | 'clean' | 'nozzle' | 'bed' | 'motors' | 'move'
  title: string
  line: string
  /** The intent action a tap sends; null opens something instead. */
  action: string | null
  args?: Record<string, unknown>
}

/** The jobs, in the order drawn on design/hands-on/'s C board. */
export function jobs(h: Pick<HandsView, 'z_moves' | 'material' | 'clean_temp' | 'can_move'>): Job[] {
  const m = h.material ?? 'PLA'
  const all: Job[] = [
    { id: 'clear', title: 'Get at the bed', line: h.z_moves === 'bed' ? 'Lowers the bed out of the way' : 'Raises the head out of the way', action: 'hands_clear' },
    { id: 'clean', title: 'Clean the nozzle', line: `Hot for ${m}, at the front`, action: 'hands_clean' },
    { id: 'nozzle', title: 'Heat the nozzle', line: 'To push filament through or pull it', action: 'hands_nozzle' },
    { id: 'bed', title: 'Heat the bed', line: 'Warm up for a material', action: null },
    { id: 'motors', title: 'Let go of the motors', line: 'Push the head by hand', action: 'hands_motors_off' },
    { id: 'move', title: 'Move it myself', line: 'Up, down, any way, any heat', action: null },
  ]
  if (h.can_move !== false) return all
  return [...all.filter((j) => j.id === 'nozzle' || j.id === 'bed'),
    { id: 'move', title: 'Set the heat', line: 'Nozzle and bed, any material', action: null }]
}

/** The two Z buttons, top first: each says what moves, and which way Z goes for it. */
export function zButtons(z: ZMoves): { label: string; arrow: 'up' | 'down'; dir: 1 | -1 }[] {
  return z === 'bed'
    ? [{ label: 'Bed up', arrow: 'up', dir: -1 }, { label: 'Bed down', arrow: 'down', dir: 1 }]
    : [{ label: 'Head up', arrow: 'up', dir: 1 }, { label: 'Head down', arrow: 'down', dir: -1 }]
}

/** The pad: arrows move the head over the bed. Up on the screen is toward the back. */
export const PAD: { arrow: 'up' | 'down' | 'left' | 'right'; axis: 'x' | 'y'; dir: 1 | -1 }[] = [
  { arrow: 'up', axis: 'y', dir: 1 }, { arrow: 'left', axis: 'x', dir: -1 },
  { arrow: 'right', axis: 'x', dir: 1 }, { arrow: 'down', axis: 'y', dir: -1 },
]

/** The Care row's second line. */
export function rowLine(h: HandsView | null | undefined, away: boolean): string {
  if (away) return 'At the printer.'
  if (!h) return "The printer isn't ready."
  return h.why_not ?? (h.can_move === false ? 'Heat the nozzle or the bed.' : 'Get at the bed, clean the nozzle, or move it yourself.')
}

/** Under the sheet's title. */
export function sheetLine(name: string, nozzle: number, bed: number): string {
  return `${name} is free. The nozzle is ${Math.round(nozzle)}°, the bed ${Math.round(bed)}°.`
}

/** Under the pad: where the head is, or why it isn't known yet. */
export function whereLine(h: Pick<HandsView, 'homed' | 'homing' | 'position'>): string {
  if (h.homing) return 'Finding home…'
  if (!h.homed || !h.position) return 'Finds home first'
  const p = h.position
  return `X ${Math.round(p.x)} · Y ${Math.round(p.y)} · Z ${fmt(p.z)}`
}

function fmt(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

/** Now's chip while a job holds the printer. */
export function heldChip(h: HandsView['held'], nozzle: number): string | null {
  if (!h) return null
  if (h.kind === 'clear') return h.z != null ? `Z ${h.z}` : null
  return `Nozzle ${Math.round(nozzle)}° of ${h.target}°`
}
