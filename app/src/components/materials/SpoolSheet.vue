<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="spool" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="`Slot ${spool.slot + 1}`">
          <div class="top">
            <span class="swatch big" :class="{ empty: !shown }" :style="{ '--c': shown || 'transparent' }"></span>
            <div class="title">
              <h2 class="a-display">{{ title }}</h2>
              <p class="sub" v-if="editing">Tell the printer what's in this slot. This doesn't load anything.</p>
              <p class="sub" v-else-if="moving">{{ `Slot ${spool.slot + 1} isn't in the head, so it's free to move.` }}</p>
              <p class="sub" v-else-if="spool.status === 'empty'">{{ unitName || `Slot ${spool.slot + 1}` }}</p>
              <p class="sub a-num" v-else>
                Slot {{ spool.slot + 1 }}<template v-if="spool.in_use"> · in the head</template><template v-if="spool.grams"> · about {{ spool.grams }} g left</template><template v-if="spool.rfid"> · from its tag</template>
              </p>
            </div>
          </div>

          <!-- Move filament (design/slots/, B): a nudge in or out, for a tip that didn't catch or a tangle -->
          <template v-if="moving">
            <div class="nudge">
              <button class="nudge-btn" :disabled="!!store.busyAction" @click="nudge(step)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M6 13l6 6 6-6" /></svg>
                <b>{{ store.busyAction === 'move_filament' && lastDir > 0 ? '…' : 'Push in' }}</b><span>toward the head</span>
              </button>
              <button class="nudge-btn" :disabled="!!store.busyAction" @click="nudge(-step)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6" /></svg>
                <b>{{ store.busyAction === 'move_filament' && lastDir < 0 ? '…' : 'Pull back' }}</b><span>toward the spool</span>
              </button>
            </div>
            <div class="links">
              <span class="per">Each tap moves</span>
              <div class="mats" role="radiogroup" aria-label="How far">
                <button v-for="mm in [10, 50, 200]" :key="mm" class="chip" :class="{ on: step === mm }" role="radio" :aria-checked="step === mm" @click="step = mm">{{ mm / 10 }} cm</button>
              </div>
              <span class="spacer"></span>
              <button class="a-btn ghost done" @click="moving = false">Done</button>
            </div>
          </template>

          <!-- What this spool can do: load / switch / unload / swap, with one line on what happens -->
          <template v-else-if="!editing">
            <p v-if="spool.status === 'empty' && spool.note" class="lead">{{ spool.note }}</p>
            <div v-if="spool.actions?.length" class="move">
              <div class="btns" :class="{ two: spool.actions.length > 1 }">
                <button
                  v-for="a in spool.actions"
                  :key="a.id"
                  class="a-btn"
                  :class="a.primary ? 'accent' : 'ghost'"
                  :disabled="!!store.busyAction"
                  @click="run(a)"
                >{{ store.busyAction === a.id ? '…' : a.label }}</button>
              </div>
              <p v-if="spool.note" class="note">{{ spool.note }}</p>
            </div>
            <p v-else-if="store.busy && spool.status !== 'empty'" class="note">Spools can be changed once the printer is free.</p>
            <p v-if="spool.spare_note" class="note quiet">{{ spool.spare_note }}</p>
            <!-- Feed assist, for the slot in the head: the unit pushes along while it prints -->
            <div v-if="spool.in_use && spool.assist != null" class="assist">
              <span class="w"><b>Help push while printing</b><span>The unit pushes the filament along, so the head doesn't pull it all the way from the spool.</span></span>
              <Toggle :model-value="spool.assist" label="Help push while printing" :disabled="!!store.busyAction"
                      @update:model-value="(v: boolean) => store.act('feed_assist', { slot: spool!.slot, on: v })" />
            </div>
            <div class="links">
              <button v-if="spool.move" class="link" @click="moving = true">Move filament</button>
              <button v-if="spool.fix" class="link" :disabled="!!store.busyAction" @click="run(spool.fix)">{{ spool.fix.label }}</button>
              <button v-if="!spool.rfid" class="link" @click="editing = true">{{ spool.move || spool.fix ? 'Edit' : 'Edit color & material' }}</button>
              <span class="spacer"></span>
              <button class="a-btn ghost done" @click="$emit('close')">Done</button>
            </div>
          </template>

          <template v-else-if="!spool.rfid">
            <div class="label">Color</div>
            <div class="colors" role="radiogroup" aria-label="Color">
              <button
                v-for="c in COLORS"
                :key="c.hex"
                class="swatch pick"
                :class="{ on: same(c.hex, color) }"
                :style="{ '--c': c.hex }"
                :aria-label="c.name"
                role="radio"
                :aria-checked="same(c.hex, color)"
                @click="color = c.hex"
              ></button>
            </div>
            <div class="label">Material</div>
            <div class="mats" role="radiogroup" aria-label="Material">
              <button
                v-for="m in MATERIALS"
                :key="m"
                class="chip"
                :class="{ on: material === m }"
                role="radio"
                :aria-checked="material === m"
                @click="material = m"
              >{{ m }}</button>
            </div>
            <div class="actions">
              <button class="a-btn ghost" @click="editing = false">Back</button>
              <button class="a-btn accent" :disabled="!color || !material || saving" @click="save">{{ saving ? '…' : 'Save' }}</button>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import type { IntentAction, IntentSpool } from '@/intent/types'
