<template>
  <!-- The bottom sheet every row on the Ready page opens: a title, a line under it, the choices. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="scrim" @click.self="$emit('close')">
        <div class="sheet" :class="{ amber, wide }" role="dialog" aria-modal="true" :aria-label="title">
          <div class="grab" aria-hidden="true"></div>
          <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
          <h2 class="a-display title">{{ title }}</h2>
          <p v-if="sub" class="sub">{{ sub }}</p>
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{ open: boolean; title: string; sub?: string; eyebrow?: string; amber?: boolean; wide?: boolean }>()
defineEmits<{ close: [] }>()
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.45);
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
}
.sheet {
  background: var(--a-bg);
  border-radius: 26px;
  box-shadow: var(--a-card-shadow);
  max-width: 520px; width: 100%;
  max-height: 100%; overflow: auto;
  padding: 10px 20px calc(24px + var(--safe-b, 0px));
}
.sheet.wide { max-width: 760px; }
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-ink-3); opacity: 0.5; margin: 0 auto 12px; }
.eyebrow { margin: 0 0 4px; font-size: 12.5px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; color: var(--a-ink-3); }
.amber .eyebrow { color: var(--a-amber-text); }
.title { font-size: 23px; letter-spacing: -0.02em; margin: 0; }
.sub { color: var(--a-ink-3); font-size: 14.5px; margin: 4px 0 14px; line-height: 1.35; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px); }
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 26px 26px 0 0; max-width: none; }
}
@media (prefers-reduced-motion: reduce) {
  .sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: none; }
}
</style>
