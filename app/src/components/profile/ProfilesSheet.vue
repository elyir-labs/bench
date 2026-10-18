<template>
  <!-- The settings in their files, each with how many files used it (docs/slicer-profile.md): asked before the first
       slice when the files disagree, and the found sheet's "Other settings in your files". A tap slices like that one. -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open && view" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="view.title">
          <div class="grab" aria-hidden="true"></div>
          <button v-if="back" class="back link" :disabled="!!busy" @click="$emit('back')"><span v-html="BACK" aria-hidden="true"></span>{{ FOUND_TITLE }}</button>
          <h2 class="a-display">{{ view.title }}</h2>
          <p class="sub">{{ view.sub }}</p>
          <div class="list">
            <button
              v-for="r in view.rows" :key="r.id" class="row" :class="{ chosen: r.chosen }"
              :disabled="!!busy" :aria-pressed="r.chosen" @click="$emit('use', r.id)"
            >
              <span class="w">
                <b>{{ r.title }}</b>
                <small>{{ r.line }}</small>
                <small v-if="r.problem" class="problem">{{ r.problem }}</small>
              </span>
              <span v-if="busy === r.id" class="mark busy" aria-hidden="true">…</span>
              <span v-else-if="r.chosen" class="mark tick" aria-hidden="true" v-html="TICK"></span>
              <span v-else class="mark chev" aria-hidden="true" v-html="CHEVRON"></span>
            </button>
          </div>
          <p v-if="error" class="err">{{ error }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { FOUND_TITLE, type ListView } from '@/intent/profile'
import { BACK, CHEVRON, TICK } from '@/components/setup/icons'

// busy: the id being sent with profile_use
defineProps<{ open: boolean; view: ListView | null; back: boolean; busy: string | null; error: string | null }>()
defineEmits<{ close: []; back: []; use: [id: string] }>()
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(8, 12, 20, .38); display: flex; align-items: center; justify-content: center; padding: 24px; }
.sheet {
  background: var(--a-surface); color: var(--a-ink); border-radius: 26px; box-shadow: 0 -10px 40px rgba(16, 24, 40, .22);
  width: 100%; max-width: 520px; max-height: 100%; overflow-y: auto; padding: 12px 20px 30px; text-align: left;
}
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 14px; }
.link { appearance: none; border: 0; background: none; padding: 0; font: inherit; font-weight: 650; color: var(--a-accent-text); cursor: pointer; }
.back { display: inline-flex; align-items: center; gap: 2px; font-size: 16px; margin: 0 0 10px -6px; }
.back :deep(svg) { display: block; }
h2 { margin: 0; font-size: 26px; font-weight: 750; letter-spacing: -.025em; line-height: 1.06; }
.sub { margin: 8px 0 0; font-size: 16px; line-height: 1.4; color: var(--a-ink-2); }
/* as c-slice-pick draws its list: rows in a bordered card, the one in use ticked */
.list { margin-top: 16px; border: 1px solid var(--a-line); border-radius: 18px; overflow: hidden; }
.row {
  appearance: none; border: 0; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer;
  width: 100%; min-height: 64px; display: flex; align-items: center; gap: 12px; padding: 11px 16px;
}
.row + .row { border-top: 1px solid var(--a-line); }
.row:active { background: color-mix(in srgb, var(--a-ink) 4%, transparent); }
.row[disabled] { cursor: default; }
.w { flex: 1; min-width: 0; display: grid; gap: 2px; }
.w b { font-size: 17px; font-weight: 650; line-height: 1.3; overflow-wrap: anywhere; }
.w small { font-size: 14px; color: var(--a-ink-3); line-height: 1.35; }
.w small.problem { color: var(--a-amber-text); }
.mark { flex: none; display: grid; place-items: center; }
.mark :deep(svg) { display: block; }
.tick { color: var(--a-accent-text); }
.chev { color: var(--a-ink); opacity: .4; }
.busy { color: var(--a-ink-3); font-weight: 700; }
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
