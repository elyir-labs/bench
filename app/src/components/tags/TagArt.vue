<template>
  <!-- The reader on the desk with a tag over it (design/spool-tags/): rings while it waits, green once read or written -->
  <svg class="tag-art" viewBox="0 0 220 170" role="img" :aria-label="done ? 'Tag on the reader' : on ? 'Tag on the reader' : 'Hold a tag on the reader'">
    <rect x="30" y="96" width="160" height="56" rx="14" class="body" />
    <rect x="30" y="96" width="160" height="12" rx="6" class="lid" />
    <text x="110" y="146" text-anchor="middle" class="word">reader</text>
    <path d="M190 128c14 0 18 8 30 8" class="cable" />
    <g :transform="`translate(0 ${on || done ? 24 : 0})`" :class="{ lift: !on && !done }">
      <circle cx="110" cy="64" r="34" class="tag" :class="{ done, on }" />
      <circle cx="110" cy="64" r="22" class="coil" />
      <circle cx="110" cy="64" r="14" class="coil" />
      <text x="110" y="69" text-anchor="middle" class="label">tag</text>
    </g>
    <path v-if="!done" d="M150 52a26 26 0 0 1 0 30M160 44a40 40 0 0 1 0 46" class="waves" />
  </svg>
</template>

<script setup lang="ts">
defineProps<{ on?: boolean; done?: boolean }>()
</script>

<style scoped>
.tag-art { display: block; width: 100%; height: auto; }
.body { fill: var(--a-surface-2); }
.lid { fill: var(--a-surface); }
.word { fill: var(--a-ink-3); font: 600 13px var(--a-font, system-ui); }
.cable { fill: none; stroke: var(--a-surface-2); stroke-width: 5; }
.tag { fill: #e9eef7; stroke: var(--a-accent); stroke-width: 4; }
.tag.done { stroke: var(--a-green, #3dd68c); }
.coil { fill: none; stroke: #b7c0cf; stroke-width: 2; }
.label { fill: #56627a; font: 700 12px var(--a-font, system-ui); }
.waves { fill: none; stroke: var(--a-accent); stroke-width: 4; stroke-linecap: round; opacity: 0.8; }
.lift { animation: hover 1.8s ease-in-out infinite; }
@keyframes hover { 50% { transform: translateY(6px); } }
@media (prefers-reduced-motion: reduce) { .lift { animation: none; } }
</style>
