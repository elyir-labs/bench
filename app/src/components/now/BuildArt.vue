<template>
  <!-- The print going up. With the file's layers (design/now-layers/, A): the real walls in the filament's color up to
       the layer it's on, that layer lit, and a faint ghost of the rest. Until they're read, or for a file without
       layer marks, the slicer's picture (design/now-illustrated/, A): solid up to the layer, a faint outline above.
       Either way the cut follows layers, not how far through the file it is. -->
  <div class="build-art" :class="{ still: !moving }" role="img" :aria-label="aria">
    <svg viewBox="0 0 200 200" aria-hidden="true">
      <defs>
        <radialGradient :id="`bg-${uid}`" cx=".5" cy=".2" r="1.2">
          <stop offset="0" class="bg-hi" /><stop offset=".7" class="bg-lo" />
        </radialGradient>
        <!-- the part still to come: an outline and a faint fill of the object's shape -->
        <filter :id="`ghost-${uid}`" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
          <feComponentTransfer in="SourceAlpha" result="a"><feFuncA type="discrete" tableValues="0 0 1" /></feComponentTransfer>
          <feMorphology in="a" operator="dilate" radius="1.4" result="d" />
          <feComposite in="d" in2="a" operator="out" result="edge" />
          <feFlood class="ink" flood-opacity=".4" /><feComposite in2="edge" operator="in" result="line" />
          <feFlood class="ink" flood-opacity=".06" /><feComposite in2="a" operator="in" result="fill" />
          <feMerge><feMergeNode in="fill" /><feMergeNode in="line" /></feMerge>
        </filter>
        <clipPath :id="`built-${uid}`"><rect x="-20" :y="cutY" width="240" :height="240 - cutY" /></clipPath>
      </defs>
      <rect width="200" height="200" :fill="`url(#bg-${uid})`" />
      <template v-if="box && !ring">
        <image :href="src!" :x="box.x" :y="box.y" :width="box.w" :height="box.h" :filter="`url(#ghost-${uid})`" />
        <image :href="src!" :x="box.x" :y="box.y" :width="box.w" :height="box.h" :clip-path="`url(#built-${uid})`" />
        <template v-if="built < 1 && !plain">
          <line :x1="box.x + box.w * 0.1" :x2="box.x + box.w * 0.9" :y1="cutY" :y2="cutY" class="layer" :class="{ still: !moving }" />
          <path v-if="moving" :d="`M${nozzleX - 6} ${cutY - 15}h12v6l-4 7h-4l-4-7z`" class="nozzle" />
        </template>
      </template>
    </svg>
    <canvas v-if="ring" ref="canvas"></canvas>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { cutAt, objectBounds } from '@/art/ringArt'
import { currentLayer, litLayer, paintLayer, paintStack, prepare } from '@/art/ringLayers'
import { useArtClock } from '@/art/useArtClock'
import type { LayerStack } from '@/look/layers'

// plain: no layer line or nozzle, for the Now bar's small ring, where motion on every tab is noise.
// layers: the file's walls (the intent store's jobLayers); layer: Klipper's current layer, from 1; color: the filament's.
const props = defineProps<{ src: string | null; alt?: string; built: number; moving: boolean; plain?: boolean
  layers?: LayerStack | null; layer?: number | null; color?: string | null }>()

const uid = Math.random().toString(36).slice(2, 8)
const clock = useArtClock(() => props.moving && !props.plain)
const aria = computed(() => `${props.alt ?? 'The print'}, ${Math.round(props.built * 100)}% of the way up`)

// The picture's size and where the object sits in it. Reading the pixels needs the image from
// the same origin (the panel and the door both serve it so); if it can't be read, assume the
// object fills the middle of the picture.
const natural = ref<{ w: number; h: number } | null>(null)
const bounds = ref({ top: 0.12, bot: 0.88 })
watch(() => props.src, (src) => {
  natural.value = null
  bounds.value = { top: 0.12, bot: 0.88 }
  if (!src) return
  const img = new Image()
  img.onload = () => {
    natural.value = { w: img.naturalWidth || 4, h: img.naturalHeight || 3 }
    try {
      const W = 80, H = Math.max(1, Math.round(80 * img.naturalHeight / img.naturalWidth))
      const c = document.createElement('canvas'); c.width = W; c.height = H
      const g = c.getContext('2d', { willReadFrequently: true })!
      g.drawImage(img, 0, 0, W, H)
      const data = g.getImageData(0, 0, W, H).data, rows: boolean[] = []
      for (let y = 0; y < H; y++) {
        let any = false
        for (let x = 0; x < W && !any; x++) any = data[(y * W + x) * 4 + 3] > 160
        rows.push(any)
      }
      bounds.value = objectBounds(rows)
    } catch { /* another origin: keep the guess */ }
  }
  img.src = src
}, { immediate: true })

