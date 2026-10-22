<template>
  <!-- One printer's own screens, framed under the app's bar (design/printers-open/, A). -->
  <div class="printer-frame">
    <p v-if="handoffNote" class="handoff-note" role="status">{{ handoffNote }}</p>

    <div v-if="src" class="stage">
      <iframe
        ref="frame"
        :key="src"
        :src="src"
        class="frame"
        :title="p?.name"
        allow="local-network-access; fullscreen"
        referrerpolicy="no-referrer"
        @load="loaded"
      ></iframe>
      <Transition name="lift"><PrinterCover v-if="!shown && p" :p="p" /></Transition>
    </div>
    <div v-else-if="!p || p.reach === 'unpaired' || p.reach === 'offline'" class="away-note">
      <template v-if="!p">
        <p>This printer isn't in your list.</p>
        <router-link to="/" class="a-btn ghost">All printers</router-link>
      </template>
      <template v-else-if="p.reach === 'unpaired'">
        <h2 class="a-display">{{ p.name }} doesn't know this phone any more</h2>
        <p>It was removed on the printer. To use it again, add it once more from the printer's screen.</p>
        <button class="a-btn ghost" @click="emit('remove')">Remove it from this list</button>
      </template>
      <template v-else-if="p.reach === 'offline'">
        <h2 class="a-display">Can't reach {{ p.name }}</h2>
        <p>Not at home and not through the internet. It may be off, or its network may be down.</p>
        <div class="acts">
          <button class="a-btn accent" @click="retry">Try again</button>
          <button class="a-btn ghost" @click="emit('remove')">Remove it from this list</button>
        </div>
      </template>
    </div>
    <div v-if="!src && p && p.reach !== 'unpaired' && p.reach !== 'offline'" class="stage"><PrinterCover :p="p" /></div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { printerById, reach, tryOtherAddress } from './printers'
import { handoff } from './look'
import PrinterCover from './PrinterCover.vue'

const props = defineProps<{ id: string; current: boolean }>()
const emit = defineEmits<{ drop: []; remove: [] }>()
const route = useRoute()
const router = useRouter()
const frame = ref<HTMLIFrameElement | null>(null)

