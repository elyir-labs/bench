<template>
  <Teleport to="body" :disabled="inline">
    <div
      ref="root"
      class="viewer"
      :class="{ inline, hidden: !controls }"
      role="dialog"
      :aria-label="`${camera.name} camera`"
      @pointermove="wake"
      tabindex="-1"
    >
      <div
        class="stage"
        @pointerdown="down"
        @pointermove="move"
        @pointerup="up"
        @pointercancel="up"
        @wheel.prevent="wheel"
        @click="tap"
      >
        <div class="zoom" :style="{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }">
          <CameraView :camera="camera" watching fit="contain" :progress="null" :badge="inline" />
        </div>
      </div>

      <template v-if="inline">
        <div class="ibar">
          <span class="ititle">{{ camera.name }}</span>
          <span class="ihint">Scroll or pinch to zoom · Esc to go back</span>
          <button class="ibtn" @click="emit('fullscreen')">Full screen</button>
          <button class="ibtn" aria-label="Close the camera" @click="close">Close</button>
        </div>
      </template>
      <template v-else>
        <button class="fsbtn close" aria-label="Close the camera" @click.stop="close">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
        </button>
        <div class="who">
          <b>{{ printerName }}</b>
          <span v-if="jobName">{{ jobName }}</span>
          <span class="livetag"><i aria-hidden="true"></i>Live · {{ camera.name }}</span>
        </div>
        <div class="bottom">
          <button v-if="pauseAction" class="fsbtn" :aria-label="pauseAction.label" :disabled="!!store.busyAction" @click.stop="store.act(pauseAction)">
            <svg v-if="pauseAction.id === 'pause'" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5l11 7-11 7z" fill="currentColor"/></svg>
          </button>
          <div class="status a-num">
            <b v-if="pct != null">{{ pct }}%</b>
            <b v-else>{{ headline }}</b>
            <span v-if="eta">Done at {{ eta }}</span>
          </div>
          <span class="hint">Pinch to zoom</span>
        </div>
        <div v-if="pct != null" class="prog" aria-hidden="true"><i :style="{ width: pct + '%' }"></i></div>
      </template>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
// The camera, big. Full screen on phones and tablets (the browser's real full screen where it
// allows one: iPhone Safari only allows it for <video>, so there it covers the page instead), or
// filling the right-hand pane on wide screens (inline). Pinch, double-tap or scroll to zoom.
// The controls fade after 3 s and a tap brings them back. The screen stays awake while it's open.
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import CameraView from './CameraView.vue'
import { useIntentStore } from '@/intent/store'
import type { Camera } from '@/camera/cameras'

const props = withDefaults(defineProps<{ camera: Camera; inline?: boolean }>(), { inline: false })
const emit = defineEmits<{ close: []; fullscreen: [] }>()
const store = useIntentStore()
const root = ref<HTMLElement | null>(null)

const intent = computed(() => store.intent)
const printerName = computed(() => intent.value?.printer?.name ?? '')
const jobName = computed(() => intent.value?.job?.name ?? '')
const headline = computed(() => intent.value?.headline ?? '')
const active = computed(() => ['preparing', 'printing', 'needs_you', 'finished'].includes(intent.value?.state ?? ''))
const pct = computed(() => (active.value && intent.value?.job ? Math.floor(intent.value.job.progress * 100) : null))
const eta = computed(() => (intent.value?.state === 'printing' ? intent.value?.job?.eta_clock ?? null : null))
const pauseAction = computed(() => intent.value?.actions.find(a => a.id === 'pause' || a.id === 'resume') ?? null)

// ---- controls fade ------------------------------------------------------------------------
const controls = ref(true)
let fade = 0
function wake() {
  controls.value = true
  window.clearTimeout(fade)
  fade = window.setTimeout(() => (controls.value = false), 3000)
}

// ---- zoom and pan -------------------------------------------------------------------------
const scale = ref(1)
const pan = reactive({ x: 0, y: 0 })
const pointers = new Map<number, { x: number; y: number }>()
let pinch: { d: number; s: number } | null = null
let drag: { x: number; y: number; px: number; py: number } | null = null
let moved = false
const clamp = (v: number) => Math.min(4, Math.max(1, v))
function setScale(s: number) {
  scale.value = clamp(s)
  if (scale.value === 1) { pan.x = 0; pan.y = 0 }
}
const dist = () => { const [a, b] = [...pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y) }
function down(e: PointerEvent) {
  (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  moved = false
  if (pointers.size === 2) { pinch = { d: dist(), s: scale.value }; drag = null }
  else if (pointers.size === 1) drag = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }
}
function move(e: PointerEvent) {
  if (!pointers.has(e.pointerId)) return
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pinch && pointers.size === 2) { setScale(pinch.s * dist() / pinch.d); moved = true }
  else if (drag && scale.value > 1) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true
    pan.x = drag.px + dx; pan.y = drag.py + dy
  }
}
function up(e: PointerEvent) {
  pointers.delete(e.pointerId)
  if (pointers.size < 2) pinch = null
  if (pointers.size === 0) drag = null
}
function wheel(e: WheelEvent) { setScale(scale.value * (e.deltaY < 0 ? 1.12 : 1 / 1.12)) }
let lastTap = 0
function tap() {
  if (moved) return
  const now = Date.now()
  if (now - lastTap < 300) { setScale(scale.value > 1 ? 1 : 2.5); lastTap = 0; return }
  lastTap = now
  if (controls.value) { controls.value = false; window.clearTimeout(fade) } else wake()
}

