<template>
  <!-- "Slicing like your prints" (design/getting-started/, c-slice-found): once, before the first model, what it
       found in their own files. Pick a model goes on to the file; the other settings in their files are a tap away. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open && view" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="view.title">
          <div class="grab" aria-hidden="true"></div>
          <h2 class="a-display">{{ view.title }}</h2>
          <p class="sub">{{ view.sub }}</p>
          <div class="rows">
            <div v-for="r in view.rows" :key="r.label" class="kv">
              <span class="k">{{ r.label }}</span>
              <span class="v">
                <b>{{ r.value }}</b>
                <small v-if="r.note" :class="{ problem: r.problem }">{{ r.note }}<span v-if="r.ok" class="ok" aria-label="agrees"> ✓</span></small>
              </span>
            </div>
          </div>
          <p v-if="error" class="err">{{ error }}</p>
          <button class="a-btn accent wide" :disabled="busy" @click="$emit('pick')">{{ view.button }}</button>
          <button v-if="view.others" class="link others" :disabled="busy" @click="$emit('others')">{{ view.others }}</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import type { FoundView } from '@/intent/profile'

defineProps<{ open: boolean; view: FoundView | null; busy: boolean; error: string | null }>()
defineEmits<{ close: []; pick: []; others: [] }>()
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(8, 12, 20, .38); display: flex; align-items: center; justify-content: center; padding: 24px; }
.sheet {
  background: var(--a-surface); color: var(--a-ink); border-radius: 26px; box-shadow: 0 -10px 40px rgba(16, 24, 40, .22);
  width: 100%; max-width: 520px; max-height: 100%; overflow-y: auto; padding: 12px 20px 30px; text-align: left;
}
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 14px; }
h2 { margin: 0; font-size: 26px; font-weight: 750; letter-spacing: -.025em; line-height: 1.06; }
.sub { margin: 8px 0 0; font-size: 16px; line-height: 1.4; color: var(--a-ink-2); }
.rows { margin-top: 14px; }
.kv { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 10px; padding: 10px 0; border-top: 1px solid var(--a-line); font-size: 16px; line-height: 1.35; }
.k { color: var(--a-ink-3); }
.v { min-width: 0; overflow-wrap: anywhere; }
.v b { font-weight: 650; }
.v small { display: block; color: var(--a-ink-3); font-size: 14px; margin-top: 2px; }
.v small.problem { color: var(--a-amber-text); }
.ok { color: var(--a-green-text); }
.wide { width: 100%; flex: none; height: 52px; min-height: 52px; padding: 0 16px; border-radius: 999px; font-size: 18px; font-weight: 650; margin-top: 16px; }
.link { appearance: none; border: 0; background: none; padding: 0; font: inherit; font-weight: 650; color: var(--a-accent-text); cursor: pointer; }
.link[disabled] { opacity: .5; cursor: default; }
.others { display: block; width: 100%; text-align: center; font-size: 16px; margin-top: 14px; padding: 4px 0; }
.err { margin: 12px 0 0; font-size: 14px; color: var(--a-red-text); }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px); }

/* a phone: from the bottom, 96 px below the top as drawn */
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { max-width: none; max-height: calc(100dvh - 96px); border-radius: 26px 26px 0 0; padding-bottom: calc(30px + env(safe-area-inset-bottom, 0px)); }
}
</style>
