<template>
  <!-- Phones, on every tab but Now: the print in one line, like a music app's now-playing bar.
       Tap it for Now. It keeps the ring, never the camera: a tiny video on every tab is noise and data. -->
  <div v-if="intent && shown" class="nowbar" :class="'is-' + intent.state" role="button" tabindex="0"
       :aria-label="`${title}. ${line}. Open Now.`" @click="open" @keydown.enter="open">
    <span class="mini" :style="{ '--v': progress }">
      <!-- the object built to the layer it's on, as on Now (design/now-illustrated/, A); still when paused -->
      <BuildArt v-if="intent.job && built != null && thumb" :src="thumb" :alt="intent.job.name" :built="built" :moving="intent.state === 'printing'" plain class="img round" />
      <ObjectImage v-else-if="intent.job" :src="thumb" :alt="intent.job.name" round class="img" />
      <span v-else class="glyph" aria-hidden="true">!</span>
    </span>
    <span class="words">
      <b>{{ title }}</b>
      <span class="a-num">{{ line }}</span>
    </span>
    <button v-if="quick" class="quick" :aria-label="quick.label" :disabled="!!store.busyAction" @click.stop="store.act(quick)">
      <svg v-if="quick.id === 'pause'" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor"/><rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor"/></svg>
      <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5l11 7-11 7z" fill="currentColor"/></svg>
    </button>
    <span class="bar" aria-hidden="true"><i :style="{ width: progress * 100 + '%' }"></i></span>
  </div>
</template>

<script setup lang="ts">
import { preparingWord } from '@/intent/colour'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import ObjectImage from './ObjectImage.vue'
import BuildArt from './BuildArt.vue'

const store = useIntentStore()
const router = useRouter()
const intent = computed(() => store.intent)
const shown = computed(() => !!intent.value && intent.value.state !== 'ready')
const thumb = computed(() => store.fileUrl(intent.value?.job?.thumbnail))
const built = computed(() => intent.value?.art?.built ?? null)

const progress = computed(() => {
  const i = intent.value
  if (!i) return 0
  if (i.state === 'preparing') {
    const st = i.steps ?? []
    return st.length ? (st.filter(s => s.status === 'done').length + (st.some(s => s.status === 'now') ? 0.5 : 0)) / st.length : 0
  }
  return i.job?.progress ?? 0
})

const title = computed(() => {
  const i = intent.value!
  if (i.state === 'printing' || (i.state === 'preparing' && !i.change)) return i.job?.name ?? i.headline
  return i.headline
})
const line = computed(() => {
  const i = intent.value!
  const pct = Math.floor((i.job?.progress ?? 0) * 100)
  switch (i.state) {
    case 'preparing': return preparingWord(i)
    case 'printing': return i.job?.eta_clock ? `${pct}% · done at ${i.job.eta_clock}` : `${pct}%`
    case 'needs_you': return 'Tap to see what to do'
    case 'problem': return 'Stopped. Tap for what happened'
    case 'finished': return i.detail
    default: return ''
  }
})
// Only the reversible one-tap actions belong in the bar.
const quick = computed(() => intent.value?.actions.find(a => a.id === 'pause') ?? null)

function open() { router.push('/') }
</script>

<style scoped>
.nowbar {
  position: relative;
  display: flex; align-items: center; gap: 12px;
  margin: 0 10px 8px;
  padding: 8px 10px 10px 8px;
  border-radius: 20px;
  background: var(--a-surface);
  box-shadow: 0 10px 30px rgba(16, 24, 40, 0.18), 0 1px 2px rgba(16, 24, 40, 0.08);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.nowbar:active { transform: scale(0.99); }
.mini {
  --c: var(--a-state);
  width: 48px; height: 48px; flex: none; border-radius: 50%;
  background: conic-gradient(var(--c) calc(var(--v) * 360deg), var(--a-surface-2) 0);
  display: grid; place-items: center;
}
.mini .img { width: 40px; height: 40px; }
.mini .round { border-radius: 50%; overflow: hidden; }
.glyph { width: 40px; height: 40px; border-radius: 50%; background: var(--a-state); color: #fff; display: grid; place-items: center; font-weight: 800; font-size: 20px; }
.is-needs_you .glyph { color: var(--a-amber-ink); }
.words { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.words b { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.words span { font-size: 13px; color: var(--a-ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.is-needs_you .words span { color: var(--a-amber-text); font-weight: 600; }
.is-problem .words span { color: var(--a-red-text); font-weight: 600; }
.quick {
  appearance: none; cursor: pointer; flex: none;
  width: 44px; height: 44px; border-radius: 50%;
  border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2);
  display: grid; place-items: center;
}
.quick svg { width: 18px; height: 18px; }
.bar { position: absolute; left: 20px; right: 20px; bottom: 0; height: 3px; border-radius: 3px; background: var(--a-line); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--a-state); transition: width 800ms linear; }
</style>
