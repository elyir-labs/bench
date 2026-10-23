<template>
  <!-- A big number pad for what the ruler says (design/unit-setup/ boards gb-pad, gb-phone) -->
  <div class="kpad">
    <button v-for="k in KEYS" :key="k" type="button" class="key" :class="{ fn: k === '.' || k === '⌫' }"
            :aria-label="k === '⌫' ? 'Delete' : k === '.' ? 'Point' : k" :disabled="disabled" @click="emit('press', k)">
      <svg v-if="k === '⌫'" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h10a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 18H9l-5.5-6z M12 9.5l5 5 M17 9.5l-5 5" /></svg>
      <template v-else>{{ k }}</template>
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ press: [key: string] }>()
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', '⌫']
</script>

<style scoped>
.kpad { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.key { appearance: none; border: 0; height: 52px; border-radius: 14px; background: var(--a-surface); box-shadow: var(--a-card-shadow);
  font: 600 26px var(--a-display); color: var(--a-ink); cursor: pointer; display: grid; place-items: center; padding: 0; }
.key.fn { background: transparent; box-shadow: none; border: 1.5px solid var(--a-line); color: var(--a-ink-2); }
.key svg { width: 26px; height: 26px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linejoin: round; stroke-linecap: round; }
.key:active:not([disabled]) { transform: scale(0.97); }
.key[disabled] { opacity: 0.5; cursor: default; }
@media (max-width: 599px) {
  .kpad { gap: 10px; }
  .key { height: 56px; font-size: 27px; border-radius: 16px; }
}
</style>
