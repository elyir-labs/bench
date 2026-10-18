<template>
  <!-- A sheet from How it prints (design/bench-how/, A-purpose): a title, a line under it, the choices, and what keeping
       them means. Each choice is saved as it's tapped, so Done only closes it. -->
  <div v-if="open" class="hscrim" @click.self="$emit('close')">
    <div class="hsheet" role="dialog" aria-modal="true" :aria-label="title">
      <div class="top">
        <h2 class="a-display">{{ title }}</h2>
        <p v-if="sub" class="muted">{{ sub }}</p>
      </div>
      <div class="body"><slot /></div>
      <div class="foot">
        <span class="muted">{{ kept ?? `Kept with ${model}: next time, and on whichever printer takes it, it prints this way.` }}</span>
        <button class="a-btn accent" @click="$emit('close')">Done</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ open: boolean; title: string; sub?: string; model: string; kept?: string }>()
defineEmits<{ close: [] }>()
</script>

<style scoped>
.hscrim { position: fixed; inset: 0; background: rgba(16, 20, 28, .42); display: grid; place-items: center; z-index: 20; padding: 16px; }
.hsheet { width: min(640px, 100%); max-height: calc(100dvh - 32px); box-sizing: border-box; background: var(--a-surface); border-radius: 24px;
          box-shadow: var(--a-card-shadow); display: flex; flex-direction: column; overflow: hidden; }
.top { padding: 24px 24px 14px; display: grid; gap: 8px; }
.top h2 { margin: 0; font-size: 32px; letter-spacing: -.02em; line-height: 1.1; }
.top p { margin: 0; font-size: 16px; }
.muted { color: var(--a-ink-3); }
.body { overflow: auto; min-height: 0; }
.foot { display: flex; align-items: center; gap: 16px; padding: 16px 22px; border-top: 1px solid var(--a-line); }
.foot .muted { flex: 1; min-width: 0; font-size: 15px; }
.foot .a-btn { width: auto; flex: none; height: 50px; font-size: 18px; padding: 0 26px; }
@media (max-width: 599px) {
  .hscrim { place-items: end stretch; padding: 0; }
  .hsheet { width: 100%; border-radius: 24px 24px 0 0; max-height: 92dvh; }
  .top { padding: 18px 18px 10px; } .top h2 { font-size: 24px; } .top p { font-size: 14px; }
  .foot { padding: 12px 16px calc(12px + env(safe-area-inset-bottom, 0px)); } .foot .muted { font-size: 13px; }
  .foot .a-btn { height: 46px; font-size: 16px; padding: 0 20px; }
}
</style>
