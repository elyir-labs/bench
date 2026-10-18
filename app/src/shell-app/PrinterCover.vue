<template>
  <!-- design/loading/, B + A: while the printer's own screen loads, what the list knows about it live, or the Now
       screen's shape. Never from memory: a printer's state is only ever shown live. -->
  <div class="cover" aria-busy="true" :aria-label="`Opening ${p.name}`"><div class="col">
    <template v-if="live">
      <div class="pic">
        <img v-if="pic && !broken" :src="pic" alt="" @error="broken = true" />
        <span v-else-if="swatch" class="swatch" :style="{ background: swatch }"></span>
        <span v-if="row.progress !== null" class="bar"><i :style="{ width: row.progress * 100 + '%' }"></i></span>
      </div>
      <h2 class="a-display head">{{ status.word.split(' · ')[0] }}</h2>
      <p v-if="line" class="line">{{ line }}</p>
    </template>
    <template v-else>
      <i class="a-sk frame"></i>
      <i class="a-sk" style="width: 200px; height: 32px; border-radius: 9px"></i>
      <i class="a-sk" style="width: 280px; height: 34px; border-radius: 17px"></i>
      <span class="steps">
        <span v-for="w in [220, 180, 240]" :key="w"><i class="a-sk round" style="width: 22px; height: 22px"></i><i class="a-sk" :style="{ width: w + 'px', height: '13px' }"></i></span>
      </span>
    </template>
    <span class="tiles">
      <span v-for="t in ['Nozzle', 'Bed', 'Chamber']" :key="t" class="tile">{{ t }}<i class="a-sk" style="width: 46px; height: 18px"></i></span>
    </span>
  </div></div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { LivePrinter } from './printers'
import { statusOf } from './status'
import { loadedColor, pictureOf, rowOf } from './home'

const props = defineProps<{ p: LivePrinter }>()
const live = computed(() => !!props.p.intent && props.p.connected)
const status = computed(() => statusOf(props.p))
const row = computed(() => rowOf(props.p))
const pic = computed(() => pictureOf(props.p))
const swatch = computed(() => loadedColor(props.p))
const broken = ref(false)
const line = computed(() => [row.value.progress !== null ? `${Math.floor(row.value.progress * 100)}%` : '', status.value.line].filter(Boolean).join(' · '))
</script>

<style scoped>
.cover { position: absolute; inset: 0; z-index: 2; overflow: hidden; background: var(--a-bg); font-family: var(--a-font); }
.col { display: flex; flex-direction: column; gap: 16px; padding: 18px 22px; box-sizing: border-box; max-width: 640px; height: 100%; margin: 0 auto; }
.pic { position: relative; width: 100%; aspect-ratio: 4 / 3; max-height: 46%; border-radius: 22px; overflow: hidden; flex: none;
  display: grid; place-items: center; background: radial-gradient(circle at 50% 42%, var(--a-obj-hi), var(--a-obj-lo)); }
.frame { width: 100%; aspect-ratio: 4 / 3; max-height: 46%; border-radius: 22px; }
.pic img { width: 70%; height: 70%; object-fit: contain; }
.swatch { width: 64px; height: 64px; border-radius: 50%; box-shadow: 0 0 0 6px var(--a-surface); }
.bar { position: absolute; left: 0; right: 0; bottom: 0; height: 5px; background: color-mix(in srgb, var(--a-ink) 8%, transparent); }
.bar i { display: block; height: 100%; background: var(--a-accent); }
.head { font-size: 32px; margin: 0; }
.line { margin: -6px 0 0; font-size: 16px; color: var(--a-ink-3); }
.steps { display: grid; gap: 12px; }
.steps > span { display: flex; align-items: center; gap: 12px; }
.tiles { display: flex; gap: 9px; }
.tile { flex: 1; display: grid; gap: 7px; padding: 10px 12px; border-radius: 16px; background: var(--a-surface); font-size: 13.5px; color: var(--a-ink-2); }
.tile .a-sk { background-color: var(--a-surface-2); }
</style>
