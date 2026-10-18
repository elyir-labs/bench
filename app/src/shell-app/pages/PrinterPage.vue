<template>
  <!-- A printer, opened (design/printers-open/, A): one bar of the app's above the printer's own screens, which drop
       their header in here. Wide: the printers as chips, as on the Bench Box. A phone: the name with a switcher, and
       another printer that needs you as a chip. One printer: no way back to a list of one. -->
  <div class="printer-page" :class="{ wide }">
    <header class="bar">
      <router-link v-if="!single" to="/" class="back" :class="{ round: !wide }" aria-label="All printers">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span v-if="wide">Printers</span>
      </router-link>

      <nav v-if="wide && !single" class="chips" aria-label="Printers">
        <router-link v-for="o in chips.on" :key="o.id" :to="`/p/${o.id}`" class="chip" :class="['tone-' + statusOf(o).tone, { here: o.id === id }]"
                     :aria-current="o.id === id ? 'page' : undefined"><i></i>{{ o.name }}</router-link>
        <router-link v-if="p && !chips.on.includes(p)" :to="`/p/${p.id}`" class="chip here tone-off"><i></i>{{ p.name }}</router-link>
        <span v-if="chips.off" class="more">+ {{ chips.off }} off</span>
      </nav>
      <button v-else class="switch" :class="{ alone: single && wide }" @click="menu = !menu" :aria-expanded="menu" aria-haspopup="menu">
        <span class="dot" :class="'tone-' + (p ? statusOf(p).tone : 'off')"></span>
        <span class="pname">{{ p?.name ?? '' }}</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>

      <span class="end">
        <router-link v-if="!wide && other" :to="`/p/${other.id}`" class="chip need" :class="'tone-' + statusOf(other).tone"><i></i>{{ other.name }}</router-link>
        <span v-else-if="p?.reach === 'away'" class="via">away</span>
        <template v-if="wide">
          <router-link to="/look" class="pill">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z" /><path d="M3.5 7 12 11.5 20.5 7M12 11.5v10" /></svg>
            Look at a model
          </router-link>
          <router-link v-if="single" to="/add" class="icb" aria-label="Add a printer">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
          </router-link>
          <YouLink />
        </template>
        <YouLink v-else-if="single" />
      </span>
    </header>

    <div v-if="menu" class="menu" role="menu" @click.self="menu = false">
      <div class="menu-box">
        <router-link v-for="o in ordered" :key="o.id" :to="`/p/${o.id}`" class="menu-item" :class="{ here: o.id === id }" role="menuitem" @click="menu = false">
          <span class="dot" :class="'tone-' + statusOf(o).tone"></span>
          <span class="mi-name">{{ o.name }}</span>
          <span class="mi-state">{{ statusOf(o).word }}</span>
        </router-link>
        <div class="menu-acts">
          <router-link to="/look" class="menu-act" role="menuitem" @click="menu = false">Look at a model</router-link>
          <router-link to="/add" class="menu-act" role="menuitem" @click="menu = false">Add a printer</router-link>
        </div>
      </div>
    </div>

    <PrinterFrame :id="id" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { benches, printerById, printers } from '../printers'
import { statusOf } from '../status'
import { chipsOf, grouped } from '../home'
import PrinterFrame from '../PrinterFrame.vue'
import YouLink from '../YouLink.vue'

defineProps<{ wide?: boolean }>()
const route = useRoute()
const menu = ref(false)
const id = computed(() => String(route.params.id))
const p = computed(() => printerById(id.value))
watch(id, () => { menu.value = false })

const single = computed(() => printers.length === 1 && benches.length === 0)
const chips = computed(() => chipsOf(printers))
const ordered = computed(() => grouped(printers).flatMap((g) => g.printers))
// a phone shows one other printer that needs you, the one the list would put first
const other = computed(() => grouped(printers).find((g) => g.group === 'attention')?.printers.find((o) => o.id !== id.value) ?? null)
</script>

