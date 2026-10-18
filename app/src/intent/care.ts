// The maintenance part of the intent object (printer/elyir_bench_care.py builds it).

export interface CareItem {
  id: string
  name: string
  note: string
  due: boolean
  snoozed: boolean
  progress: number   // 0..1 of the nearest reminder
  label: string      // e.g. "112 of 150 print hours"
}

export interface CareSummary {
  items: CareItem[]
  due: number
  hint: string | null   // one line for the Ready screen, only while idle
}

/** The care summary, or null when the printer's intent layer predates it. */
export function careOf(intent: unknown): CareSummary | null {
  return (intent as { care?: CareSummary } | null)?.care ?? null
}
