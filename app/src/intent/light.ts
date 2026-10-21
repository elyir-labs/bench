// The chamber light (design/chamber-light/, A): a bulb on the camera picture where Now shows one, otherwise in
// the top bar. A printer with two lights asks once which one lights the bed (LightSheet).

import { ref } from 'vue'

export interface LightView {
  on: boolean
  /** a printer with more than one light that hasn't said which: each, and whether it's on */
  ask: { name: string; label: string; on: boolean }[] | null
}

/** Where the switch goes: on the camera when Now shows one; the top bar where there is one; else at the top of
 *  Now (inside the Printers app, whose own bar names the printer). */
export function lightPlace(o: { light: boolean; cameraOnNow: boolean; embedded: boolean }): 'camera' | 'top' | 'now' | null {
  if (!o.light) return null
  if (o.cameraOnNow) return 'camera'
  return o.embedded ? 'now' : 'top'
}

/** Now is showing the camera (NowScreen says), so the shell leaves the switch to it. */
export const nowCameraShown = ref(false)
/** The "which one lights the bed?" sheet. */
export const lightAskOpen = ref(false)

export const BULB = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.4 1.1 2.2h5c0-.8.4-1.6 1.1-2.2A6 6 0 0 0 12 3z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>'
