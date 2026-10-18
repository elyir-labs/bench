<template>
  <!-- The print going up (design/now-illustrated/, A): the slicer's picture of the object, solid up to
       the layer the printer is on and a faint outline above, with a line where the nozzle is. The
       cut follows layers, not how far through the file it is. -->
  <svg class="build-art" :class="{ still: !moving }" viewBox="0 0 200 200" role="img" :aria-label="aria">
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
    <template v-if="box">
      <image :href="src!" :x="box.x" :y="box.y" :width="box.w" :height="box.h" :filter="`url(#ghost-${uid})`" />
      <image :href="src!" :x="box.x" :y="box.y" :width="box.w" :height="box.h" :clip-path="`url(#built-${uid})`" />
      <template v-if="built < 1 && !plain">
        <line :x1="box.x + box.w * 0.1" :x2="box.x + box.w * 0.9" :y1="cutY" :y2="cutY" class="layer" :class="{ still: !moving }" />
        <path v-if="moving" :d="`M${nozzleX - 6} ${cutY - 15}h12v6l-4 7h-4l-4-7z`" class="nozzle" />
      </template>
    </template>
  </svg>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { cutAt, objectBounds } from '@/art/ringArt'
import { useArtClock } from '@/art/useArtClock'

// plain: no layer line or nozzle, for the Now bar's small ring, where motion on every tab is noise
const props = defineProps<{ src: string | null; alt?: string; built: number; moving: boolean; plain?: boolean }>()

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
</script>

<style scoped>
.build-art { display: block; width: 100%; height: 100%; }
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
