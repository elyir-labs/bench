// The current arrangement (layout.ts), following the window as it's resized or turned.

import { computed, ref } from 'vue'
import { isPanel } from '@/theme'
import { layoutFor, type Layout } from './layout'
import { benchChrome } from '@/auth'

const size = ref({ width: window.innerWidth, height: window.innerHeight })
window.addEventListener('resize', () => { size.value = { width: window.innerWidth, height: window.innerHeight } }, { passive: true })

export const layout = computed<Layout>(() => layoutFor({ panel: isPanel, bench: benchChrome, ...size.value }))

/** A mouse or trackpad (laptops). Touch screens open the camera full screen instead of in a pane. */
const fine = window.matchMedia('(pointer: fine)')
const finePointerRef = ref(fine.matches)
fine.addEventListener('change', (e) => { finePointerRef.value = e.matches })
export const finePointer = computed(() => finePointerRef.value)
