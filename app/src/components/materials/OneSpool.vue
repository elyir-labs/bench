<template>
  <!-- A printer without a filament unit: the spool is the page (design/one-spool/, direction B). -->
  <div class="one" :class="{ away: door.away }">
    <div v-if="view.question" class="ask" :class="view.question.tone" role="status">
      <div class="words">
        <b>{{ view.question.headline }}</b>
        <span>{{ view.question.detail }}</span>
      </div>
      <button
        v-if="view.question.confirm && !door.away"
        class="a-btn accent confirm"
        :disabled="!!store.busyAction"
        @click="save(view.question.confirm)"
      >{{ view.question.confirm.label }}</button>
      <div v-if="view.question.answers.length && !door.away" class="answers">
        <button
          v-for="a in view.question.answers"
          :key="a.label"
          class="answer"
          :class="{ same: a.label === 'Same as before' }"
          :disabled="!!store.busyAction"
          @click="save(a)"
        ><span class="dot" :style="{ '--c': a.color || 'transparent' }"></span>{{ a.label }}</button>
      </div>
    </div>

    <div class="spool" :class="{ asking: !!view.question && view.look === 'changed' }">
      <div class="art-wrap">
        <span
          class="art"
          :class="[view.look, { 'a-spool-ring': spool.in_use && feeding, turning: feeding }]"
          :style="{ '--c': artColor }"
        ><i v-if="view.look === 'guess' || view.look === 'changed' || view.look === 'unknown'" class="q">?</i></span>
      </div>
      <div class="side">
        <div v-if="view.look !== 'changed'" class="name">
          <small>On the printer<span v-if="view.pill" class="pill">{{ view.pill }}</span></small>
          <b class="a-display">{{ view.title }}</b>
          <span v-if="view.meta && !view.question" class="meta a-num">{{ view.meta }}</span>
        </div>

        <template v-if="view.editable">
          <div class="label">Material</div>
          <div class="chips" role="radiogroup" aria-label="Material">
            <button
              v-for="m in MATERIALS"
              :key="m"
              class="chip"
              :class="{ on: view.material === m && !view.maybe, maybe: view.material === m && view.maybe }"
              role="radio"
              :aria-checked="view.material === m"
              :disabled="door.away || !!store.busyAction"
              @click="tap({ material: m })"
            >{{ m }}</button>
          </div>
          <div class="label">Color</div>
          <div class="colours" role="radiogroup" aria-label="Color">
            <button
              v-for="c in COLORS"
              :key="c.hex"
              class="colour"
              :class="{ on: shownColor === c.hex && !view.maybe, maybe: shownColor === c.hex && view.maybe }"
              :style="{ '--c': c.hex }"
              role="radio"
              :aria-label="c.name"
              :aria-checked="shownColor === c.hex"
              :disabled="door.away || !!store.busyAction"
              @click="tap({ color: c.hex })"
            ></button>
          </div>
        </template>
        <!-- Changing filament starts here and runs on Now (design/change-filament/, B) -->
        <div v-if="moves.length" class="moves">
          <button
            v-for="a in moves"
            :key="a.label"
            class="a-btn"
            :class="a.primary ? 'accent' : 'ghost'"
            :disabled="!!store.busyAction"
            @click="start(a)"
          >{{ store.busyAction === a.id ? '…' : a.label }}</button>
          <span v-if="spool.note" class="hint">{{ spool.note }}</span>
        </div>
        <p v-else class="note">{{ note }}</p>
      </div>
    </div>

    <Transition name="toast">
      <div v-if="undo" class="toast" role="status">
        <span>Changed to {{ undo.now }}</span>
        <button class="undo" :disabled="!!store.busyAction" @click="putBack">Undo</button>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { IntentAction, IntentSpool } from '@/intent/types'
import { allowedHere, door } from '@/door'
import { COLORS, MATERIALS } from './palette'
import { oneSpoolView, tapToSave, undoTarget, type QuickAnswer } from './oneSpool'

const props = defineProps<{ spool: IntentSpool; feeding?: boolean }>()
const store = useIntentStore()

// "3 days ago" moves on by itself
const now = ref(new Date())
const clock = setInterval(() => { now.value = new Date() }, 60_000)
onBeforeUnmount(() => { clearInterval(clock); clearTimeout(undoTimer) })

const view = computed(() => oneSpoolView(props.spool, now.value))
const router = useRouter()
const moves = computed(() => (props.spool.actions ?? []).filter((a) => allowedHere(a.id)))
async function start(a: IntentAction) {
  await store.act(a)
  if (!store.actionError) router.push('/')
}
const pendingColor = ref<string | null>(null)
watch(() => [props.spool.material, props.spool.changed, props.spool.status], () => { pendingColor.value = null })

