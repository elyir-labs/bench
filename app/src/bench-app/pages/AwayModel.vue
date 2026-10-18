<template>
  <!-- A model from the shelf, away (design/bench-remote/, A-phone-shelf): look at it; prints start at home, where someone
       checks the bed. A paired phone can add it to the queue, which waits for It's clear at home; a guest only looks. -->
  <section class="bpage">
    <BenchTop title="Print"><router-link to="/print" class="back">Shelf</router-link></BenchTop>
    <p v-if="!item && loaded" class="gone">That model isn't on the shelf any more.</p>
    <template v-if="item">
      <div class="picbig"><img v-if="item.picture" :src="item.picture" alt="" /><span v-else class="ext">{{ item.file }}</span></div>
      <div class="words">
        <h1 class="a-display name">{{ item.name }}</h1>
        <p class="muted">{{ sub }}</p>
      </div>
      <div class="home">
        <b><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11l8-6.5 8 6.5M6.5 9.5V19.5h11V9.5" /></svg>{{ AT_HOME.title }}</b>
        <p>{{ homeLine }}</p>
      </div>
      <template v-if="here.may.queue">
        <button class="a-btn ghost queue" :disabled="queuing || !fil" @click="queueIt">{{ queuing ? 'Adding…' : 'Add to the queue' }}</button>
        <p class="muted small">{{ AT_HOME.queued }}</p>
        <p v-if="error" class="bad">{{ error }}</p>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { bench, loadQueue } from '../live'
import { here } from '../here'
import { AT_HOME, atHomeLine } from '../away'
import { choices, filamentFor, lastLine, printOn, shelfCard, type MyFilament, type Printable } from '../shelf'
import { addToQueue, getMine, getPrintable, getShelf, type ShelfItem } from '../shelf-api'
import BenchTop from './BenchTop.vue'

const route = useRoute()
const router = useRouter()
const id = String(route.params.id)
const item = ref<ShelfItem | null>(null)
const loaded = ref(false)
const printable = ref<Printable>({})
const mine = ref<MyFilament[]>([])
const queuing = ref(false)
const error = ref('')
const now = new Date()

onMounted(async () => {
  try {
    item.value = (await getShelf()).find((x) => x.id === id) ?? null
  } finally {
    loaded.value = true
  }
  printable.value = await getPrintable().catch(() => ({}))
  mine.value = await getMine().catch(() => [])
})

const fils = computed(() => choices(bench.printers, printable.value, mine.value))
const fil = computed(() => filamentFor(fils.value, item.value?.last?.material, item.value?.last?.color) ?? fils.value[0] ?? null)
const sub = computed(() => {
  const it = item.value!
  return it.from && it.last?.at === it.from.at ? `From ${it.from.printer_name}'s Print · ${shelfCard(it, now).line}`
    : it.last ? `Last printed: ${lastLine(it, now)}` : lastLine(it, now)
})
const homeLine = computed(() => {
  const rows = printOn(bench.printers, fil.value, printable.value)
  const fits = rows.find((r) => r.fits && r.free)
  const free = fits ?? rows.find((r) => r.free)
  return atHomeLine(free ? { name: free.name, filament: fits ? fil.value?.name ?? null : null } : null)
})

async function queueIt() {
  if (!item.value || !fil.value) return
  queuing.value = true
  error.value = ''
  try {
    const named = fil.value.preset ? { filament: fil.value.preset, filament_name: fil.value.name } : {}
    await addToQueue({ shelf: item.value.id, copies: item.value.last?.copies ?? 1, material: fil.value.material, color: fil.value.color, ...named })
    await loadQueue()
    await router.push('/print')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    queuing.value = false
  }
}
</script>

<style scoped>
.bpage { min-height: 100%; box-sizing: border-box; padding: 22px 40px 28px; display: flex; flex-direction: column; gap: 16px; max-width: 760px; }
.back { color: var(--a-accent-text); font-weight: 650; font-size: 20px; text-decoration: none; }
.back::before { content: '‹ '; }
.gone { color: var(--a-ink-3); font-size: 22px; }
.muted { margin: 0; color: var(--a-ink-3); font-size: 17px; }
.small { font-size: 15px; }
.bad { margin: 0; color: var(--a-red-text); }
.picbig { height: 300px; border-radius: 22px; background: linear-gradient(var(--a-surface), var(--a-surface-2)); box-shadow: var(--a-card-shadow); display: grid; place-items: center; overflow: hidden; }
.picbig img { max-width: 86%; max-height: 270px; object-fit: contain; }
.ext { color: var(--a-ink-3); font-size: 18px; }
.words { display: grid; gap: 4px; }
.name { margin: 0; font-size: 36px; letter-spacing: -.02em; }
.home { display: grid; gap: 6px; padding: 16px 18px; border-radius: 18px; background: color-mix(in srgb, var(--a-amber) 22%, var(--a-surface)); }
.home b { display: inline-flex; align-items: center; gap: 10px; font-size: 19px; }
.home svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linejoin: round; stroke-linecap: round; }
.home p { margin: 0; color: var(--a-ink-2); font-size: 16px; line-height: 1.45; }
.queue { flex: none; height: 54px; border-radius: 999px; font-size: 18px; font-weight: 650; }
@media (max-width: 599px) {
  .bpage { padding: 14px 16px 24px; gap: 12px; }
  .picbig { height: 200px; border-radius: 18px; } .picbig img { max-height: 180px; }
  .name { font-size: 26px; } .muted { font-size: 14px; } .small { font-size: 13.5px; }
  .home { padding: 14px 16px; } .home b { font-size: 17px; } .home p { font-size: 14.5px; }
  .back { font-size: 16px; }
}
</style>
