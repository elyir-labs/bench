<template>
  <!-- Newer prints use other settings (design/getting-started/, c-slice-newer): offered on one line, never a switch -->
  <div class="newer" role="region" aria-label="Newer settings in your files">
    <span class="t"><b>{{ offer.text }}</b> <span class="ask">{{ offer.ask }}</span></span>
    <small v-if="offer.problem" class="problem">{{ offer.problem }}</small>
    <div class="btns">
      <button class="btn accent" :disabled="!!busy" @click="$emit('use')">{{ busy === 'use' ? '…' : offer.use }}</button>
      <button class="btn" :disabled="!!busy" @click="$emit('keep')">{{ busy === 'keep' ? '…' : offer.keep }}</button>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import type { NewerOffer } from '@/intent/profile'

defineProps<{ offer: NewerOffer; busy: 'use' | 'keep' | null; error: string | null }>()
defineEmits<{ use: []; keep: [] }>()
</script>

<style scoped>
.newer {
  display: grid; gap: 10px; padding: 14px 16px; margin: calc(12 * var(--u)) 0 0; border-radius: 20px; text-align: left;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); border: 1px solid var(--a-tint-blue);
}
.t { font-size: 16px; line-height: 1.35; color: var(--a-ink); }
.t b { font-weight: 650; }
.ask { color: var(--a-ink-2); }
.problem { font-size: 14px; color: var(--a-amber-text); line-height: 1.35; }
.btns { display: flex; gap: 10px; flex-wrap: wrap; }
.btn {
  appearance: none; font: inherit; cursor: pointer; white-space: nowrap;
  height: 40px; padding: 0 18px; border-radius: 999px; font-size: 15px; font-weight: 650;
  background: var(--a-ghost-bg); border: 1px solid var(--a-line); color: var(--a-ink-2);
}
.btn.accent { background: var(--a-accent); border-color: transparent; color: var(--a-accent-ink); }
.btn[disabled] { opacity: .6; cursor: default; }
.err { margin: 0; font-size: 14px; color: var(--a-red-text); }
</style>
