<template>
  <!-- The one line, shown before it goes in (design/getting-started/, c-include); the same sheet takes it out -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="w.title">
          <div class="grab" aria-hidden="true"></div>
          <button class="back link" @click="$emit('back')"><span v-html="BACK" aria-hidden="true"></span>What works</button>
          <h2 class="a-display">{{ w.title }}</h2>
          <div class="line mono">{{ info.works.include_text }}</div>
          <template v-if="!w.removing">
            <p class="sub">It adds two macros (and <b>M600</b> if you have none). Your own PRINT_START and macros stay exactly as they are, and run as always.</p>
            <p class="sub next">Files {{ PRODUCT }} slices get them by themselves. In your own slicer, put them around the start G-code you have:</p>
          </template>
          <template v-else>
            <p class="sub">The two macros go with it (and <b>M600</b>, if it added one). Your own PRINT_START and macros stay exactly as they are.</p>
            <p class="sub next">Files {{ PRODUCT }} slices go back to your own start G-code by themselves. In your own slicer, take these two lines out again:</p>
          </template>
          <div class="slicer mono">
            <span class="lines">
              <b>{{ before[0] }}</b>{{ before[1] }}<br>
              <span class="yours">{{ INCLUDE_YOURS }}</span><br>
              <b>{{ after[0] }}</b>{{ after[1] }}
            </span>
            <button class="copy" :class="{ copied }" :aria-label="copied ? 'Copied' : 'Copy the two lines'" @click="copy" v-html="copied ? TICK : COPY"></button>
          </div>
          <p class="muted">{{ w.removing ? 'Klipper restarts to read it, about 10 seconds.' : 'Klipper restarts to read it, about 10 seconds. Remove it any time from here.' }}</p>
          <p v-if="info.works.include === 'failed' && info.works.include_why" class="err">{{ info.works.include_why }}</p>
          <p v-if="error" class="err">{{ error }}</p>
          <button
            class="a-btn wide go" :class="w.removing ? 'red' : 'accent'" :disabled="busy || !!w.busy"
            @click="w.removing ? $emit('remove') : $emit('add')"
          >{{ w.busy ?? w.button }}</button>
          <button class="a-btn wide plain" @click="$emit('close')">Not now</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { INCLUDE_YOURS, PRODUCT, includeWords, macroParts, slicerCopy, type SetupInfo } from '@/intent/setup'
import { BACK, COPY, TICK } from './icons'

const props = defineProps<{ open: boolean; info: SetupInfo; busy: boolean; error: string | null }>()
defineEmits<{ back: []; close: []; add: []; remove: [] }>()

const w = computed(() => includeWords(props.info.works.include))
const before = computed(() => macroParts(props.info.works.slicer_lines.before))
const after = computed(() => macroParts(props.info.works.slicer_lines.after))

// The printer's page is often plain http on the home Wi-Fi, where the clipboard API isn't offered
const copied = ref(false)
async function copy() {
  const text = slicerCopy(props.info.works.slicer_lines)
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const t = document.createElement('textarea')
    t.value = text
    t.setAttribute('readonly', '')
    t.style.position = 'fixed'
    t.style.opacity = '0'
    document.body.appendChild(t)
    t.select()
    document.execCommand('copy')
    t.remove()
  }
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 2000)
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(8, 12, 20, .38); display: flex; align-items: center; justify-content: center; padding: 24px; }
.sheet {
  background: var(--a-surface); color: var(--a-ink); border-radius: 26px; box-shadow: 0 -10px 40px rgba(16, 24, 40, .22);
  width: 100%; max-width: 520px; max-height: 100%; overflow-y: auto; padding: 12px 20px 30px; text-align: left;
}
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); margin: 0 auto 14px; }
.link { appearance: none; border: 0; background: none; padding: 0; font: inherit; font-weight: 650; color: var(--a-accent-text); cursor: pointer; }
.back { display: inline-flex; align-items: center; gap: 2px; font-size: 16px; margin-left: -6px; }
.back :deep(svg) { display: block; }
h2 { margin: 10px 0 0; font-size: 26px; font-weight: 750; letter-spacing: -.025em; line-height: 1.06; }
.mono { font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace; user-select: text; -webkit-user-select: text; }
.line { margin-top: 16px; background: #0b0e13; color: #fff; border-radius: 12px; padding: 14px 16px; font-size: 15px; }
.sub { margin: 16px 0 0; font-size: 16px; line-height: 1.45; color: var(--a-ink-2); }
.sub b { color: var(--a-ink); font-weight: 650; }
.sub.next { margin-top: 12px; }
.slicer { margin-top: 10px; display: flex; align-items: flex-start; gap: 10px; background: var(--a-surface-2); border-radius: 12px; padding: 10px 12px 10px 14px; font-size: 12.5px; }
.lines { flex: 1; min-width: 0; line-height: 1.5; overflow-wrap: anywhere; }
.lines b { font-weight: 700; }
.yours { color: var(--a-ink-3); }
.copy { appearance: none; border: 0; background: none; padding: 4px; margin: -4px -4px 0 0; color: var(--a-ink-3); cursor: pointer; display: grid; }
.copy.copied { color: var(--a-green-text); }
.copy :deep(svg) { display: block; width: 18px; height: 18px; }
.muted { margin: 14px 0 0; font-size: 14px; color: var(--a-ink-3); }
.err { margin: 10px 0 0; font-size: 14px; color: var(--a-red-text); }
.wide { width: 100%; flex: none; display: flex; align-items: center; justify-content: center; border-radius: 999px; font-weight: 650; padding: 0 16px; }
.go { height: 52px; min-height: 52px; font-size: 18px; margin-top: 18px; }
.plain { height: 48px; min-height: 48px; font-size: 17px; margin-top: 10px; background: transparent; color: var(--a-ink-2); }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px); }

/* a phone: from the bottom, 70 px below the top as drawn */
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { max-width: none; max-height: calc(100dvh - 70px); border-radius: 26px 26px 0 0; padding-bottom: calc(30px + env(safe-area-inset-bottom, 0px)); }
}
</style>
