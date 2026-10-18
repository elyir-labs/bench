<template>
  <!-- A printer's camera, through the box (GET /bench/p/<id>/camera): live where its stream is one an <img> can show,
       else a still every 2 s. Nothing at all when it has no camera, or the picture stops. -->
  <div v-if="src" class="bcam" :style="{ aspectRatio: String(aspect) }">
    <img :src="src" :style="{ transform }" alt="" @error="onError" />
    <span class="name">{{ name }} · {{ live ? 'live' : 'every 2 s' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { cameraAspect, cameraTransform } from '@/camera/cameras'

const props = defineProps<{ printer: string; name: string }>()
interface BenchCam { stream: string | null; snapshot: string | null; rotation?: number; aspect_ratio?: string; flip_horizontal?: boolean; flip_vertical?: boolean }
const cam = ref<BenchCam | null>(null)
const live = ref(false)
const still = ref<string | null>(null)
let timer = 0

const transform = computed(() => (cam.value ? cameraTransform(cam.value) : ''))
const aspect = computed(() => (cam.value ? cameraAspect({ aspect_ratio: cam.value.aspect_ratio, rotation: cam.value.rotation }) : 4 / 3))
const src = computed(() => (live.value ? cam.value?.stream : still.value) ?? null)

async function load() {
  stop()
  cam.value = await fetch(`/bench/p/${props.printer}/camera`, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
  live.value = !!cam.value?.stream
  if (!live.value) stills()
}
// a still every 2 s, swapped in only once it has loaded, so the picture never blinks
function stills() {
  const url = cam.value?.snapshot
  if (!url) return
  const img = new Image()
  img.onload = () => { still.value = img.src; timer = window.setTimeout(stills, 2000) }
  img.onerror = () => { still.value = null }
  img.src = `${url}?t=${Date.now()}`
}
function onError() {
  if (live.value) { live.value = false; stills() } else still.value = null
}
function stop() {
  window.clearTimeout(timer)
  live.value = false
  still.value = null
}
watch(() => props.printer, load, { immediate: true })
onBeforeUnmount(stop)        // dropping the <img> ends the stream through the box
</script>

<style scoped>
.bcam { position: relative; width: 100%; max-height: 320px; border-radius: 14px; overflow: hidden; background: #11141a; }
.bcam img { width: 100%; height: 100%; object-fit: cover; display: block; }
.name { position: absolute; left: 12px; top: 10px; padding: 3px 10px; border-radius: 999px; background: rgba(0, 0, 0, .5); color: #fff; font-size: 14px; font-weight: 600; }
</style>
