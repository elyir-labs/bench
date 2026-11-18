<template>
  <!-- Setting a spot, one step at a time (design/spots/, B): only the arrows that matter, and a real test before
       it's saved. Advanced shows the numbers instead (C). -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open && (guide || numbersRow)" class="scrim">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="guide ? guide.name : 'Spot numbers'">
          <template v-if="guide">
            <header class="head">
              <div class="dots" aria-hidden="true"><i v-for="i in guide.of" :key="i" :class="{ on: i <= guide.n }"></i></div>
              <span class="grow"></span>
              <button class="a-btn ghost small" @click="cancel">Cancel</button>
            </header>
            <div class="body">
              <div class="words">
                <p class="where">{{ guide.name }} · {{ guide.n }} of {{ guide.of }}</p>
                <h2 class="a-display">{{ guide.asked ? guide.asked.title : guide.title }}</h2>
                <p class="detail">{{ guide.asked ? guide.asked.detail : guide.trying ? 'Cutting… it heats first if it needs to.' : guide.detail }}</p>
                <p v-if="guide.axis" class="pos a-num"><b>X {{ guide.position.x.toFixed(1) }}</b><b v-if="hasY">Y {{ guide.position.y.toFixed(1) }}</b><span v-if="guide.pressed != null">pressed {{ guide.pressed.toFixed(1) }} mm</span></p>
                <div v-if="guide.axis" class="seg" role="radiogroup" aria-label="Step">
                  <button
                    v-for="s in guide.steps" :key="s" class="seg-opt" role="radio"
                    :aria-checked="step === s" :class="{ on: step === s }" @click="step = s"
                  >{{ s }} mm</button>
                </div>
                <p v-if="guide.error || spots?.error" class="note err">{{ guide.error || spots?.error }}</p>
                <div class="acts">
                  <template v-if="guide.asked">
                    <button class="a-btn ghost" :disabled="busy" @click="send('spot_answer', { clean: false })">{{ guide.asked.no }}</button>
                    <button class="a-btn accent" :disabled="busy" @click="send('spot_answer', { clean: true })">{{ guide.asked.yes }}</button>
                  </template>
                  <template v-else>
                    <button v-if="guide.n > 1 && !guide.trying" class="a-btn ghost" :disabled="busy" @click="send('spot_back')">Back</button>
                    <button class="a-btn accent" :disabled="busy || guide.trying" @click="send(guide.test ? 'spot_try' : 'spot_next')">{{ guide.trying ? 'Cutting…' : guide.done }}</button>
                  </template>
                </div>
              </div>
              <div class="side">
                <NowCamera v-if="camera" :camera="camera" class="cam" />
                <div v-if="guide.axis" class="pad" :class="{ four: hasY }" role="group" aria-label="Move the head">
                  <button v-if="hasY" class="up" aria-label="Toward the back" :disabled="busy" @click="nudge('y', 1)"><svg viewBox="0 0 24 24"><path d="M5 15l7-7 7 7" /></svg></button>
                  <button class="left" aria-label="Left" :disabled="busy" @click="nudge('x', -1)"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" /></svg></button>
                  <span class="mid">{{ hasY ? 'Move the head' : 'Left · Right' }}</span>
                  <button class="right" aria-label="Right" :disabled="busy" @click="nudge('x', 1)"><svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" /></svg></button>
                  <button v-if="hasY" class="down" aria-label="Toward the front" :disabled="busy" @click="nudge('y', -1)"><svg viewBox="0 0 24 24"><path d="M5 9l7 7 7-7" /></svg></button>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="numbersRow">
            <header class="head">
              <div class="title"><h2 class="a-display">{{ numbersRow.name }}</h2><p class="sub">Numbers you measured. Go there checks them by eye.</p></div>
              <button class="a-btn ghost small" @click="emit('close')">Done</button>
            </header>
            <div class="fields">
              <label v-for="v in numbersRow.values" :key="v.id" class="field">
                <small>{{ v.label }}</small>
                <input v-model="typed[v.id]" inputmode="decimal" class="a-num" :aria-label="v.label" />
              </label>
            </div>
            <p v-if="spots?.error" class="note err">{{ spots.error }}</p>
            <div class="acts">
              <button class="a-btn ghost" :disabled="busy" @click="send('spot_go', { kind: numbersRow.kind })">Go there</button>
              <button class="a-btn accent" :disabled="busy" @click="saveNumbers">Save</button>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { useCameras } from '@/camera/useCameras'
import NowCamera from '@/components/now/NowCamera.vue'

const props = defineProps<{ open: boolean; numbers?: string | null }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const { cameras } = useCameras()
const camera = computed(() => cameras.value[0] ?? null)

const spots = computed(() => store.intent?.spots ?? null)
const guide = computed(() => spots.value?.guide ?? null)
const numbersRow = computed(() => (props.numbers ? spots.value?.rows.find((r) => r.kind === props.numbers) ?? null : null))
const busy = computed(() => store.busyAction !== null)
const hasY = computed(() => (guide.value?.axis ?? '').includes('y'))
const step = ref(1)
const typed = reactive<Record<string, string>>({})

