<template>
  <!-- Print the rest (design/power-loss/, A): the top as its own part; on top of what's there isn't offered yet -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="scrim" :class="{ phone: !panel }" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="`Print the rest of ${lost.name}`">
          <div v-if="!panel" class="grab" aria-hidden="true"></div>
          <h2 class="a-display">Print the rest of {{ lost.name }}</h2>
          <p class="sub">{{ restWords(lost) }}</p>
          <div class="split">
            <ObjectImage :src="thumb" :alt="lost.name" class="pic" />
            <div class="ways">
              <div class="way" :class="{ on: can, off: !can }">
                <span class="radio" :class="{ on: can }"></span>
                <span class="t"><b>The top on its own</b><span>{{ can ? 'On a clean plate. Glue the halves (superglue for PLA).' : why }}</span></span>
              </div>
              <div class="way off">
                <span class="radio"></span>
                <span class="t"><b>On top of what's there</b><span>Not on {{ printer }}: it can't find its height again over the part.</span></span>
              </div>
            </div>
          </div>
          <p v-if="error" class="err">{{ error }}</p>
          <div class="acts">
            <button v-if="can" class="a-btn accent" :disabled="busy" @click="$emit('rest')">{{ busy ? 'Getting it ready…' : 'Print the rest' }}</button>
            <button class="a-btn ghost" :disabled="busy" @click="$emit('again')">Start over</button>
            <button v-if="!can" class="a-btn ghost" @click="$emit('close')">Not now</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ObjectImage from './ObjectImage.vue'
import type { LostView } from '@/intent/types'
import { restWords } from '@/intent/lost'
import { layout } from '@/shell/useLayout'

// why: when the rest can't be sliced here (the panel, away, or a file sliced elsewhere), in its row's place
const props = defineProps<{ open: boolean; lost: LostView; thumb: string | null; printer: string; why: string | null; busy?: boolean; error?: string }>()
defineEmits<{ close: []; rest: []; again: [] }>()
const panel = computed(() => layout.value === 'panel')
const can = computed(() => !props.why)
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(16 * var(--u) + 6px); }
.sheet { background: var(--a-surface); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 760px; width: 100%; max-height: 100%; overflow: auto; padding: calc(16 * var(--u) + 8px) calc(20 * var(--u) + 10px); }
h2 { margin: 0; font-size: calc(22 * var(--u) + 8px); line-height: 1.1; letter-spacing: -.025em; }
.sub { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 5px); margin: 6px 0 calc(10 * var(--u) + 4px); line-height: 1.35; }
.split { display: grid; grid-template-columns: calc(180 * var(--u) + 70px) 1fr; gap: calc(16 * var(--u) + 6px); align-items: center; }
.pic { width: 100%; aspect-ratio: 4 / 3; border-radius: 18px; background: var(--a-surface-2); }
.pic :deep(img) { position: absolute; inset: 0; }
.ways { display: grid; gap: 10px; }
.way { display: flex; gap: 14px; align-items: center; padding: 12px 16px; border-radius: 16px; border: 1px solid var(--a-line); }
.way.on { border-color: var(--a-accent); box-shadow: 0 0 0 1px var(--a-accent); }
.way.off { opacity: .55; }
.t { flex: 1; display: grid; gap: 2px; }
.t b { font-size: calc(13 * var(--u) + 6px); }
.t span { font-size: calc(10 * var(--u) + 5px); color: var(--a-ink-3); line-height: 1.3; }
.radio { width: 24px; height: 24px; border-radius: 50%; border: 2px solid var(--a-ink-3); flex: none; }
.radio.on { border: 7px solid var(--a-accent); }
.acts { display: flex; gap: 12px; margin-top: calc(12 * var(--u) + 6px); }
.acts .a-btn { min-height: calc(40 * var(--u) + 14px); font-size: calc(14 * var(--u) + 6px); border-radius: 18px; padding: 0 calc(16 * var(--u) + 6px); }
.err { color: var(--a-red-text); font-size: 15px; margin: 10px 0 0; }

.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-ink-3); opacity: .5; margin: 0 auto 12px; }
.phone .sheet { background: var(--a-bg); }
.phone .split { grid-template-columns: 1fr; }
.phone .pic { aspect-ratio: 2 / 1; }
.phone .acts { flex-direction: column; }
.phone .acts .a-btn { width: 100%; min-height: 52px; font-size: 18px; }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .scrim.phone { align-items: flex-end; padding: 0; background: rgba(8, 12, 20, .38); }
  .phone .sheet { border-radius: 28px 28px 0 0; padding: 10px 20px 28px; max-width: none; box-shadow: 0 -10px 40px rgba(16, 24, 40, .25); }
}
</style>
