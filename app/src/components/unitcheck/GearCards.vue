<template>
  <!-- Each slot while the encoder measures (boards gc-encoder, gc-phone): slot 1 by ruler, the others by encoder -->
  <div v-for="c in cards" :key="c.slot" class="chk" :class="cls(c)">
    <span class="h"><span class="sw" :class="{ empty: c.state === 'next' || c.state === 'skipped' }"></span>{{ c.label }}</span>
    <span class="l">
      <span v-if="c.state === 'ok'" class="y">✓</span><span v-else-if="c.state === 'failed' || c.state === 'kept'" class="q">!</span><span v-else-if="c.state === 'now'" class="spin"></span>{{ c.line }}
    </span>
    <span v-if="c.sub" class="l sub">{{ c.sub }}</span>
  </div>
</template>

<script setup lang="ts">
import type { GearCard } from '@/intent/unitCheck'

defineProps<{ cards: GearCard[] }>()
const cls = (c: GearCard) => ({ now: 'now', failed: 'warn', kept: 'warn', next: 'next', skipped: 'next', ok: '' }[c.state])
</script>

<style scoped>
.chk { background: var(--a-surface); border-radius: 16px; padding: 10px 12px; display: grid; gap: 5px; align-content: start; box-shadow: var(--a-card-shadow); border: 2px solid transparent; min-height: 60px; }
.chk.now { border-color: var(--a-accent); }
.chk.warn { border-color: var(--a-amber); }
.chk.next { background: transparent; box-shadow: none; border: 1.5px dashed var(--a-line); }
.h { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; }
.sw { width: 20px; height: 20px; border-radius: 50%; background: var(--a-ink-3); border: 2px solid var(--a-swatch-edge); box-sizing: border-box; flex: none; }
.sw.empty { background: transparent; border-style: dashed; border-color: var(--a-swatch-empty); }
.l { font-size: 13.5px; color: var(--a-ink-3); display: flex; align-items: center; gap: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.l.sub { margin-top: -2px; }
.y { color: var(--a-green-text); font-weight: 700; }
.q { color: var(--a-amber-text); font-weight: 700; }
.spin { width: 14px; height: 14px; border-radius: 50%; border: 2.5px solid var(--a-surface-2); border-top-color: var(--a-accent); flex: none; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
