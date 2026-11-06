// The current arrangement (layout.ts), following the window as it's resized or turned.

import { computed, ref, watchEffect } from 'vue'
import { isPanel } from '@/theme'
import { layoutFor, panelFit, type Layout } from './layout'
import { benchChrome } from '@/auth'

const size = ref({ width: window.innerWidth, height: window.innerHeight })
window.addEventListener('resize', () => { size.value = { width: window.innerWidth, height: window.innerHeight } }, { passive: true })

export const layout = computed<Layout>(() => layoutFor({ panel: isPanel, bench: benchChrome, ...size.value }))

/** This is the printer's own screen, whichever arrangement it has: a tall panel is laid out as a phone but isn't one. */
export const ownScreen = computed(() => isPanel || layout.value === 'panel')

// ?panel_in: the kiosk's word for the screen's diagonal (kiosk/start.sh). The router drops the query, so a reload
// keeps it in the session, like ?lite.
const PANEL_IN = 'elyir-bench.panelInches'
function panelInches(): number | null {
  const asked = new URLSearchParams(window.location.search).get('panel_in')
  try {
    if (asked) sessionStorage.setItem(PANEL_IN, asked)
    return Number(asked ?? sessionStorage.getItem(PANEL_IN)) || null
  } catch {
    return Number(asked) || null
  }
}
const inches = isPanel ? panelInches() : null
export const fit = computed(() => panelFit({ inches, ...size.value }))
export const railed = computed(() => !!fit.value?.rail)

// On the root, not the shell: sheets are teleported to the body.
watchEffect(() => {
  const root = document.documentElement
  const f = fit.value
  if (f) root.dataset.fit = f.rail ? 'rail' : 'floor'
  else delete root.dataset.fit
  root.style.setProperty('--tap', f ? `${f.tap}px` : '0px')
  if (f?.unit) root.style.setProperty('--u', f.unit)
  else root.style.removeProperty('--u')
})

/** A mouse or trackpad (laptops). Touch screens open the camera full screen instead of in a pane. */
const fine = window.matchMedia('(pointer: fine)')
const finePointerRef = ref(fine.matches)
fine.addEventListener('change', (e) => { finePointerRef.value = e.matches })
export const finePointer = computed(() => finePointerRef.value)