// the picture fitted inside the face, the way ObjectImage shows it (contain)
const box = computed(() => {
  const n = natural.value
  if (!n || !props.src) return null
  const s = Math.min(200 / n.w, 200 / n.h), w = n.w * s, h = n.h * s
  return { x: (200 - w) / 2, y: (200 - h) / 2, w, h }
})
const cutY = computed(() => (box.value ? box.value.y + box.value.h * cutAt(bounds.value, props.built) : 200))
const nozzleX = computed(() => {
  const b = box.value!
  return b.x + b.w * (0.2 + 0.6 * (0.5 + 0.5 * Math.sin(clock.value * 2.4)))
})

// ---- the real layers ----
const ring = computed(() => (props.layers ? prepare(props.layers) : null))
const canvas = ref<HTMLCanvasElement | null>(null)
const size = ref(0)
// the stack below the lit layer only changes with the layer, so it's kept and laid down under each frame
const below = shallowRef<{ key: string; img: HTMLCanvasElement } | null>(null)
let resize: ResizeObserver | null = null
onMounted(() => {
  resize = new ResizeObserver(() => {
    const c = canvas.value
    if (c) size.value = Math.round(c.clientWidth * (window.devicePixelRatio || 1))
  })
  watch(canvas, (c, old) => { if (old) resize!.unobserve(old); if (c) resize!.observe(c) }, { immediate: true })
})
onBeforeUnmount(() => resize?.disconnect())

function paint() {
  const R = ring.value, c = canvas.value, W = size.value
  if (!R || !c || !W) return
  if (c.width !== W) { c.width = c.height = W }
  const css = getComputedStyle(c)
  const ink = { ink: css.getPropertyValue('--a-ink').trim() || '#fff', accent: css.getPropertyValue('--a-accent').trim() || '#4da3ff' }
  const done = props.built >= 1
  const lit = done ? R.stack.count : litLayer(R, currentLayer(R.stack.count, props.layer, props.built))
  const color = props.color || '#8A8D91'
  const key = `${lit}|${W}|${color}|${ink.ink}`
  if (below.value?.key !== key) {
    const img = document.createElement('canvas'); img.width = img.height = W
    paintStack(img, R, lit, color, ink)
    below.value = { key, img }
  }
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, W, W)
  ctx.drawImage(below.value!.img, 0, 0)
  if (done || props.plain) return
  // paused: the layer drawn quiet, and no nozzle (nothing is moving)
  const line = props.moving ? ink.accent : css.getPropertyValue('--a-ink-3').trim() || ink.ink
  paintLayer(ctx, R, lit, ink, line, props.moving ? clock.value / 6 : null)
}
watch([ring, size, () => props.built, () => props.layer, () => props.color, () => props.moving, () => props.plain, clock], paint, { flush: 'post' })
</script>

<style scoped>
.build-art { position: relative; display: block; width: 100%; height: 100%; }
.build-art > svg, .build-art > canvas { position: absolute; inset: 0; display: block; width: 100%; height: 100%; }
/* paused: the picture holds still and dims (on the whole drawing: a CSS filter on the
   images would replace the outline filter) */
.build-art.still { opacity: .6; filter: saturate(.4); }
.bg-hi { stop-color: var(--a-obj-hi); }
.bg-lo { stop-color: var(--a-obj-lo); }
.layer { stroke: var(--a-accent); stroke-width: 1.6; }
.layer.still { stroke: var(--a-ink-3); stroke-dasharray: 3 4; }
.nozzle { fill: var(--a-ink); }
.ink { flood-color: var(--a-ink); }
</style>
