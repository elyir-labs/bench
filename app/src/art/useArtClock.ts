// The ambient clock behind the ring's pictures: heat rising, a probe tapping, the nozzle going to and
// fro. It runs only while the printer is doing something (motion means activity, the same rule as
// the spool ring), only while the page is visible, and not at all with reduced motion. Ten frames a
// second is plenty for a drawing and cheap for a panel without a GPU.

import { onBeforeUnmount, ref, watch } from 'vue'

const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function useArtClock(moving: () => boolean) {
  const clock = ref(performance.now() / 1000)
  let id = 0
  const tick = () => { if (!document.hidden) clock.value = performance.now() / 1000 }
  watch(moving, (m) => {
    window.clearInterval(id)
    if (m && !reduced) id = window.setInterval(tick, 100)
  }, { immediate: true })
  onBeforeUnmount(() => window.clearInterval(id))
  return clock
}
