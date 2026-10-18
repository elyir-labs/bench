<template>
  <div
    ref="root"
    class="cam"
    :class="['tone-' + tone, { contain: fit === 'contain', failed }]"
    :style="fit === 'contain' ? undefined : { aspectRatio: String(camera.aspect) }"
  >
    <img
      v-if="src && !failed"
      :src="src"
      :alt="`${camera.name} camera`"
      :style="{ transform: camera.transform || undefined }"
      draggable="false"
      @error="onError"
      @load="loaded = true"
    />
    <div v-if="!loaded && !failed" class="waiting">Connecting to the camera…</div>
    <div v-if="failed" class="waiting">The camera isn't answering.</div>

    <span v-if="badge" class="live" :class="{ still: mode === 'stills' }">
      <i aria-hidden="true"></i>{{ mode === 'live' ? 'Live' : 'Every 2 s' }}<template v-if="showName"> · {{ camera.name }}</template>
    </span>
    <button v-if="expandable" class="expand" aria-label="Show the camera bigger" @click.stop="emit('expand')">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <slot />
    <div v-if="progress != null" class="prog" aria-hidden="true"><i :style="{ width: Math.round(progress * 100) + '%' }"></i></div>
  </div>
</template>

<script setup lang="ts">
// One camera picture. Live MJPEG in an <img>, or a snapshot refreshed every 2 s when data is dear.
// Nothing is fetched while the picture is off screen or the page is hidden: dropping the src
// closes the MJPEG connection, so a tab in the background costs nothing.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { cameraMode, type Camera } from '@/camera/cameras'
import { saveData } from '@/camera/useCameras'

const props = withDefaults(defineProps<{
  camera: Camera
  /** someone asked to watch (full screen): always live */
  watching?: boolean
  fit?: 'cover' | 'contain'
  tone?: 'accent' | 'amber' | 'red' | 'green' | 'none'
  progress?: number | null
  expandable?: boolean
  showName?: boolean
  /** the Live / Every 2 s label; the full-screen viewer says it in its own corner */
  badge?: boolean
}>(), { watching: false, fit: 'cover', tone: 'none', progress: null, expandable: false, showName: false, badge: true })
const emit = defineEmits<{ expand: []; failed: [] }>()

const root = ref<HTMLElement | null>(null)
const onScreen = ref(true)
const pageVisible = ref(document.visibilityState !== 'hidden')
const failed = ref(false)
const loaded = ref(false)
const still = ref<string | null>(null)

const mode = computed(() => cameraMode(props.camera, { saveData: saveData(), watching: props.watching }))
const active = computed(() => onScreen.value && pageVisible.value)

const src = computed(() => {
  if (!active.value) return null
  if (mode.value === 'live') return props.camera.stream
  return still.value
})

function withStamp(url: string) {
  return url + (url.includes('?') ? '&' : '?') + 't=' + Date.now()
}

// Stills: load the next frame off screen and swap it in, so the picture never blinks.
let timer = 0
function nextStill() {
  const url = props.camera.snapshot
  if (!url) return
  const img = new Image()
  img.onload = () => { still.value = img.src; loaded.value = true }
  img.onerror = () => onError()
  img.src = withStamp(url)
}
function runStills() {
  window.clearInterval(timer)
  if (mode.value !== 'stills' || !active.value || failed.value) return
  nextStill()
  timer = window.setInterval(nextStill, 2000)
}
watch([mode, active, () => props.camera.snapshot], runStills)

// A camera that stops answering gets another chance every 30 s; the parent shows the ring meanwhile.
let retry = 0
function onError() {
  if (failed.value) return
  failed.value = true
  loaded.value = false
  emit('failed')
  window.clearInterval(timer)
  retry = window.setTimeout(() => { failed.value = false; runStills() }, 30000)
}
watch(() => props.camera.stream, () => { failed.value = false; loaded.value = false })

let io: IntersectionObserver | null = null
const onVis = () => { pageVisible.value = document.visibilityState !== 'hidden' }
onMounted(() => {
  document.addEventListener('visibilitychange', onVis)
  if (root.value && 'IntersectionObserver' in window) {
    io = new IntersectionObserver(([e]) => { onScreen.value = e.isIntersecting })
    io.observe(root.value)
  }
  runStills()
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVis)
  io?.disconnect()
  window.clearInterval(timer)
  window.clearTimeout(retry)
})
</script>

<style scoped>
.cam {
  position: relative;
  width: 100%;
  overflow: hidden;
  background: #0d0f13;
  border-radius: inherit;
  color: #fff;
}
.cam.contain { height: 100%; }
.cam img {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}
.cam.contain img { object-fit: contain; }
.waiting {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  font-size: 14px; color: rgba(255, 255, 255, 0.6);
  padding: 16px; text-align: center;
}
.live {
  position: absolute; left: 10px; top: 10px;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 99px;
  background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(6px);
  font-size: 12px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
}
.live i { width: 7px; height: 7px; border-radius: 50%; background: #ff5a5a; }
.live.still i { background: rgba(255, 255, 255, 0.7); }
.failed .live { display: none; }
.expand {
  appearance: none; border: 0; cursor: pointer; color: #fff;
  position: absolute; right: 10px; top: 10px;
  width: 36px; height: 36px; border-radius: 50%;
  background: rgba(0, 0, 0, 0.5); backdrop-filter: blur(6px);
  display: grid; place-items: center;
}
.expand svg { width: 17px; height: 17px; }
.prog { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: rgba(255, 255, 255, 0.2); }
.prog i { display: block; height: 100%; background: var(--a-accent); transition: width 800ms linear; }
.tone-amber::after, .tone-red::after {
  content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  box-shadow: inset 0 0 0 3px var(--edge);
}
.tone-amber { --edge: var(--a-amber); }
.tone-red { --edge: var(--a-red); }
.tone-amber .prog i { background: var(--a-amber); }
.tone-green .prog i { background: var(--a-green); }
</style>
