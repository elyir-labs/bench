<template>
  <!-- − n + for how many copies (design/plate/, A). Tapping fast is fine: the slice waits for the taps to stop. -->
  <span class="step" :class="{ big }" role="group" :aria-label="label">
    <!-- bin: at its least the − takes the part off instead (design/remove-parts/, C) -->
    <button v-if="bin && value <= min" type="button" class="bin" aria-label="Take it off the plate" @click="$emit('remove')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v6M14 11v6" /></svg>
    </button>
    <button v-else type="button" :disabled="value <= min" :aria-label="`One fewer`" @click="$emit('change', value - 1)">−</button>
    <b class="a-num" aria-live="polite">{{ shown ?? value }}</b>
    <button type="button" :disabled="value >= max" :aria-label="`One more`" @click="$emit('change', value + 1)">+</button>
  </span>
</template>

<script setup lang="ts">
// shown: what to show instead of the number (a setting's value, design/edit-settings/: value is then its step)
withDefaults(defineProps<{ value: number; min?: number; max?: number; big?: boolean; label?: string; shown?: string; bin?: boolean }>(), { min: 1, max: 200, label: 'How many' })
defineEmits<{ change: [n: number]; remove: [] }>()
</script>

<style scoped>
.step { display: inline-flex; align-items: center; flex: none; background: var(--a-surface-2); border-radius: 99px; height: 40px; }
.step button { appearance: none; border: 0; background: none; font: inherit; cursor: pointer; width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; font-size: 22px; font-weight: 600; color: var(--a-ink-2); }
.step button:disabled { opacity: 0.3; cursor: default; }
.step button.bin { color: var(--a-red, #c0392b); }
.step button.bin svg { width: 18px; height: 18px; }
.step button:focus-visible { outline: 2px solid var(--a-accent); outline-offset: -2px; }
.step b { min-width: 26px; text-align: center; font-size: 17px; }
.step.big { height: 56px; }
.step.big button { width: 56px; height: 56px; font-size: 30px; }
.step.big b { min-width: 48px; font-size: 28px; letter-spacing: -0.02em; }
</style>
