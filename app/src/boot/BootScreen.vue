<template>
  <div class="boot" aria-hidden="true">
    <div class="veil" :style="{ opacity: veil }"></div>
    <svg ref="svg" :viewBox="`0 0 ${M.design[0]} ${M.design[1]}`">
      <g :transform="eyeTransform" :style="{ opacity: eyeOpacity }">
        <circle :r="M.ring.r" fill="none" :stroke="rgba(M.colors.track)" :stroke-width="stroke"
                :style="{ opacity: 1 - land }" />
        <circle :r="M.ring.r" fill="none" :stroke="color" :stroke-width="stroke" stroke-linecap="round"
                pathLength="1" :stroke-dasharray="`${arc} 1`" transform="rotate(-90)"
                :style="{ opacity: arc > 0.004 ? 1 : 0 }" />
        <g :transform="`scale(1 ${blink})`"><circle :r="pupilR" :fill="color" /></g>
      </g>
      <text :x="M.center[0]" :y="M.name_y" text-anchor="middle" class="name" :fill="rgba(M.colors.name)"
            :style="{ opacity: nameOpacity }">{{ name }}</text>
      <text :x="M.center[0]" :y="M.line_y" text-anchor="middle" class="line" :fill="rgba(M.colors.line)"
            :style="{ opacity: lineOpacity }">{{ line }}</text>
    </svg>
  </div>
</template>

<script setup lang="ts">
// The boot screen, from the app's side (design/boot/, E: the Elyir signature becomes the eye). Plymouth fills the ring up to
// mark.handoff while the Pi boots and index.html shows that same frame while this loads; from here
// the ring moves only when something real happens, and when the printer is ready the eye blinks and
// settles into the Now tab, where the same mark lives. Shown only on the panel's first page load
// after power-on: the decision is made once, in index.html, as html[data-boot].
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import M from './mark.json'
import { GIVE_UP_MS, STALL_MS, arcFor, stageOf, stallLine, type BootStage } from './progress'

const emit = defineEmits<{ done: [] }>()
const store = useIntentStore()
const router = useRouter()
const svg = ref<SVGSVGElement | null>(null)

const rgba = (c: number[]) => `rgba(${c.join(',')})`
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const mix = (a: number[], b: number[], x: number) => `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * x)).join(',')})`
const clamp = (v: number) => Math.min(1, Math.max(0, v))
const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)
const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches

const stage = computed<BootStage>(() => stageOf(store.connected, store.intent))
const name = computed(() => store.intent?.printer?.name ?? '')

// what the animation loop draws
const arc = ref<number>(M.handoff)
const blink = ref(1)
const land = ref(0)
const veil = ref(1)            // the dark screen itself; fading it shows the app underneath
const eyeOpacity = ref(1)
const nameOpacity = ref(0)
const lineOpacity = ref(0)
const line = ref('')
const red = ref(0)
const target = ref({ x: M.center[0], y: M.center[1], k: 1, ink: hex(M.colors.accent) })

const color = computed(() => red.value > 0
  ? mix(hex(M.colors.accent), hex(M.colors.problem), red.value)
  : mix(hex(M.colors.accent), target.value.ink, clamp((land.value - 0.35) / 0.65)))
const eyeTransform = computed(() => {
  const L = land.value
  const x = M.center[0] + (target.value.x - M.center[0]) * ease(L)
  const y = M.center[1] + (target.value.y - M.center[1]) * L
  return `translate(${x} ${y}) scale(${1 + (target.value.k - 1) * L})`
})
// The thin boot ring and its pupil grow to the Now tab icon's weight as they land in it.
const T = M.now_tab
const stroke = computed(() => M.ring.stroke + (T.stroke * M.ring.r / T.r - M.ring.stroke) * ease(land.value))
const pupilR = computed(() => M.pupil.r + (T.pupil * M.ring.r / T.r - M.pupil.r) * ease(land.value))

