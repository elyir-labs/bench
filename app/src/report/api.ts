// The printer's door gathers and sends a report (`elyir-bench report`); an idea typed on a phone that isn't paired goes
// from bench.elyir.com/write, which the panel's code opens with the printer named (design/report/, B).
import { BASE } from '@/base'
import { authHeaders } from '@/auth'
import type { ReportContext, ReportKind, ReportPreview } from './words'

const demo = import.meta.env.VITE_DEMO === '1'
const sample: ReportPreview = { kind: 'wrong', printer: { name: 'Workshop', release: '2026.10.18', board: 'Raspberry Pi 5' },
  files: ['config/elyir-bench.conf', 'config/printer.cfg', 'logs/klippy.log', 'logs/moonraker.log', 'state/install-check.txt'],
  bundle_bytes: 182_000 }

/** What would go, sending nothing. Null when the printer can't say (an older release, no door). */
export async function previewReport(kind: ReportKind): Promise<ReportPreview | null> {
  if (demo) return { ...sample, kind }
  try {
    const r = await fetch(`${BASE}/door/report?kind=${kind}`, { cache: 'no-store', headers: authHeaders() })
    return r.ok ? await r.json() : null
  } catch {
    return null
  }
}

/** Sends it; the answer is the code to quote in an email. */
export async function sendReport(body: { kind: ReportKind; note?: string; email?: string; details?: boolean;
  context?: ReportContext | null }): Promise<string> {
  if (demo) return new Promise((done) => setTimeout(() => done('R-DEMO'), 900))
  let r: Response
  try {
    r = await fetch(`${BASE}/door/report`, {
      method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
  } catch {
    throw new Error("The printer couldn't be reached. Try again in a moment.")
  }
  const got = await r.json().catch(() => ({}))
  if (!r.ok || !got.code) throw new Error(got.message || "It wasn't sent. Try again in a moment.")
  return got.code
}
