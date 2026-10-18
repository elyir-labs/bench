// Where the boot screen's ring stands, and the one line it may say, from what the app knows.
//
// The ring only moves when something real happens (the app's motion rule), so each stage has a
// fixed place on it. Plymouth fills it up to `handoff` while the Pi boots; the app takes it the
// rest of the way. Pure functions, no Vue: `npm test` runs them under plain Node.

export type BootStage = 'loaded' | 'connected' | 'starting' | 'ready' | 'problem'

export interface BootIntent {
  state: string
  phase?: string
  raw?: string
}

/** No progress for this long and the boot screen says, in one line, what it is waiting for. */
export const STALL_MS = 4000
/** Stalled this long, it steps aside for the app's own Starting up screen, which can say more. */
export const GIVE_UP_MS = 30000

export function stageOf(connected: boolean, intent: BootIntent | null): BootStage {
  if (!connected) return 'loaded'
  if (!intent) return 'connected'
  if (intent.state === 'problem') return 'problem'
  if (intent.state === 'preparing' && intent.phase === 'starting_up') return 'starting'
  return 'ready'
}

// How far along the app's share of the ring each stage is.
const SHARE: Record<BootStage, number> = { loaded: 0.1, connected: 0.3, starting: 0.55, ready: 1, problem: 0.55 }

export function arcFor(stage: BootStage, handoff: number): number {
  return handoff + (1 - handoff) * SHARE[stage]
}

/** The line shown after a stall, in the words the intent layer uses. */
export function stallLine(stage: BootStage, intent: BootIntent | null): string {
  if (stage === 'loaded') return 'Starting the printer’s software…'
  // Klipper names the board it is waiting for: "mcu 'EBBCan': Unable to connect"
  const board = /mcu '([^']+)'/i.exec(intent?.raw ?? '')?.[1] ?? ''
  if (/ebb|tool|head|sb2040|nhk/i.test(board)) return 'Waking the print head…'
  return 'Waking the printer’s brain…'
}