// Where the Now tab's icon is, in the eye's own coordinates, so the landing hits it on any panel.
function aimAtNow() {
  const icon = document.querySelector('.tabs .tab[href="/"] .icon') as HTMLElement | null
  const ctm = svg.value?.getScreenCTM()
  if (!icon || !ctm) return false
  const r = icon.getBoundingClientRect()
  const ink = getComputedStyle(icon).color.match(/\d+/g)?.slice(0, 3).map(Number) ?? hex(M.colors.accent)
  target.value = {
    x: (r.left + r.width / 2 - ctm.e) / ctm.a,
    y: (r.top + r.height / 2 - ctm.f) / ctm.d,
    k: (r.width * M.now_tab.r / 24 / ctm.a) / M.ring.r,   // the tab icon's ring, in its 24 box
    ink,
  }
  return true
}

let raf = 0
let last = performance.now()
let movedAt = performance.now()
let phase: 'filling' | 'blink' | 'landing' | 'fading' = 'filling'
let phaseAt = 0

function go(p: typeof phase, now: number) { phase = p; phaseAt = now }

function frame(now: number) {
  const dt = Math.min(0.1, (now - last) / 1000)
  last = now
  const want = arcFor(stage.value, M.handoff)
  if (want > arc.value + 0.0005) {
    arc.value += (want - arc.value) * Math.min(1, dt * 7)
    movedAt = now
  }
  if (name.value) nameOpacity.value = Math.min(1, nameOpacity.value + dt / 0.6)

  const stalled = now - movedAt
  if (phase === 'filling') {
    if (stalled > STALL_MS && stage.value !== 'ready') line.value = stallLine(stage.value, store.intent)
    lineOpacity.value = stalled > STALL_MS && stage.value !== 'ready'
      ? Math.min(1, lineOpacity.value + dt / 0.4) : Math.max(0, lineOpacity.value - dt / 0.3)
    if (stage.value === 'ready' && arc.value > 0.995) {
      arc.value = 1
      if (still || !aimAtNow()) go('fading', now)
      else go('blink', now)
    } else if (stage.value === 'problem' || stalled > GIVE_UP_MS) {
      // The Problem screen, or the app's own Starting up, says more than this one line can.
      go('fading', now)
    }
  } else if (phase === 'blink') {
    const b = clamp((now - phaseAt) / 260)
    blink.value = 1 - 0.86 * Math.sin(Math.PI * b)
    if (b >= 1) { aimAtNow(); go('landing', now) }
  } else if (phase === 'landing') {
    const L = clamp((now - phaseAt) / 800)
    land.value = L
    nameOpacity.value = Math.min(nameOpacity.value, 1 - clamp(L / 0.3))
    veil.value = 1 - clamp((L - 0.35) / 0.6)
    eyeOpacity.value = 1 - clamp((L - 0.88) / 0.12)
    if (L >= 1) return finish()
  } else if (phase === 'fading') {
    const f = clamp((now - phaseAt) / 500)
    if (stage.value === 'problem') red.value = clamp(f * 2)
    veil.value = 1 - clamp((f - 0.3) / 0.7)
    eyeOpacity.value = veil.value
    lineOpacity.value = Math.min(lineOpacity.value, veil.value)
    nameOpacity.value = Math.min(nameOpacity.value, veil.value)
    if (f >= 1) return finish()
  }
  raf = requestAnimationFrame(frame)
}

function finish() {
  try { sessionStorage.setItem('elyir-bench.booted', '1') } catch { /* the next load just shows it again */ }
  delete document.documentElement.dataset.boot
  document.documentElement.style.background = ''
  emit('done')
}

// The boot always ends on Now, whatever page the kiosk was left on.
watch(() => router.currentRoute.value.path, (p) => { if (p !== '/') router.replace('/') }, { immediate: true })

onMounted(() => {
  // index.html's still frame stays up until this one has painted over it
  requestAnimationFrame(() => document.getElementById('boot-frame')?.remove())
  last = movedAt = performance.now()
  raf = requestAnimationFrame(frame)
})
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<style scoped>
/* It takes the touches too: nothing underneath should be tapped blind. */
.boot { position: fixed; inset: 0; z-index: 9000; }
.veil { position: absolute; inset: 0; background: v-bind('M.colors.bg'); }
.boot svg { position: absolute; inset: 0; width: 100%; height: 100%; display: block; overflow: visible; }
.name { font-family: var(--a-font); font-size: 21px; font-weight: 600; letter-spacing: 4px; }
.line { font-family: var(--a-font); font-size: 17px; font-weight: 500; }
</style>