import { COLORS, MATERIALS } from './palette'
import Toggle from './Toggle.vue'

const props = defineProps<{ spool: IntentSpool | null; unitName?: string | null; startEditing?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const router = useRouter()
const editing = ref(false)


const color = ref<string | null>(null)
const material = ref<string | null>(null)
const saving = ref(false)

const moving = ref(false)
const step = ref(50)
const lastDir = ref(0)

// Fresh sheet: start on the main view (or straight on "what is it", from "New spool in slot 7")
watch(() => [props.spool?.slot, props.startEditing], () => { editing.value = !!props.startEditing; moving.value = false })

// An empty slot keeps the colour it was set to, but nothing is in it: draw it empty unless editing
const shown = computed(() => (!editing.value && props.spool?.status === 'empty' ? null : color.value))

const title = computed(() => {
  const s = props.spool
  if (!s) return ''
  if (editing.value) return `Slot ${s.slot + 1}`
  if (moving.value) return `Move ${s.name || `slot ${s.slot + 1}`}`
  if (s.status === 'empty') return `Slot ${s.slot + 1} is empty`
  return s.name || `Slot ${s.slot + 1}`
})

/** Load / switch / unload / swap go to Now to watch it happen; a correction just closes. */
async function run(a: IntentAction) {
  await store.act(a)
  if (store.actionError) return
  emit('close')
  if (a.id === 'load_spool' || a.id === 'unload_spool' || a.id === 'swap_start') router.push('/')
}

async function nudge(mm: number) {
  if (!props.spool) return
  lastDir.value = mm
  await store.act('move_filament', { slot: props.spool.slot, mm })
}

watch(() => props.spool, (s) => {
  color.value = s?.color ?? null
  material.value = s?.material && MATERIALS.includes(s.material) ? s.material : null
}, { immediate: true })

function same(a: string | null, b: string | null): boolean {
  return !!a && !!b && a.toUpperCase() === b.toUpperCase()
}

async function save() {
  if (!props.spool || !color.value || !material.value) return
  saving.value = true
  try {
    await store.setSpool(props.spool.slot, color.value, material.value)
    if (!store.actionError) editing.value = false
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 50;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: calc(14 * var(--u) + 6px);
}
.sheet {
  background: var(--a-surface);
  border-radius: calc(22 * var(--u) + 8px);
  box-shadow: var(--a-card-shadow);
  max-width: 720px; width: 100%;
  max-height: 100%; overflow: auto;
  padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px);
}
.top { display: flex; align-items: center; gap: calc(14 * var(--u) + 4px); margin-bottom: calc(6 * var(--u) + 2px); }
.title h2 { font-size: calc(22 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 5px); margin: 2px 0 0; }
.label { font-size: calc(11 * var(--u) + 4px); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-ink-3); margin: calc(8 * var(--u) + 2px) 0 calc(5 * var(--u) + 2px); }
.swatch {
  border-radius: 50%; background: var(--c); border: 3px solid var(--a-swatch-edge); box-sizing: border-box; flex: none;
}
.swatch.big { width: calc(40 * var(--u) + 12px); height: calc(40 * var(--u) + 12px); }
.swatch.big.empty { border-style: dashed; border-color: var(--a-swatch-empty); }
.colors { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 3px); }
.swatch.pick {
  appearance: none; padding: 0; cursor: pointer;
  width: calc(34 * var(--u) + 10px); height: calc(34 * var(--u) + 10px); min-width: 40px; min-height: 40px;
}
.swatch.pick.on { outline: 3px solid var(--a-accent); outline-offset: 3px; }
.mats { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 4px); }
.chip {
  appearance: none; font: inherit; font-weight: 700; cursor: pointer;
  font-size: calc(15 * var(--u) + 4px); letter-spacing: 0.03em;
  padding: calc(7 * var(--u) + 3px) calc(14 * var(--u) + 5px); min-height: 42px;
  border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2);
}
.chip.on { background: var(--a-accent); border-color: var(--a-accent); color: var(--a-accent-ink); }
.actions { display: flex; gap: calc(10 * var(--u) + 4px); margin-top: calc(14 * var(--u) + 4px); align-items: center; }
.actions .a-btn { padding: calc(10 * var(--u) + 4px) calc(16 * var(--u) + 6px); font-size: calc(18 * var(--u) + 4px); }
.move { display: flex; flex-direction: column; gap: calc(6 * var(--u) + 2px); margin-top: calc(10 * var(--u) + 4px); }
.move .a-btn { flex: none; padding: calc(12 * var(--u) + 4px) calc(18 * var(--u) + 6px); font-size: calc(19 * var(--u) + 4px); }
.btns { display: grid; gap: calc(10 * var(--u) + 2px); }
.btns.two { grid-template-columns: 1fr 1fr; }
.lead { font-size: calc(17 * var(--u) + 4px); line-height: 1.35; margin: calc(8 * var(--u) + 2px) 0 0; }
.note.quiet { color: var(--a-ink-3); margin-top: calc(6 * var(--u) + 2px); }
.assist { display: flex; align-items: center; gap: calc(12 * var(--u) + 4px); margin-top: calc(12 * var(--u) + 4px);
          padding-top: calc(10 * var(--u) + 4px); border-top: 1px solid var(--a-line); }
