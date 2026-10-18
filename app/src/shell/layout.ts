// Which arrangement a screen gets (design/responsive/, B "Now stays with you", chosen 1 Oct 2026).
//
//   panel    the printer's own 800x480 screen: unchanged, Now is a tab
//   compact  phones (under 600 px wide): Now is a tab, and a Now bar rides above the tabs elsewhere
//   stacked  tablets held upright: Now is a card across the top, the other tabs below it
//   split    tablets on their side, laptops: Now is a column on the left, the other tabs beside it
//
// Pure, so tests/layout.test.ts can pin it; useLayout.ts makes it follow the window.

export type Layout = 'panel' | 'compact' | 'stacked' | 'split'

export const COMPACT_MAX = 600
export const STACKED_MAX = 1024

export function layoutFor(o: { panel: boolean; width: number; height: number; bench?: boolean }): Layout {
  if (o.panel) return 'panel'
  // inside a Bench Box: the box has the sections, so Now is one of them, as on the panel (design/bench-box/, D)
  if (o.bench && o.width >= COMPACT_MAX) return 'panel'
  if (o.width < COMPACT_MAX) return 'compact'
  if (o.width < STACKED_MAX && o.height > o.width) return 'stacked'
  return 'split'
}

/** Off the panel the type scale is fixed per arrangement instead of growing with the window
 *  (the --u unit in elyir-bench.css; 1 is the panel's own design size). */
export function unitFor(l: Layout): string | null {
  switch (l) {
    case 'compact': return '0.62px'
    case 'stacked': return '0.78px'
    case 'split': return '0.74px'
    default: return null
  }
}
