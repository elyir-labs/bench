<template>
  <!-- The model in the spool's colour, drawn in the browser (src/slice/render.ts). A STEP file can't
       be read here, so it gets the same stand-in as a print without a picture. turnable: drag to look
       round the plate (design/plate/), level-ish and never from underneath; it doesn't zoom or move parts. -->
  <div ref="box" class="pic" :class="{ turnable, zoomable }"
       @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up" @lostpointercapture="up" @wheel="wheel">
    <canvas v-if="(tris && tris.length) || layers" ref="canvas" :aria-label="alt" role="img"></canvas>
    <ObjectImage v-else :src="null" :alt="alt" class="none" />
    <slot />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ObjectImage from '@/components/now/ObjectImage.vue'
import { draw, drawLayers, type LayersPicture } from '@/slice/render'
import type { SupportLines } from '@/slice/supports'

// plate: the build plate under it, so which side is down is plain to see (design/orientation/)
// bed: the printer's bed, for a plate of several parts in bed coordinates (design/plate/)
// zoomable: scroll (or a trackpad's pinch) zooms, and zoomBy/fit can be called (design/ready-wide/)
// shift: CSS px to move the plate's centre across, so a card over the right of the picture never hides it
// supports: the slice's supports, solid under a see-through part (design/supports/, A)
// zoomable also pinches on a touch screen; spin: turns slowly by itself, for showing someone (design/look/)
// layers: the slice instead of the model, cut at a layer (design/look/, A with C's layers)
const props = defineProps<{ tris: Float32Array | null; color: string; alt: string; plate?: boolean; bed?: number[] | null;
  turnable?: boolean; zoomable?: boolean; shift?: number; supports?: SupportLines | null; spin?: boolean; layers?: LayersPicture | null }>()
const emit = defineEmits<{ moved: [changed: boolean] }>()
const box = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)

// the view the slicer's own preview uses, until someone turns it
const AZ = -0.6, EL = 0.62
const view = { az: AZ, el: EL }
let zoom = 1
let shiftNow = props.shift ?? 0       // eased towards props.shift when the card opens or closes
let glide = 0
let drag: { x: number; y: number; az: number; el: number; id: number } | null = null
const touches = new Map<number, { x: number; y: number }>()
let pinch = 0
let frame = 0

function paint(fast = false) {
  const c = canvas.value, b = box.value
  if (!c || !b || (!props.tris && !props.layers)) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = Math.round(b.clientWidth * dpr), h = Math.round(b.clientHeight * dpr)
  if (c.width !== w || c.height !== h) {
    c.width = w; c.height = h
    c.style.width = b.clientWidth + 'px'; c.style.height = b.clientHeight + 'px'
  }
  const dpr2 = c.width / Math.max(1, b.clientWidth)
  const more = { fast, zoom, shift: shiftNow * dpr2, ...(props.supports ? { supports: props.supports, ghost: 0.3 } : {}) }
  if (props.layers) drawLayers(c, props.layers, view, 0.1, { fast, zoom, shift: shiftNow * dpr2 })
  else if (props.tris) draw(c, props.tris, props.color, view, 0.1, props.plate ? { plate: true, bed: props.bed, ...more } : more)
}

