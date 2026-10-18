// Keeps the printer's camera list current: asked for once connected, and again whenever
// Moonraker says the webcams changed. Shared by every component that shows a camera.

import { computed, ref, watch } from 'vue'
import { withToken } from '@/auth'
import { useIntentStore } from '@/intent/store'
import { toCameras, type Camera, type MoonrakerWebcam } from './cameras'
import { door } from '@/door'

const raw = ref<MoonrakerWebcam[]>([])
let started = false

/** Go easy on data: reached from away through the door, or the browser says Save-Data or cellular.
 *  The camera then shows a still every 2 s; full screen stays live because someone asked to watch. */
export function saveData(): boolean {
  if (door.away) return true
  const c = (navigator as any).connection
  return !!c && (c.saveData === true || c.type === 'cellular')
}

export function useCameras() {
  const store = useIntentStore()

  if (!started) {
    started = true
    const load = async () => {
      try {
        const r = await store.call<{ webcams: MoonrakerWebcam[] }>('server.webcams.list')
        raw.value = r?.webcams ?? []
      } catch {
        // a Moonraker without webcams support, or not connected yet: no camera
      }
    }
    watch(() => store.connected, (c) => { if (c) load() }, { immediate: true })
    store.on('notify_webcams_changed', load)
  }

  const cameras = computed<Camera[]>(() => {
    const http = store.endpoint?.http
    // embedded in the shell: the camera takes the token in its address (an <img> can't send a header)
    return http ? toCameras(raw.value, window.location.href, http).map((c) => ({ ...c, stream: withToken(c.stream), snapshot: withToken(c.snapshot) })) : []
  })
  return { cameras }
}
