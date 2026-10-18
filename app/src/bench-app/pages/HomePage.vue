<template>
  <section class="home" :class="'size-' + size">
    <BenchTop title="Bench">
      <router-link v-if="!here.away" to="/setup" class="add" aria-label="Add a printer">+ Add</router-link>
      <button v-else-if="here.may.invite" class="add" @click="inviting = true">+ Invite</button>
    </BenchTop>
    <!-- a new box, or every printer taken off: the first run -->
    <router-link v-if="!here.away && bench.loaded && !bench.printers.length" to="/setup" class="a-btn accent first">Find the printers on this Wi-Fi</router-link>
    <BenchShape v-if="!bench.loaded && !bench.error" />
    <h1 v-else class="a-display say">{{ line }}</h1>
    <p v-if="bench.error" class="note">{{ bench.error }}</p>

    <!-- the printers, as many as there are: big tiles up to four, compact up to nine, then rows by state -->
    <div v-if="size !== 'rows'" class="tiles">
      <article v-for="t in on" :key="t.id" class="tile" :class="'tone-' + t.tone" @click="open(t)">
        <div class="head"><b class="name">{{ t.name }}</b><span class="chip" :class="'tone-' + t.tone"><i></i>{{ t.word }}</span></div>
        <div class="pic"><Ring :tile="t" :printer="byId(t.id)" /></div>
        <div class="words"><b>{{ t.says }}</b><span>{{ t.what }}</span></div>
        <button v-if="act(t).button" class="a-btn" :class="t.tone === 'green' ? 'accent' : 'amber'" @click.stop="open(t)">{{ act(t).button }}</button>
        <span v-else-if="act(t).note" class="athome">{{ act(t).note }}</span>
      </article>
    </div>
    <div v-else class="groups">
      <div v-for="g in groups" :key="g.title" class="group">
        <p class="gtitle">{{ g.title }} · {{ g.tiles.length }}</p>
        <article v-for="t in g.tiles" :key="t.id" class="row" :class="'tone-' + t.tone" @click="open(t)">
          <Ring :tile="t" :printer="byId(t.id)" small />
          <span class="rw"><b>{{ t.name }} <em v-if="t.what">· {{ t.what.split(' · ')[0] }}</em></b><span>{{ t.says }}</span></span>
          <button v-if="act(t).button" class="a-btn" :class="t.tone === 'green' ? 'accent' : 'amber'" @click.stop="open(t)">{{ act(t).button }}</button>
          <span v-else-if="act(t).note" class="athome">{{ act(t).note }}</span>
          <span v-else-if="t.frac" class="pct a-num">{{ Math.round(t.frac * 100) }}%</span>
        </article>
      </div>
    </div>
    <QueueStart v-if="starting" :item="starting" @close="starting = null" />
    <p v-if="off" class="off"><span class="chip tone-off"><i></i>{{ off.split(' · ')[0] }}</span>{{ off.split(' · ').slice(1).join(' · ') }}</p>
    <p v-if="guest && bench.loaded" class="guest">{{ guestLine(here, new Date()) }}</p>
    <InviteSheet :open="inviting" @close="inviting = false" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { bench } from '../live'
import { offLine, ordered, sentence, sizeFor, withQueue, type Tile } from '../bench'
import Ring from './BenchRing.vue'
import BenchTop from './BenchTop.vue'
import QueueStart from './QueueStart.vue'
import InviteSheet from './InviteSheet.vue'
import type { QueueItem } from '../shelf'
import { here } from '../here'
import { guestLine, hostOf, isGuest, tileAct } from '../away'
import BenchShape from './BenchShape.vue'

const router = useRouter()
const tiles = computed(() => withQueue(ordered(bench.printers), bench.queue).sort((a, b) => a.rank - b.rank))
const on = computed(() => tiles.value.filter((t) => t.tone !== 'off'))
const size = computed(() => sizeFor(on.value.length))
const guest = computed(() => isGuest(here))
const line = computed(() => (bench.loaded ? sentence(tiles.value, guest.value ? hostOf(here) : undefined) : ''))
const act = (t: Tile) => tileAct(t, here)
const inviting = ref(false)
const off = computed(() => offLine(tiles.value))
const groups = computed(() => [
  { title: 'Needs you', tiles: on.value.filter((t) => t.rank <= 2) },
  { title: 'Printing', tiles: on.value.filter((t) => t.rank === 3) },
  { title: 'Ready', tiles: on.value.filter((t) => t.rank === 4) },
].filter((g) => g.tiles.length))
const byId = (id: string) => bench.printers.find((p) => p.id === id)!

// the action lives on the printer's own screen: open it there; Print a model opens the box's shelf, for that printer
const starting = ref<QueueItem | null>(null)
function open(t: Tile) {
  if (t.queued && here.away) { router.push(`/p/${t.id}`); return }
  if (t.queued) { starting.value = bench.queue.find((q) => q.id === t.queued) ?? null; return }   // the queue's bed question
  router.push(t.action === 'Print a model' ? { path: '/print', query: { on: t.id } } : `/p/${t.id}`)
}
</script>