watch(() => guide.value?.step, () => {
  const steps = guide.value?.steps ?? []
  if (steps.length && !steps.includes(step.value)) step.value = steps[0]
}, { immediate: true })
watch(numbersRow, (r) => {
  for (const v of r?.values ?? []) typed[v.id] = v.value == null ? '' : String(v.value)
}, { immediate: true })
// the guide ended (saved, or cancelled elsewhere): the sheet goes with it
watch(guide, (g, was) => { if (!g && was && !props.numbers) emit('close') })

function send(id: string, args: Record<string, unknown> = {}) {
  void store.act(id, args)
}
function nudge(axis: 'x' | 'y', dir: number) {
  send('spot_move', { axis, mm: dir * step.value })
}
function cancel() {
  send('spot_cancel')
  emit('close')
}
function saveNumbers() {
  if (!numbersRow.value) return
  send('spot_set', { kind: numbersRow.value.kind, values: { ...typed } })
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(10 * var(--u) + 4px); }
.sheet { background: var(--a-bg); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 820px; width: 100%; max-height: 100%; overflow: auto; padding: calc(14 * var(--u) + 6px) calc(16 * var(--u) + 6px); }
.head { display: flex; align-items: center; gap: calc(8 * var(--u) + 2px); }
.title { flex: 1; min-width: 0; }
.grow { flex: 1; }
h2 { font-size: calc(22 * var(--u) + 8px); line-height: 1.1; margin: 4px 0 0; }
.sub, .where { color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); margin: 2px 0 0; }
.a-btn.small { flex: none; min-height: 44px; padding: 0 calc(12 * var(--u) + 6px); font-size: calc(12 * var(--u) + 4px); }
.dots { display: flex; gap: 6px; }
.dots i { width: 28px; height: 5px; border-radius: 3px; background: var(--a-surface-2); }
.dots i.on { background: var(--a-accent); }
.body { display: grid; grid-template-columns: 1.1fr 1fr; gap: calc(14 * var(--u) + 6px); margin-top: calc(6 * var(--u) + 4px); }
.detail { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 4px); margin: 8px 0 0; line-height: 1.35; }
.pos { margin: 12px 0 0; display: flex; align-items: baseline; gap: 16px; color: var(--a-ink-2); font-size: calc(12 * var(--u) + 5px); }
.pos b { color: var(--a-ink); font-size: calc(20 * var(--u) + 8px); }
.seg { display: inline-flex; background: var(--a-surface-2); border-radius: 99px; padding: 4px; margin-top: 10px; }
.seg-opt { appearance: none; border: 0; background: none; font: inherit; font-weight: 600; font-size: calc(11 * var(--u) + 4px); color: var(--a-ink-3); padding: 0 calc(10 * var(--u) + 4px); min-height: 38px; border-radius: 99px; white-space: nowrap; cursor: pointer; }
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: 0 1px 3px rgba(16, 24, 40, 0.15); }
.acts { display: flex; gap: 10px; margin-top: calc(12 * var(--u) + 6px); }
.acts .a-btn { flex: 1; min-height: 52px; }
.note { margin: 10px 2px 0; color: var(--a-ink-2); font-size: calc(12 * var(--u) + 4px); }
.note.err { color: var(--a-red-text); }
.side { display: grid; gap: 8px; align-content: start; }
.cam { border-radius: calc(12 * var(--u) + 4px); overflow: hidden; aspect-ratio: 16 / 9; }
.pad { display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: center; }
.pad button { appearance: none; border: 0; cursor: pointer; border-radius: calc(12 * var(--u) + 6px); background: var(--a-surface); color: var(--a-ink); min-height: calc(50 * var(--u) + 24px); display: grid; place-items: center; }
.pad button:active { transform: scale(0.96); background: var(--a-surface-2); }
.pad svg { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.pad .mid { font-size: calc(10 * var(--u) + 4px); color: var(--a-ink-3); text-align: center; }
.pad.four { grid-template-columns: 1fr 1fr 1fr; grid-template-areas: ". up ." "left mid right" ". down ."; }
.pad.four button { min-height: calc(26 * var(--u) + 18px); }
.pad.four .up { grid-area: up; } .pad.four .down { grid-area: down; }
.pad.four .left { grid-area: left; } .pad.four .right { grid-area: right; } .pad.four .mid { grid-area: mid; }
.fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px; }
.field { background: var(--a-surface); border-radius: 14px; padding: 10px 14px; display: grid; gap: 2px; }
.field small { color: var(--a-ink-3); font-size: calc(10 * var(--u) + 4px); }
.field input { appearance: none; border: 0; background: none; color: var(--a-ink); font: inherit; font-size: calc(18 * var(--u) + 6px); font-weight: 700; width: 100%; padding: 0; }
.field input:focus { outline: none; }
.field:focus-within { outline: 2px solid var(--a-accent); }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 22px 22px 0 0; padding: 14px 16px 24px; }
  .body, .fields { grid-template-columns: 1fr; }
}
</style>
