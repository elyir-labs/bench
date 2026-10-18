<template>
  <!-- A mark big enough to read from across the room. Amber = needs a person, red = something stopped. -->
  <div class="glyph" :class="kind" aria-hidden="true">
    <svg v-if="kind === 'problem'" viewBox="0 0 100 100">
      <path d="M50 8 L94 84 H6 Z" fill="var(--a-red)" stroke="var(--a-red)" stroke-width="10" stroke-linejoin="round"/>
      <rect x="45" y="34" width="10" height="28" rx="5" fill="var(--a-red-ink)"/>
      <circle cx="50" cy="72" r="6" fill="var(--a-red-ink)"/>
    </svg>
    <svg v-else viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="44" fill="var(--a-amber)"/>
      <rect x="45" y="24" width="10" height="34" rx="5" fill="var(--a-amber-ink)"/>
      <circle cx="50" cy="71" r="6.5" fill="var(--a-amber-ink)"/>
    </svg>
  </div>
</template>

<script setup lang="ts">
defineProps<{ kind: 'needs_you' | 'problem' }>()
</script>

<style scoped>
.glyph {
  --size: calc(132 * var(--u) + 22px);
  width: var(--size);
  height: var(--size);
  display: grid;
  place-items: center;
  border-radius: 50%;
  justify-self: end;
}
.glyph svg { width: 100%; height: 100%; display: block; }
.glyph.needs_you { filter: drop-shadow(0 0 calc(18 * var(--u) + 6px) color-mix(in srgb, var(--a-amber) 45%, transparent)); }
.glyph.problem { filter: drop-shadow(0 0 calc(18 * var(--u) + 6px) color-mix(in srgb, var(--a-red) 45%, transparent)); }
@media (prefers-reduced-motion: no-preference) {
  .glyph.needs_you svg { animation: breathe 2.4s ease-in-out infinite; }
  @keyframes breathe { 50% { transform: scale(0.96); opacity: 0.9; } }
}
</style>
