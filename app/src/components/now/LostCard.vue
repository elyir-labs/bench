<template>
  <!-- A print the power took (design/power-loss/, A): on the panel it takes the Print again card's place -->
  <div class="lost" :class="{ compact }">
    <ObjectImage :src="thumb" :alt="lost.name" class="lost-img" />
    <div class="lost-text">
      <small>Stopped by a power cut</small>
      <b class="a-display">{{ lost.name }}</b>
      <span class="a-num">{{ doneWords(lost) }}</span>
      <div class="acts">
        <button class="a-btn accent" :disabled="disabled" @click="$emit('rest')">Print the rest</button>
        <button class="a-btn ghost" :disabled="disabled" @click="$emit('again')">Start over</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import ObjectImage from './ObjectImage.vue'
import type { LostView } from '@/intent/types'
import { doneWords } from '@/intent/lost'

defineProps<{ lost: LostView; thumb: string | null; compact?: boolean; disabled?: boolean }>()
defineEmits<{ rest: []; again: [] }>()
</script>

<style scoped>
.lost {
  justify-self: end; align-self: center;
  display: flex; flex-direction: column;
  width: calc(240 * var(--u) + 60px);
  border-radius: calc(20 * var(--u) + 6px);
  overflow: hidden;
  background: color-mix(in srgb, var(--a-amber) 18%, var(--a-surface));
  box-shadow: var(--a-card-shadow);
}
.lost-img { width: 100%; aspect-ratio: 2 / 1; }
.lost-img :deep(img) { position: absolute; inset: 0; }   /* the box's height, not the picture's own */
.lost-text { display: flex; flex-direction: column; gap: 2px; padding: calc(10 * var(--u) + 4px) calc(16 * var(--u) + 4px) calc(14 * var(--u) + 4px); }
small { font-size: calc(9 * var(--u) + 4px); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--a-amber-text); }
b { font-size: calc(20 * var(--u) + 6px); }
span { font-size: calc(12 * var(--u) + 4px); color: var(--a-ink-2); }
.acts { display: flex; gap: 8px; margin-top: calc(8 * var(--u) + 2px); }
.acts .a-btn { min-height: calc(34 * var(--u) + 10px); font-size: calc(12 * var(--u) + 5px); padding: 0 calc(10 * var(--u) + 4px); border-radius: 14px; white-space: nowrap; }

.compact { justify-self: stretch; width: auto; margin-top: 14px; }
.compact .lost-img { aspect-ratio: 5 / 2; }
.compact b { font-size: 22px; }
.compact span { font-size: 15px; }
.compact .acts .a-btn { flex: 1; min-height: 46px; font-size: 16px; }
</style>