<style scoped>
.printer-page { height: 100dvh; display: flex; flex-direction: column; background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font); }
.bar {
  flex: none; display: flex; align-items: center; gap: 8px; min-height: 56px; box-sizing: border-box;
  padding: env(safe-area-inset-top, 0px) 12px 0;
  border-bottom: 1px solid var(--a-line);
}
.wide .bar { min-height: 64px; gap: 10px; padding: env(safe-area-inset-top, 0px) 24px 0; }
.back { display: inline-flex; align-items: center; gap: 4px; height: 40px; padding: 0 14px 0 8px; border-radius: 99px; flex: none;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: var(--a-ink); text-decoration: none; font-weight: 650; font-size: 16px; }
.back.round { width: 40px; padding: 0; justify-content: center; }
.back svg { width: 20px; height: 20px; }

.chips { display: flex; align-items: center; gap: 8px; min-width: 0; overflow-x: auto; scrollbar-width: none; padding: 4px 2px; }
.chips::-webkit-scrollbar { display: none; }
.chip { display: inline-flex; align-items: center; gap: 7px; height: 36px; padding: 0 14px; border-radius: 99px; flex: none;
  background: var(--a-surface); color: var(--a-ink-2); font-weight: 650; font-size: 15px; white-space: nowrap; text-decoration: none; }
.chip i { width: 9px; height: 9px; border-radius: 50%; background: var(--a-ink-3); flex: none; }
.chip.here { background: var(--a-ink); color: var(--a-bg); }
.chip.need.tone-amber { background: color-mix(in srgb, var(--a-amber) 20%, var(--a-surface)); color: var(--a-amber-text); }
.chip.need.tone-red { background: color-mix(in srgb, var(--a-red) 14%, var(--a-surface)); color: var(--a-red-text); }
.more { color: var(--a-ink-3); font-size: 14px; white-space: nowrap; flex: none; }

.switch {
  appearance: none; border: 0; background: none; font: inherit; color: var(--a-ink); min-width: 0;
  display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 99px;
  font-weight: 700; font-size: 18px; cursor: pointer; min-height: 40px;
}
.switch .pname { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.switch svg { width: 18px; height: 18px; color: var(--a-ink-3); flex: none; }
.end { margin-left: auto; display: flex; align-items: center; gap: 10px; flex: none; }
.via { font-size: 12px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--a-ink-3); }
.pill { display: inline-flex; align-items: center; gap: 8px; height: 40px; padding: 0 16px; border-radius: 99px; text-decoration: none;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: var(--a-ink-2); font-weight: 650; font-size: 15px; white-space: nowrap; }
.pill svg { width: 18px; height: 18px; color: var(--a-accent-text); }
.icb { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex: none;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: var(--a-ink-2); }
.icb svg { width: 20px; height: 20px; }

.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--a-ink-3); flex: none; }
.tone-busy.dot, .tone-busy i { background: var(--a-accent); }
.tone-amber.dot, .tone-amber i { background: var(--a-amber); }
.tone-green.dot, .tone-green i { background: var(--a-green); }
.tone-red.dot, .tone-red i { background: var(--a-red); }

.menu { position: fixed; inset: 0; z-index: 20; background: rgba(0, 0, 0, 0.35); display: flex; justify-content: center; align-items: flex-start;
  padding-top: calc(56px + env(safe-area-inset-top, 0px)); }
.menu-box { width: min(420px, calc(100% - 24px)); background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); padding: 6px; }
.menu-item { display: flex; align-items: center; gap: 12px; padding: 14px; border-radius: 12px; color: var(--a-ink); text-decoration: none; }
.menu-item.here { box-shadow: inset 0 0 0 2px var(--a-accent); }
.menu-item:active { background: var(--a-surface-2); }
.mi-name { font-weight: 700; flex: 1; }
.mi-state { color: var(--a-ink-3); font-size: 14px; }
.menu-acts { display: flex; border-top: 1px solid var(--a-line); margin-top: 4px; }
.menu-act { flex: 1; text-align: center; padding: 14px 8px; color: var(--a-accent-text); font-weight: 650; text-decoration: none; }
</style>
