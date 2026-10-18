<template>
  <!-- Spools, on the box (design/bench-box/, D): every printer's spools in one place, the ones running short
       first; what's loaded where, by material. A printer opens on its own Materials, where spools are changed. -->
  <section class="bpage">
    <BenchTop title="Spools" />
    <h1 class="a-display say">{{ line }}</h1>
    <p v-if="materials.length" class="mats">
      <span v-for="[m, on] in materials" :key="m" class="mat"><b>{{ m }}</b> {{ on.join(', ') }}</span>
    </p>
    <div class="cards">
      <article v-for="c in cards" :key="c.id" class="card" :class="{ short: c.short }" @click="router.push(`/p/${c.id}/materials`)">
        <header><b>{{ c.name }}</b><span class="open">Materials ›</span></header>
        <ul>
          <li v-for="s in c.spools" :key="s.slot">
            <span class="sw" :class="{ empty: !s.color && s.name === 'Empty' }" :style="s.color ? { background: s.color } : {}"></span>
            <span class="n a-num" v-if="c.spools.length > 1">{{ s.slot }}</span>
            <span class="nm">{{ s.name }}</span>
            <span class="meta" :class="s.tone ? 'tone-' + s.tone : ''">{{ s.meta }}</span>
          </li>
        </ul>
      </article>
    </div>
    <p v-if="quiet.length" class="quiet">{{ quiet.join(', ') }} {{ quiet.length === 1 ? "doesn't say" : "don't say" }} what's loaded.</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { bench } from '../live'
import { byMaterial, spoolCards, spoolSentence } from '../tabs'
import BenchTop from './BenchTop.vue'

const router = useRouter()
const cards = computed(() => spoolCards(bench.printers))
const line = computed(() => (bench.loaded ? spoolSentence(cards.value) : ''))
const materials = computed(() => byMaterial(bench.printers))
// printers that are on but report no spools (a Kobra on its own firmware, a resin printer)
const quiet = computed(() => bench.printers.filter((p) => p.live && p.intent && !p.intent.spools?.length).map((p) => p.name).sort())
</script>

<style scoped>
.bpage { min-height: 100%; box-sizing: border-box; padding: 22px 40px 28px; display: flex; flex-direction: column; gap: 16px; }
.say { margin: 8px 0 0; font-size: 40px; line-height: 1.08; letter-spacing: -.025em; text-wrap: balance; }
.mats { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; }
.mat { background: var(--a-surface-2); border-radius: 999px; padding: 6px 14px; font-size: 16px; color: var(--a-ink-3); }
.mat b { color: var(--a-ink); margin-right: 4px; }
.cards { display: grid; gap: 18px; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); align-items: start; }
.card { background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); padding: 18px 22px; cursor: pointer; }
.card.short { box-shadow: 0 0 0 3px var(--a-amber), var(--a-card-shadow); }
header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
header b { font-size: 24px; }
.open { color: var(--a-accent-text); font-weight: 650; font-size: 17px; }
ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
li { display: flex; align-items: center; gap: 12px; min-height: 36px; font-size: 19px; }
.sw { width: 26px; height: 26px; border-radius: 50%; flex: none; background: var(--a-surface-2); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--a-ink) 14%, transparent); }
.sw.empty { background: none; box-shadow: none; border: 2px dashed var(--a-ink-3); box-sizing: border-box; }
.n { color: var(--a-ink-3); font-size: 16px; width: 1.2em; }
.nm { flex: 1; min-width: 0; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { color: var(--a-ink-3); font-size: 16px; white-space: nowrap; }
.meta.tone-amber { color: var(--a-amber-text); font-weight: 650; }
.meta.tone-accent { color: var(--a-accent-text); font-weight: 650; }
.quiet { margin: 0; color: var(--a-ink-3); font-size: 17px; }
@media (max-width: 599px) {
  .bpage { padding: 14px 16px 24px; gap: 10px; }
  .say { font-size: 25px; }
  .cards { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .card { padding: 12px 14px; border-radius: 16px; } header b { font-size: 18px; }
  li { font-size: 15px; min-height: 30px; } .sw { width: 20px; height: 20px; } .meta { font-size: 13px; }
  .mat { font-size: 13px; padding: 4px 10px; } .quiet { font-size: 14px; }
}
</style>