const shownColor = computed(() => pendingColor.value ?? view.value.color)
const artColor = computed(() => {
  if (view.value.look === 'changed') return props.spool.was?.color || 'transparent'
  if (view.value.look === 'unknown' || view.value.look === 'empty') return 'transparent'
  return pendingColor.value ?? props.spool.color ?? 'transparent'
})
const note = computed(() => {
  if (door.away) return 'Change the spool at the printer.'
  if (pendingColor.value) return 'Now tap the material.'
  return view.value.note
})

// Every tap saves. A stray one can be put back for a few seconds, when what was there was yours.
const undo = ref<{ now: string; back: QuickAnswer } | null>(null)
let undoTimer: ReturnType<typeof setTimeout> | undefined

async function send(material: string, color: string | null) {
  await store.act('set_spool', { slot: props.spool.slot, material, color })
}

async function save(a: { material: string; color: string | null }, offerUndo = true) {
  const back = offerUndo ? undoTarget(props.spool) : null
  await send(a.material, a.color)
  if (store.actionError) return
  clearTimeout(undoTimer)
  undo.value = null
  if (back && (back.material !== a.material || back.color !== a.color)) {
    const colour = COLORS.find(c => c.hex.toUpperCase() === (a.color ?? '').toUpperCase())?.name
    undo.value = { now: colour ? `${colour} ${a.material}` : a.material, back }
    undoTimer = setTimeout(() => { undo.value = null }, 6000)
  }
}

async function tap(t: { material?: string; color?: string }) {
  const r = tapToSave(view.value, t, pendingColor.value)
  pendingColor.value = r.pendingColor
  if (r.send) await save(r.send)
}

async function putBack() {
  if (!undo.value) return
  const back = undo.value.back
  await save(back, false)
}
</script>

<style scoped>
.one { display: flex; flex-direction: column; gap: calc(10 * var(--u) + 2px); position: relative; }

/* The question: a guess (plain) or "New filament?" (amber). Its answers are one tap. */
.ask {
  display: flex; align-items: center; flex-wrap: wrap; gap: calc(12 * var(--u) + 4px);
  background: var(--a-surface); box-shadow: var(--a-card-shadow);
  border-radius: calc(16 * var(--u) + 4px);
  padding: calc(9 * var(--u) + 3px) calc(12 * var(--u) + 4px) calc(9 * var(--u) + 3px) calc(16 * var(--u) + 4px);
}
.ask.amber { background: color-mix(in srgb, var(--a-amber) 26%, var(--a-surface)); }
.words { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; font-size: calc(14 * var(--u) + 4px); }
.words b { font-size: calc(16 * var(--u) + 4px); }
.words span { color: var(--a-ink-2); }
.confirm { flex: none; font-size: calc(16 * var(--u) + 4px); padding: calc(10 * var(--u) + 3px) calc(18 * var(--u) + 6px); }
.answers { flex-basis: 100%; display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 2px); }
.answer {
  appearance: none; font: inherit; font-weight: 600; cursor: pointer; color: var(--a-ink);
  display: inline-flex; align-items: center; gap: 8px; white-space: nowrap;
  font-size: calc(14 * var(--u) + 4px); min-height: 44px;
  padding: 0 calc(13 * var(--u) + 4px) 0 calc(7 * var(--u) + 2px);
  border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-surface);
}
.answer.same { border-color: var(--a-amber); }
.answer .dot { width: calc(20 * var(--u) + 6px); height: calc(20 * var(--u) + 6px); border-radius: 50%; background: var(--c); border: 2px solid var(--a-swatch-edge); }

/* The spool and what it is */
.spool { display: grid; grid-template-columns: calc(120 * var(--u) + 40px) 1fr; gap: calc(24 * var(--u) + 6px); align-items: start; }
.spool.asking { grid-template-columns: calc(90 * var(--u) + 28px) 1fr; }
.art-wrap { display: grid; justify-items: center; padding-top: 6px; }
.art {
  position: relative; display: grid; place-items: center;
  width: 100%; aspect-ratio: 1; border-radius: 50%; box-sizing: border-box;
  border: 5px solid var(--a-swatch-edge);
  background-color: var(--c);
  background-image:
    radial-gradient(circle, var(--a-bg) 0 12%, var(--a-surface-2) 12.5% 27%, rgba(0,0,0,.28) 27.5% 29%, transparent 29.5%),
    repeating-radial-gradient(circle, rgba(255,255,255,.07) 0 1px, transparent 1.5px 6px);
}
.art.guess { border-style: dashed; border-color: var(--a-ink-3); }
.art.changed { background-color: color-mix(in srgb, var(--c) 40%, transparent); border-color: var(--a-amber); }
.art.unknown, .art.empty {
  background-color: transparent; border-style: dashed; border-color: var(--a-swatch-empty);
  background-image: radial-gradient(circle, var(--a-surface-2) 0 27%, transparent 27.5%);
}
.art .q {
  position: absolute; right: -4%; bottom: -4%; width: 28%; aspect-ratio: 1; border-radius: 50%;
  display: grid; place-items: center; font-style: normal; font-weight: 800; line-height: 1;
  font-size: calc(18 * var(--u) + 6px); background: var(--a-surface-2); color: var(--a-ink);
  box-shadow: 0 0 0 3px var(--a-bg);
}
.art.changed .q { background: var(--a-amber); color: var(--a-amber-ink); }
.art.unknown .q { position: static; width: auto; background: none; box-shadow: none; color: var(--a-ink-3); font-size: calc(40 * var(--u) + 12px); }

