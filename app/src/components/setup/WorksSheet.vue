<template>
  <!-- What works on this printer, in three groups (design/getting-started/, c-works) -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="title">
          <div class="grab" aria-hidden="true"></div>
          <h2 class="a-display">{{ title }}</h2>
          <p class="muted">{{ WORKS_SUB }}</p>
          <template v-for="g in groups" :key="g.group">
            <span class="lbl">{{ g.label }}</span>
            <div v-for="f in g.items" :key="f.id" class="fitrow">
              <span v-if="g.group === 'now'" class="mark yes" v-html="TICK"></span>
              <span v-else-if="g.group === 'with_macro'" class="mark plus">+</span>
              <span v-else class="mark no">–</span>
              <span>{{ f.label }}<small v-if="f.note">{{ f.note }}</small></span>
            </div>
            <!-- the start macro: offered under what it brings; once it's in, taken out from here too -->
            <template v-if="g.group === macroGroup">
              <p v-if="include === 'failed' && info.works.include_why" class="err">{{ info.works.include_why }}</p>
              <button
                class="a-btn accent wide" :class="{ quiet: removing }" :disabled="busy || moving"
                @click="$emit('include')"
              >{{ buttonWords }}</button>
            </template>
          </template>
          <template v-if="differences.length || board?.note">
            <span class="lbl">On this board</span>
            <p v-if="board?.board" class="board">{{ board.board }}</p>
            <div v-for="(d, i) in differences" :key="i" class="fitrow">
              <span class="mark dot" aria-hidden="true"></span>
              <span>{{ d }}</span>
            </div>
            <p v-if="board?.note" class="note">{{ board.note }}</p>
          </template>
          <p v-if="error" class="err">{{ error }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ADD_MACRO, REMOVE_MACRO, WORKS_SUB, featureGroups, possessive, PRODUCT, type SetupInfo } from '@/intent/setup'
import { TICK } from './icons'

const props = defineProps<{ open: boolean; info: SetupInfo; busy: boolean; error: string | null }>()
defineEmits<{ close: []; include: [] }>()

const title = computed(() => `What works on ${props.info.name}`)
const groups = computed(() => featureGroups(props.info.works.features))
const include = computed(() => props.info.works.include)
const removing = computed(() => include.value === 'on' || include.value === 'removing')
const moving = computed(() => include.value === 'adding' || include.value === 'removing')
// The button sits under the start macro's group; once it's in, that group is empty, so under Works now.
const macroGroup = computed(() => (groups.value.some((g) => g.group === 'with_macro') ? 'with_macro' : removing.value ? 'now' : null))
const buttonWords = computed(() => {
  if (include.value === 'adding') return `Adding ${possessive(PRODUCT)} start macro…`
  if (include.value === 'removing') return `Taking ${possessive(PRODUCT)} start macro out…`
  return removing.value ? REMOVE_MACRO : ADD_MACRO
})
const board = computed(() => props.info.works.board ?? null)
const differences = computed(() => board.value?.differences ?? [])
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(8, 12, 20, .38); display: flex; align-items: center; justify-content: center; padding: 24px; }
.sheet {
  background: var(--a-surface); color: var(--a-ink); border-radius: 26px; box-shadow: 0 -10px 40px rgba(16, 24, 40, .22);
  width: 100%; max-width: 520px; max-height: 100%; overflow-y: auto; padding: 12px 20px 30px; text-align: left;
  user-select: text; -webkit-user-select: text;
}
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 14px; }
h2 { margin: 0; font-size: 26px; font-weight: 750; letter-spacing: -.025em; line-height: 1.06; }
.muted { margin: 6px 0 0; font-size: 15px; color: var(--a-ink-3); }
.lbl { display: block; margin-top: 18px; font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-3); }
.fitrow + .lbl { margin-top: 12px; }
.fitrow { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 10px; align-items: start; padding: 9px 0; font-size: 16px; line-height: 1.35; }
.fitrow small { display: block; color: var(--a-ink-3); font-size: 14px; }
.mark { display: grid; place-items: center; height: 22px; font-weight: 800; font-size: 20px; line-height: 20px; }
.mark :deep(svg) { display: block; }
.yes { color: var(--a-green-text); }
.plus { color: var(--a-accent-text); }
.no { color: var(--a-ink-3); }
.dot::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--a-ink-3); }
.wide { width: 100%; flex: none; height: 48px; min-height: 48px; padding: 0 16px; border-radius: 999px; font-size: 17px; font-weight: 650; margin-top: 8px; }
.wide.quiet { background: var(--a-ghost-bg); border: 1px solid var(--a-line); color: var(--a-ink-2); }
.board { margin: 8px 0 0; font-size: 15px; color: var(--a-ink-2); }
.note { margin: 6px 0 0; font-size: 14px; color: var(--a-ink-3); }
.err { margin: 10px 0 0; font-size: 14px; color: var(--a-red-text); }

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
