<template>
  <!-- A part's first layer from above with a brim drawn round it (design/brim/, A): measured from the part's own
       triangles (src/slice/footprint.ts), not sliced. The front of the plate is at the bottom. -->
  <div ref="box" class="fp">
    <canvas v-if="print" ref="canvas" :aria-label="alt" role="img"></canvas>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { drawFootprint, type Box, type BrimKind, type Footprint } from '@/slice/footprint'

// box: the area to show, shared by the pictures of one part so they compare (roomFor)
const props = defineProps<{ print: Footprint | null; color: string; kind: BrimKind; alt: string; area?: Box }>()
const box = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)

function paint() {
  const c = canvas.value, b = box.value
  if (!c || !b || !props.print) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const w = Math.round(b.clientWidth * dpr), h = Math.round(b.clientHeight * dpr)
  if (c.width !== w || c.height !== h) {
    c.width = w; c.height = h
    c.style.width = b.clientWidth + 'px'; c.style.height = b.clientHeight + 'px'
  }
  drawFootprint(c, props.print, props.color, props.kind, props.area)
}

let ro: ResizeObserver | null = null
onMounted(() => {
  paint()
  ro = new ResizeObserver(() => paint())
  if (box.value) ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())
watch(() => [props.print, props.color, props.kind, props.area], () => requestAnimationFrame(paint))
</script>

<style scoped>
.fp { position: relative; overflow: hidden; background: var(--a-surface); box-shadow: inset 0 0 0 1px var(--a-line); }
canvas { position: absolute; inset: 0; display: block; }
</style>
