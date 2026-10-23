<template>
  <!-- The colour-change pause on a printer with a unit (design/colour-change/, A). On the panel, a tile per slot in
       two units (APause): its number, the spool, a colour word and one short line. Tapping a tile only picks it;
       the amber button below says what will happen. On a phone, the same spools as circles numbered from 1
       (APhone). The words are the intent layer's. -->
  <div class="cpick" :class="{ compact }">
    <template v-if="!compact">
      <div class="heads">
        <span v-for="(u, k) in units" :key="k" class="uhead" :style="{ '--n': u.tiles.length }">
          <span class="uname">{{ u.name }}</span>
          <span v-if="warm && k === units.length - 1" class="warm">{{ warm }}</span>
        </span>
      </div>
      <div class="tiles" role="radiogroup" aria-label="Which spool next">
        <div v-for="(u, k) in units" :key="k" class="unit" :style="{ '--n': u.tiles.length }">
          <button
            v-for="t in u.tiles" :key="t.slot" type="button" role="radio" class="tile"
            :class="['st-' + t.status, { on: t.slot === picked, off: !offered(t, away) }]"
            :aria-checked="t.slot === picked" :disabled="disabled || !offered(t, away)"
            :aria-label="`Slot ${t.slot + 1}: ${t.word}, ${t.sub}`"
            @click="$emit('pick', t.slot)"
          >
            <span class="num a-num">{{ t.slot + 1 }}</span>
            <span class="sw" :class="{ 'a-spool-ring': t.in_use, empty: t.status === 'empty' }"
                  :style="{ '--c': t.status === 'empty' ? 'transparent' : (t.color || 'transparent') }"></span>
            <b class="word">{{ t.word }}</b>
            <span class="sub" :class="t.tone">{{ t.sub }}</span>
          </button>
        </div>
      </div>
    </template>
    <div v-else class="dots" role="radiogroup" aria-label="Which spool next">
      <div v-for="(u, k) in units" :key="k" class="unit">
        <button
          v-for="t in u.tiles" :key="t.slot" type="button" role="radio" class="dot"
          :class="['st-' + t.status, { on: t.slot === picked, off: !offered(t, away) }]"
          :aria-checked="t.slot === picked" :disabled="disabled || !offered(t, away)"
          :aria-label="`Slot ${t.slot + 1}: ${t.word}, ${t.sub}`"
          @click="$emit('pick', t.slot)"
        >
          <span class="sw" :class="{ 'a-spool-ring': t.in_use, empty: t.status === 'empty' }"
                :style="{ '--c': t.status === 'empty' ? 'transparent' : (t.color || 'transparent') }"></span>
          <span class="n a-num">{{ t.slot + 1 }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { IntentColour } from '@/intent/types'
import { offered, unitsOf } from '@/intent/colour'

const props = defineProps<{ colour: IntentColour; picked: number | null; away: boolean; compact?: boolean; warm?: string; disabled?: boolean }>()
defineEmits<{ pick: [slot: number] }>()
const units = computed(() => unitsOf(props.colour))
</script>

<style scoped>
.cpick { margin-top: calc(8 * var(--u) + 2px); }
.heads { display: flex; gap: calc(18 * var(--u)); margin: 0 2px calc(5 * var(--u)); }
/* one row of tiles: each unit as wide as its slots (two ACEs 4 + 4, an ERCF 8), so a unit with more slots never
   wraps onto a second row the panel has no room for */
.uhead { flex: var(--n) 1 0%; display: flex; align-items: baseline; min-width: 0; }
.uname { font-size: calc(12 * var(--u) + 1px); font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.warm { margin-left: auto; font-size: calc(12 * var(--u) + 2px); color: var(--a-ink-3); white-space: nowrap; }
.tiles { display: flex; gap: calc(18 * var(--u)); }
.unit { flex: var(--n) 1 0%; display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: calc(9 * var(--u)); }
.tile {
  appearance: none; font: inherit; color: var(--a-ink); cursor: pointer; position: relative;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
  height: calc(98 * var(--u)); padding: calc(6 * var(--u)) 2px calc(5 * var(--u));
  border-radius: calc(13 * var(--u)); background: var(--a-surface); border: 2px solid transparent; min-width: 0;
}
.tile.on { border-color: var(--a-amber); background: color-mix(in srgb, var(--a-amber) 24%, var(--a-surface)); }
.tile[disabled] { cursor: default; }
.tile.off:not(.on) .word, .tile.off:not(.on) .sw { opacity: .55; }
.num { position: absolute; top: calc(5 * var(--u)); left: calc(8 * var(--u)); font-size: calc(12 * var(--u) + 1px); font-weight: 600; color: var(--a-ink-3); }
.sw {
  width: calc(40 * var(--u)); height: calc(40 * var(--u)); border-radius: 50%; flex: none; box-sizing: border-box;
  background: var(--c); border: 3px solid var(--a-swatch-edge); margin-bottom: calc(4 * var(--u));
}
.sw.empty { border-style: dashed; border-color: var(--a-swatch-empty); }
.tile > * { flex: none; }
.word { font-size: calc(15 * var(--u) + 1px); font-weight: 700; line-height: 1.15; white-space: nowrap; }
.st-empty .word { color: var(--a-ink-3); }
.sub { font-size: calc(12 * var(--u) + 1px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.sub.accent { color: var(--a-accent-text); }
.sub.amber { color: var(--a-amber-text); font-weight: 600; }

/* a phone: circles numbered underneath, two units with room between them */
.dots { display: flex; gap: 12px; justify-content: flex-start; }
.dots .unit { flex: none; display: flex; gap: 3px; }
.dot { appearance: none; font: inherit; background: none; border: 2px solid transparent; border-radius: 13px; cursor: pointer;
       display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 3px 1px 2px; color: var(--a-ink-3); }
.dot.on { border-color: var(--a-amber); background: color-mix(in srgb, var(--a-amber) 22%, transparent); color: var(--a-ink); }
.dot .sw { width: 32px; height: 32px; margin: 0; border-width: 2.5px; }
.dot .n { font-size: 12px; font-weight: 600; }
.dot.off .sw { opacity: .5; }
.dot[disabled] { cursor: default; }
</style>