.side { min-width: 0; }
.name { display: flex; flex-direction: column; gap: 2px; }
.name small {
  display: flex; align-items: center; gap: 8px;
  font-size: calc(9 * var(--u) + 3.5px); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--a-ink-3);
}
.pill { font-size: calc(7.5 * var(--u) + 3px); font-weight: 700; letter-spacing: .05em; padding: 3px 8px; border-radius: 99px; background: rgba(127,127,127,.18); color: var(--a-ink-2); }
.name b { font-size: calc(22 * var(--u) + 6px); font-weight: 700; letter-spacing: -.02em; line-height: 1.1; }
.meta { font-size: calc(12 * var(--u) + 4px); color: var(--a-ink-2); }
.label {
  font-size: calc(9 * var(--u) + 4px); font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--a-ink-3);
  margin: calc(8 * var(--u) + 2px) 0 calc(4 * var(--u) + 2px);
}
.chips { display: flex; flex-wrap: wrap; gap: calc(6 * var(--u) + 2px); }
.chip {
  appearance: none; font: inherit; cursor: pointer;
  min-height: calc(30 * var(--u) + 12px); padding: 0 calc(12 * var(--u) + 4px); border-radius: 99px;
  font-weight: 700; font-size: calc(13 * var(--u) + 4px); letter-spacing: .03em;
  border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2);
}
.chip.on { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-accent-ink); }
.chip.maybe { border: 2px dashed var(--a-accent); color: var(--a-accent-text); }
.colours { display: grid; grid-template-columns: repeat(8, calc(22 * var(--u) + 8px)); gap: calc(8 * var(--u) + 2px); }
.colour {
  appearance: none; cursor: pointer; padding: 0;
  width: calc(22 * var(--u) + 8px); aspect-ratio: 1; border-radius: 50%; box-sizing: border-box;
  background: var(--c); border: 3px solid var(--a-swatch-edge);
}
.colour.on { outline: 3px solid var(--a-accent); outline-offset: 3px; }
.colour.maybe { outline: 2px dashed var(--a-accent); outline-offset: 4px; }
.chip[disabled], .colour[disabled], .answer[disabled] { cursor: default; }
.away .chip[disabled], .away .colour[disabled] { opacity: 1; }   /* read-only away, not broken */
.note { margin: calc(12 * var(--u) + 4px) 0 0; color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); max-width: 52ch; }
.moves { display: flex; flex-wrap: wrap; align-items: center; gap: calc(10 * var(--u) + 4px); margin-top: calc(14 * var(--u) + 4px); }
.moves .a-btn { flex: none; font-size: calc(16 * var(--u) + 4px); padding: calc(9 * var(--u) + 3px) calc(18 * var(--u) + 6px); min-height: 44px; }
.moves .hint { color: var(--a-ink-3); font-size: calc(11 * var(--u) + 4px); }

.toast {
  position: fixed; left: 50%; transform: translateX(-50%); bottom: calc(76 * var(--u) + 20px); z-index: 40;
  display: flex; align-items: center; gap: 14px;
  background: var(--a-ink); color: var(--a-bg); border-radius: 99px;
  padding: 8px 8px 8px 20px; font-size: calc(13 * var(--u) + 4px); box-shadow: var(--a-card-shadow);
}
.undo { appearance: none; border: 0; font: inherit; font-weight: 700; cursor: pointer; color: var(--a-bg); background: color-mix(in srgb, var(--a-bg) 18%, transparent); border-radius: 99px; padding: 8px 16px; min-height: 40px; }
.toast-enter-active, .toast-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translate(-50%, 8px); }

/* Phones: the spool on top, centred, then what it is */
@media (max-width: 599px) {
  .spool, .spool.asking { grid-template-columns: 1fr; gap: 14px; }
  .art-wrap { padding-top: 4px; }
  .art { width: 150px; }
  .spool.asking .art { width: 110px; }
  .name { align-items: center; text-align: center; }
  .name b { font-size: 30px; }
  .name .meta { font-size: 15px; }
  .colours { grid-template-columns: repeat(8, 32px); justify-content: space-between; gap: 12px 0; }
  .colour { width: 32px; }
  .chip { min-height: 40px; font-size: 16px; padding: 0 15px; }
  .note { font-size: 14px; }
  .toast { bottom: 100px; }
}
</style>