const spread = () => { const [a, b] = [...touches.values()]; return Math.hypot(a.x - b.x, a.y - b.y) }
function down(e: PointerEvent) {
  if (!props.turnable || !(props.tris?.length || props.layers)) return
  touches.set(e.pointerId, { x: e.clientX, y: e.clientY })
  box.value?.setPointerCapture(e.pointerId)
  if (props.zoomable && touches.size === 2) { drag = null; pinch = spread(); return }
  if (touches.size === 1) drag = { x: e.clientX, y: e.clientY, az: view.az, el: view.el, id: e.pointerId }
}
function move(e: PointerEvent) {
  if (touches.has(e.pointerId)) touches.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pinch && touches.size === 2) {
    const d = spread()
    if (d > 0) zoomBy(d / pinch)
    pinch = d
    return
  }
  if (!drag || e.pointerId !== drag.id) return
  const w = box.value?.clientWidth || 300
  view.az = drag.az - ((e.clientX - drag.x) / w) * Math.PI
  view.el = Math.min(1.25, Math.max(0.2, drag.el + ((e.clientY - drag.y) / w) * Math.PI * 0.6))
  if (!frame) frame = requestAnimationFrame(() => { frame = 0; paint(true) })
}
function up(e?: PointerEvent) {
  if (e) touches.delete(e.pointerId)
  if (pinch && touches.size < 2) { pinch = 0; paint(); return }
  if (!drag) return
  drag = null
  cancelAnimationFrame(frame); frame = 0
  paint()
  emit('moved', changed())
}
const changed = () => zoom !== 1 || view.az !== AZ || view.el !== EL
function wheel(e: WheelEvent) {
  if (!props.zoomable || !(props.tris?.length || props.layers)) return
  e.preventDefault()
  zoomBy(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)))   // ctrlKey: a trackpad pinch
}
function zoomBy(k: number) {
  zoom = Math.min(8, Math.max(0.5, zoom * k))
  if (!frame) frame = requestAnimationFrame(() => { frame = 0; paint(true); clearTimeout(settle); settle = window.setTimeout(() => paint(), 120) })
  emit('moved', changed())
}
let settle = 0
/** Back to the whole plate, from the front, as it opened. */
function fit() {
  zoom = 1; view.az = AZ; view.el = EL
  paint()
  emit('moved', false)
}
/** The view as it is now, on the picture's own background, as a PNG to send. */
function picture(w = 1600, h = 1200): Promise<Blob | null> {
  if (!(props.tris?.length || props.layers) || !box.value) return Promise.resolve(null)
  const model = document.createElement('canvas'), out = document.createElement('canvas')
  model.width = out.width = w; model.height = out.height = h
  if (props.layers) drawLayers(model, props.layers, view, 0.1, { zoom })
  else if (props.tris) draw(model, props.tris, props.color, view, 0.1, props.plate ? { plate: true, bed: props.bed, zoom } : { zoom })
  const css = getComputedStyle(box.value), ctx = out.getContext('2d')!
  const bg = ctx.createRadialGradient(w / 2, h * 0.38, 0, w / 2, h * 0.38, Math.hypot(w, h) * 0.6)
  bg.addColorStop(0, css.getPropertyValue('--a-obj-hi').trim() || '#fff')
  bg.addColorStop(1, css.getPropertyValue('--a-obj-lo').trim() || '#e6e8ec')
  ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h)
  ctx.drawImage(model, 0, 0)
  return new Promise((resolve) => out.toBlob(resolve, 'image/png'))
}
defineExpose({ zoomBy, fit, picture })

let spinning = 0
function spinFrom(t0: number, az0: number) {
  spinning = requestAnimationFrame((t) => {
    if (!drag && !pinch) view.az = az0 - ((t - t0) / 1000) * 0.4
    else { t0 = t; az0 = view.az }
    paint(true)
    spinFrom(t0, az0)
  })
}
watch(() => props.spin, (on) => {
  cancelAnimationFrame(spinning); spinning = 0
  if (on && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) spinFrom(performance.now(), view.az)
  else paint()
}, { immediate: true })

let ro: ResizeObserver | null = null
onMounted(() => {
  paint()
  ro = new ResizeObserver(() => paint())
  if (box.value) ro.observe(box.value)
})
onBeforeUnmount(() => { ro?.disconnect(); cancelAnimationFrame(spinning); cancelAnimationFrame(frame); cancelAnimationFrame(glide); clearTimeout(settle) })
watch(() => [props.tris, props.color, props.supports, props.layers], () => requestAnimationFrame(() => paint()))
// the card opened or closed: ease the plate across rather than jump
watch(() => props.shift ?? 0, (to) => {
  const from = shiftNow, t0 = performance.now(), ms = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 260
  cancelAnimationFrame(glide)
  const step = (t: number) => {
    const k = ms ? Math.min(1, (t - t0) / ms) : 1
    shiftNow = from + (to - from) * (1 - Math.pow(1 - k, 3))
    paint(k < 1)
    if (k < 1) glide = requestAnimationFrame(step)
  }
  glide = requestAnimationFrame(step)
})
</script>

<style scoped>
.pic {
  position: relative; overflow: hidden;
  border-radius: 22px;
  background: radial-gradient(circle at 50% 38%, var(--a-obj-hi), var(--a-obj-lo));
}
.pic.turnable { touch-action: pan-y; cursor: grab; }
.pic.turnable.zoomable { touch-action: none; }
.pic.turnable:active { cursor: grabbing; }
canvas { position: absolute; inset: 0; display: block; }
.none { width: 100%; height: 100%; }
</style>