const p = computed(() => printerById(props.id))
// The printer screen to show: the frame reports it back, so a reload or a notification lands on it.
const path = ref(pathFromHash())
function pathFromHash(): string {
  const h = decodeURIComponent(route.hash.replace(/^#/, ''))
  return h.startsWith('/') ? h : '/'
}

// Built once per address: switching between home and away reloads the frame where it was.
const base = computed(() => p.value?.base ?? null)
const src = ref<string | null>(null)
// The frame says whether its live connection is up; if it isn't within 8 s, use the other name.
const frameConnected = ref(false)
const frameReports = ref(false)   // older printer apps never say; only act on one that does
let frameTimer = 0
// The cover stays until the printer's screen says it's connected; an older printer app never says, so a moment after it
// loads; and never longer than LIFT_MS from opening, after which the printer's own screen says what it's doing (a camera
// stream can keep the frame's load event from ever firing).
const shown = ref(false)
const LIFT_MS = 6000
let liftTimer = 0
function loaded() {
  window.setTimeout(() => { if (!frameReports.value) shown.value = true }, 2500)
}
watch([base, () => props.id], () => {
  src.value = base.value ? `${base.value}${path.value}${path.value.includes('?') ? '&' : '?'}embed=1` : null
  frameConnected.value = false
  frameReports.value = false
  shown.value = false
  window.clearTimeout(frameTimer)
  window.clearTimeout(liftTimer)
  if (src.value) liftTimer = window.setTimeout(() => { shown.value = true }, LIFT_MS)
  if (src.value) {
    frameTimer = window.setTimeout(() => {
      if (frameReports.value && !frameConnected.value && p.value) tryOtherAddress(p.value.id)
    }, 8000)
  }
}, { immediate: true })

// a notification for this printer while it's open: move the frame instead of reloading it
// (switching printers is the `current` watch's to handle)
watch(() => [route.path, route.hash], ([nowPath], [wasPath]) => {
  if (props.current && nowPath === wasPath) follow()
})
function follow() {
  const want = pathFromHash()
  if (want !== path.value) {
    path.value = want
    frame.value?.contentWindow?.postMessage({ type: 'elyir-bench:navigate', path: want }, new URL(base.value!).origin)
  }
}

// Kept loaded while another printer or the list is shown. A printer app that can't pause when hidden (an older release)
// is let go after a while, so its camera doesn't run on unseen.
const hides = ref(false)
const DROP_MS = 3 * 60_000
let dropTimer = 0
function tellShown() {
  if (base.value) frame.value?.contentWindow?.postMessage({ type: 'elyir-bench:shown', shown: props.current }, new URL(base.value).origin)
}
watch(() => props.current, (now) => {
  window.clearTimeout(dropTimer)
  tellShown()
  if (now) {
    // back to this printer: a link that names a screen goes there; otherwise the address shows where the frame is
    if (route.hash) follow()
    else if (path.value !== '/') router.replace({ path: route.path, hash: '#' + path.value })
  } else if (!hides.value) {
    dropTimer = window.setTimeout(() => emit('drop'), DROP_MS)
  }
})

function onMessage(ev: MessageEvent) {
  const printer = p.value
  if (!printer || !base.value || !frame.value || ev.source !== frame.value.contentWindow) return
  // carries nothing secret, so from whatever address the frame ended up on: its screen is up, lift the cover
  if (ev.data?.type === 'elyir-bench:status' && ev.data.connected) shown.value = true
  if (ev.origin !== new URL(base.value).origin) return   // only the printer we loaded gets its token
  if (ev.data?.type === 'elyir-bench:ready') {
    frame.value.contentWindow!.postMessage({ type: 'elyir-bench:token', token: printer.token }, ev.origin)
    // a deep link that arrived while the frame was still loading: say it again now it listens
    if (path.value !== '/') frame.value.contentWindow!.postMessage({ type: 'elyir-bench:navigate', path: path.value }, ev.origin)
  } else if (ev.data?.type === 'elyir-bench:listening') {
    hides.value = !!ev.data.hides
    if (hides.value) window.clearTimeout(dropTimer)
    tellShown()
    // "Print on Workshop…" from Look at a model: the file goes to this printer's own Print now it listens
    if (handoff.value?.printer === printer.id) frame.value.contentWindow!.postMessage({ type: 'elyir-bench:model', files: [...handoff.value.files] }, ev.origin)
  } else if (ev.data?.type === 'elyir-bench:model-taken') {
    handoff.value = null
    handoffNote.value = ''
    window.clearTimeout(handoffTimer)
  } else if (ev.data?.type === 'elyir-bench:status') {
    frameReports.value = true
    frameConnected.value = !!ev.data.connected
    if (frameConnected.value) shown.value = true
  } else if (ev.data?.type === 'elyir-bench:path' && typeof ev.data.path === 'string') {
    const clean = ev.data.path.replace(/[?&]embed=1\b/, '').replace(/\?$/, '') || '/'
    path.value = clean
    if (props.current) router.replace({ path: route.path, hash: clean === '/' ? '' : '#' + clean })
  }
}
// A printer on an older release doesn't take files from here: say so rather than wait.
const handoffNote = ref('')
let handoffTimer = 0
watch(() => [handoff.value?.printer, p.value?.id], () => {
  window.clearTimeout(handoffTimer)
  handoffNote.value = ''
  const h = handoff.value, printer = p.value
  if (!h || !printer || h.printer !== printer.id) return
  handoffTimer = window.setTimeout(() => {
    if (handoff.value !== h) return
    handoff.value = null
    handoffNote.value = `${printer.name} didn't take the file: it needs an update for that. Open its Print and pick ${h.files[0]?.name ?? 'the file'} there.`
  }, 20000)
}, { immediate: true })

onMounted(() => window.addEventListener('message', onMessage))
onBeforeUnmount(() => { window.removeEventListener('message', onMessage); window.clearTimeout(frameTimer); window.clearTimeout(handoffTimer); window.clearTimeout(liftTimer); window.clearTimeout(dropTimer) })

function retry() {
  if (p.value) reach(p.value.id)
}
</script>

<style scoped>
.printer-frame { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.frame { flex: 1; width: 100%; border: 0; display: block; background: var(--a-bg); }
.handoff-note { margin: 0; padding: 10px 16px; font-size: 15px; line-height: 1.4; color: var(--a-amber-text); background: color-mix(in srgb, var(--a-amber) 14%, var(--a-bg)); }
.away-note { flex: 1; display: flex; flex-direction: column; align-items: flex-start; justify-content: center; gap: 14px; padding: 24px; max-width: 520px; margin: 0 auto; }
.away-note h2 { font-size: 26px; margin: 0; }
.away-note p { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0; }
.away-note .a-btn { flex: none; text-decoration: none; }
.acts { display: flex; flex-wrap: wrap; gap: 10px; }
.stage { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.lift-leave-active { transition: opacity .25s ease; }
.lift-leave-to { opacity: 0; }
</style>