// ---- full screen, wake lock, Esc ----------------------------------------------------------
let wakeLock: any = null
let wentFull = false
function close() { emit('close') }
function onFsChange() { if (wentFull && !document.fullscreenElement) close() }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && !document.fullscreenElement) close() }
onMounted(async () => {
  wake()
  root.value?.focus()
  window.addEventListener('keydown', onKey)
  document.addEventListener('fullscreenchange', onFsChange)
  try { wakeLock = await (navigator as any).wakeLock?.request('screen') } catch { /* not offered: fine */ }
  if (!props.inline && root.value?.requestFullscreen) {
    try { await root.value.requestFullscreen({ navigationUI: 'hide' }); wentFull = true } catch { /* the overlay still covers the page */ }
  }
})
onBeforeUnmount(() => {
  window.clearTimeout(fade)
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('fullscreenchange', onFsChange)
  wakeLock?.release?.().catch?.(() => undefined)
  if (wentFull && document.fullscreenElement) document.exitFullscreen().catch(() => undefined)
})
</script>

<style scoped>
.viewer {
  position: fixed; inset: 0; z-index: 50;
  background: #000; color: #fff;
  outline: none;
  font-family: var(--a-font);
}
.viewer.inline { position: relative; inset: auto; z-index: auto; height: 100%; border-radius: 20px; overflow: hidden; display: flex; flex-direction: column; }
.stage { position: absolute; inset: 0; overflow: hidden; touch-action: none; cursor: zoom-in; }
.inline .stage { position: relative; flex: 1; }
.zoom { position: absolute; inset: 0; transform-origin: center; transition: transform 60ms linear; }
.zoom :deep(.cam) { border-radius: 0; background: #000; }

.fsbtn {
  appearance: none; border: 0; cursor: pointer; color: #fff;
  width: 48px; height: 48px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.16); backdrop-filter: blur(8px);
  display: grid; place-items: center; flex: none;
}
.fsbtn svg { width: 22px; height: 22px; }
.fsbtn[disabled] { opacity: 0.5; }
.close { position: absolute; left: max(20px, env(safe-area-inset-left)); top: max(20px, env(safe-area-inset-top)); }
.who {
  position: absolute; right: max(20px, env(safe-area-inset-right)); top: max(20px, env(safe-area-inset-top));
  display: flex; flex-direction: column; align-items: flex-end; gap: 2px;
  font-size: 15px; text-shadow: 0 1px 6px rgba(0, 0, 0, 0.6);
}
.who b { font-size: 18px; }
.livetag { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; margin-top: 4px; }
.livetag i { width: 7px; height: 7px; border-radius: 50%; background: #ff5a5a; }
.who span { opacity: 0.75; }
.bottom {
  position: absolute; left: 0; right: 0; bottom: 0;
  display: flex; align-items: center; gap: 16px;
  padding: 60px max(20px, env(safe-area-inset-right)) max(22px, env(safe-area-inset-bottom)) max(20px, env(safe-area-inset-left));
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.7));
}
.status { display: flex; flex-direction: column; gap: 2px; }
.status b { font-size: 24px; }
.status span { opacity: 0.75; font-size: 15px; }
.hint { margin-left: auto; opacity: 0.6; font-size: 14px; }
.prog { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: rgba(255, 255, 255, 0.2); }
.prog i { display: block; height: 100%; background: var(--a-accent); }
.close, .who, .bottom { transition: opacity 300ms ease; }
.hidden .close, .hidden .who, .hidden .bottom { opacity: 0; pointer-events: none; }
.hidden { cursor: none; }

.ibar { display: flex; align-items: baseline; gap: 14px; padding: 12px 16px; background: #000; }
.ititle { font-weight: 700; }
.ihint { opacity: 0.55; font-size: 13px; }
.ibtn { appearance: none; border: 0; cursor: pointer; font: inherit; font-size: 13px; font-weight: 600; color: #fff; background: rgba(255, 255, 255, 0.14); padding: 6px 12px; border-radius: 99px; }
.ibtn:first-of-type { margin-left: auto; }
</style>
