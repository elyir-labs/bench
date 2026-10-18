// Which screen pressed a button, sent with every intent action so the printer's log can say who
// stopped a print (after an untraceable Stop now on workshop, 3 October 2026). The printer adds the
// connection's address and browser itself, and the door names the paired phone when it's away.
// Pure, so tests/hold.test.ts can pin it; the store passes in where the app is running.

export function sourceOf(where: { embedded: boolean; panel: boolean; away: boolean }): string {
  if (where.embedded) return where.away ? 'printers app, away' : 'printers app'
  if (where.panel) return 'panel'
  return where.away ? 'phone or computer, away' : 'phone or computer'
}