.assist .w { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.assist b { font-size: calc(15 * var(--u) + 3px); font-weight: 600; }
.assist .w span { font-size: calc(12 * var(--u) + 3px); color: var(--a-ink-3); }
.nudge { display: grid; grid-template-columns: 1fr 1fr; gap: calc(10 * var(--u) + 2px); margin-top: calc(10 * var(--u) + 4px); }
.nudge-btn {
  appearance: none; border: 0; font: inherit; color: var(--a-ink); cursor: pointer;
  display: grid; justify-items: center; gap: 2px; padding: calc(12 * var(--u) + 2px) 10px;
  border-radius: calc(16 * var(--u) + 4px); background: var(--a-surface-2);
}
.nudge-btn svg { width: 28px; height: 28px; fill: none; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.nudge-btn b { font-size: calc(17 * var(--u) + 4px); }
.nudge-btn span { font-size: calc(11 * var(--u) + 3px); color: var(--a-ink-3); }
.nudge-btn:active { transform: scale(0.98); }
.nudge-btn[disabled] { opacity: 0.6; }
.per { font-size: calc(13 * var(--u) + 3px); color: var(--a-ink-3); }
.note { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 5px); margin: 0; }
.links { display: flex; align-items: center; flex-wrap: wrap; gap: calc(14 * var(--u) + 4px); margin-top: calc(14 * var(--u) + 4px); }
.link {
  appearance: none; border: 0; background: none; padding: 6px 0; cursor: pointer; font: inherit;
  font-size: calc(13 * var(--u) + 5px); color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px;
}
.link[disabled] { opacity: 0.5; }
.spacer { flex: 1; }
.links .a-btn.done { flex: none; padding: calc(8 * var(--u) + 3px) calc(18 * var(--u) + 6px); font-size: calc(16 * var(--u) + 4px); min-height: 40px; }
.actions .a-btn { flex: 0 1 220px; }
.actions .a-btn.accent { flex: 1 1 260px; }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1); }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(24px) scale(0.98); }

@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 22px 22px 0 0; }
}
</style>