<style scoped>
.home { min-height: 100%; box-sizing: border-box; padding: 22px 40px 28px; display: flex; flex-direction: column; gap: 18px; }
.say { margin: 0; font-size: 40px; line-height: 1.08; letter-spacing: -.025em; text-wrap: balance; }
.note { color: var(--a-red-text); margin: 0; }
.add { appearance: none; border: 0; background: none; padding: 0; font: inherit; cursor: pointer; color: var(--a-accent-text); font-weight: 650; font-size: 20px; text-decoration: none; white-space: nowrap; }
.athome { margin-top: auto; color: var(--a-ink-3); font-size: 17px; text-align: right; }
.guest { margin: 4px 0 0; color: var(--a-ink-3); font-size: 18px; max-width: 70ch; }
.first { align-self: flex-start; height: 68px; font-size: 24px; padding: 0 34px; display: inline-flex; align-items: center; text-decoration: none; }
.chip { display: inline-flex; align-items: center; gap: 7px; font-weight: 650; border-radius: 999px; padding: 4px 12px; font-size: 15px; white-space: nowrap; background: var(--a-surface-2); color: var(--a-ink-2); }
.chip i { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.chip.tone-amber { background: color-mix(in srgb, var(--a-amber) 22%, transparent); color: var(--a-amber-text); }
.chip.tone-red { background: color-mix(in srgb, var(--a-red) 18%, transparent); color: var(--a-red-text); }
.chip.tone-blue { background: color-mix(in srgb, var(--a-accent) 14%, transparent); color: var(--a-accent-text); }
.chip.tone-green { background: color-mix(in srgb, var(--a-green) 18%, transparent); color: var(--a-green-text); }
.chip.tone-off i { background: var(--a-ink-3); }

.tiles { display: grid; gap: 22px; grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr)); }
.size-big .tiles { --cols: v-bind('Math.max(3, Math.min(on.length, 4))'); }   /* one or two printers: tiles their usual size */
.tile { background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); padding: 24px; display: flex; flex-direction: column; gap: 14px; cursor: pointer; min-width: 0; }
.tile.tone-amber, .row.tone-amber { box-shadow: 0 0 0 3px var(--a-amber), var(--a-card-shadow); }
.tile.tone-red, .row.tone-red { box-shadow: 0 0 0 3px var(--a-red), var(--a-card-shadow); }
.head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 4px 8px; }
.name { font-size: 26px; letter-spacing: .01em; }
.pic { display: grid; place-items: center; }
.words { display: grid; gap: 3px; }
.words b { font-size: 24px; letter-spacing: -.01em; }
.words span { color: var(--a-ink-3); font-size: 18px; }
.tile .a-btn { margin-top: auto; height: 60px; font-size: 22px; }

/* five to nine: compact tiles, three across, the ring beside the words */
.size-compact .tiles { --cols: 3; gap: 16px; }
.size-compact .tile { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 16px; padding: 16px 18px; align-content: start; }
.size-compact .pic { grid-row: 1 / span 2; grid-column: 1; }
.size-compact .head { grid-column: 2; }
.size-compact .words { grid-column: 2; }
.size-compact .name { font-size: 21px; }
.size-compact .words b { font-size: 18px; }
.size-compact .words span { font-size: 15px; }
.size-compact .tile .a-btn { grid-column: 1 / -1; height: 46px; font-size: 18px; margin-top: 8px; }

/* ten or more: rows grouped by what they're doing, in two columns */
.groups { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
.group { display: grid; gap: 7px; }
.gtitle { margin: 4px 0 0; color: var(--a-ink-3); font-size: 14px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.row { display: flex; align-items: center; gap: 12px; padding: 5px 12px; background: var(--a-surface); border-radius: 14px; cursor: pointer; }
.rw { flex: 1; min-width: 0; display: grid; line-height: 1.25; }
.rw b { font-size: 18px; } .rw em { font-style: normal; font-weight: 500; color: var(--a-ink-3); font-size: 15px; }
.rw span { color: var(--a-ink-3); font-size: 15px; }
.row .a-btn { height: 38px; font-size: 16px; padding: 0 16px; }
.pct { font-size: 18px; font-weight: 650; color: var(--a-accent-text); }
.off { display: flex; align-items: center; gap: 12px; margin: 0; color: var(--a-ink-3); font-size: 18px; }

/* a phone: one list, whatever the size (design/bench-box/, D on a phone) */
@media (max-width: 599px) {
  .home { padding: 14px 16px 24px; gap: 12px; }
  .say { font-size: 25px; }
  .tiles, .groups { grid-template-columns: minmax(0, 1fr) !important; gap: 8px; }
  .tile, .size-compact .tile { display: flex; flex-direction: row; align-items: center; gap: 12px; padding: 9px 12px; border-radius: 16px; }
  .tile .head .chip, .tile .words span { display: none; }
  .tile .pic { order: -1; }
  .tile .head { flex: 0 0 auto; }
  .tile .words { flex: 1; min-width: 0; } .tile .words b { font-size: 14px; font-weight: 500; color: var(--a-ink-3); }
  .name, .size-compact .name { font-size: 16px; }
  .tile .head, .tile .words { display: block; }
  .tile .a-btn, .size-compact .tile .a-btn { margin: 0; height: 36px; font-size: 14px; padding: 0 12px; }
  .off { font-size: 14px; }
  .add { font-size: 16px; }
  .athome { margin: 0; font-size: 12.5px; line-height: 1.3; max-width: 92px; }
  .guest { font-size: 14px; }
}
</style>
