// Press and hold with a visible fill. Used for the Advanced door.
import { ref, onBeforeUnmount } from 'vue'

export function useLongPress(durationMs: number, onComplete: () => void) {
  const progress = ref(0) // 0..1 while holding
  let raf = 0
  let start = 0
  let active = false

  function tick(now: number) {
    if (!active) return
    const p = Math.min(1, (now - start) / durationMs)
    progress.value = p
    if (p >= 1) {
      active = false
      progress.value = 0
      try { (navigator as any).vibrate?.(20) } catch { /* no haptics here */ }
      onComplete()
      return
    }
    raf = requestAnimationFrame(tick)
  }

  function begin(e?: Event) {
    if (e && 'button' in e && (e as MouseEvent).button !== 0) return
    active = true
    start = performance.now()
    raf = requestAnimationFrame(tick)
  }

  function end() {
    active = false
    progress.value = 0
    cancelAnimationFrame(raf)
  }

  onBeforeUnmount(end)

  return {
    progress,
    handlers: {
      onPointerdown: begin,
      onPointerup: end,
      onPointerleave: end,
      onPointercancel: end,
      onContextmenu: (e: Event) => e.preventDefault(),
    },
  }
}
