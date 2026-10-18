<template>
  <!-- Move and heat (design/hands-on/, C): the jobs first, Move it myself opens the controls -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open && hands" class="scrim" @click.self="close">
        <div class="sheet" :class="'view-' + view" role="dialog" aria-modal="true" aria-label="Move and heat">
          <template v-if="view === 'jobs'">
            <header class="head">
              <div class="title">
                <h2 class="a-display">Move and heat</h2>
                <p class="sub">{{ sheetLine(name, nozzle.temperature, bed.temperature) }}</p>
              </div>
              <button class="a-btn ghost small" @click="close">Done</button>
            </header>
            <div class="jobs">
              <button
                v-for="j in jobList" :key="j.id" class="job" :class="{ more: j.id === 'move' }"
                :disabled="store.busyAction !== null && j.id !== 'move'" @click="pick(j)"
              >
                <span class="ic" v-html="JOB_ICON[j.id]"></span>
                <span class="t"><b>{{ j.action && store.busyAction === j.action ? '…' : j.title }}</b><span>{{ j.line }}</span></span>
              </button>
            </div>
            <p v-if="note" class="note">{{ note }}</p>
          </template>

          <template v-else>
            <header class="head">
              <button class="backlink" @click="view = 'jobs'"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" /></svg>Move and heat</button>
              <span class="grow"></span>
              <button class="a-btn ghost small" @click="send('hands_motors_off')"><span class="i" v-html="JOB_ICON.motors"></span>Motors off</button>
              <button class="a-btn ghost small" @click="close">Done</button>
            </header>
            <div class="controls">
              <div class="move">
                <div class="padz">
                  <div class="pad">
                    <span></span>
                    <button aria-label="Toward the back" @click="move('y', 1)"><svg viewBox="0 0 24 24"><path :d="ARROW.up" /></svg></button>
                    <span></span>
                    <button aria-label="Left" @click="move('x', -1)"><svg viewBox="0 0 24 24"><path :d="ARROW.left" /></svg></button>
                    <button class="home" aria-label="Find home" @click="send('hands_home')"><svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7M6 9.5V20h12V9.5" /></svg></button>
                    <button aria-label="Right" @click="move('x', 1)"><svg viewBox="0 0 24 24"><path :d="ARROW.right" /></svg></button>
                    <span></span>
                    <button aria-label="Toward the front" @click="move('y', -1)"><svg viewBox="0 0 24 24"><path :d="ARROW.down" /></svg></button>
                    <span></span>
                  </div>
                  <div class="zcol">
                    <button v-for="z in zButtons(hands.z_moves)" :key="z.label" @click="move('z', z.dir)">
                      <svg viewBox="0 0 24 24"><path :d="ARROW[z.arrow]" /></svg>{{ z.label }}
                    </button>
                  </div>
                </div>
                <div class="under">
                  <div class="seg" role="radiogroup" aria-label="Step">
                    <button
                      v-for="s in hands.steps" :key="s" class="seg-opt" role="radio"
                      :aria-checked="step === s" :class="{ on: step === s }" @click="step = s"
                    >{{ s }} mm</button>
                  </div>
                  <span class="where a-num">{{ whereLine(hands) }}</span>
                </div>
              </div>
              <div class="heats">
                <div v-for="h in heaters" :key="h.key" class="heat">
                  <div class="h">
                    <b>{{ h.label }}</b>
                    <span class="v a-num">{{ Math.round(h.now.temperature) }}°<small v-if="h.now.target"> of {{ Math.round(h.now.target) }}°</small></span>
                  </div>
                  <span class="bar"><i :style="{ width: pct(h.now) }"></i></span>
                  <div class="chips">
                    <button
                      v-for="p in h.presets" :key="p.material" class="chip" :class="{ on: h.now.target === p.temp }"
                      @click="heat(h.key, p.temp, p.material)"
                    >{{ p.material }} <small>{{ p.temp }}°</small></button>
                    <button class="chip" :class="{ on: !h.now.target }" @click="heat(h.key, 0)">Off</button>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <p v-if="store.actionError" class="note err">{{ store.actionError }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
  <WarmSheet :open="warmOpen" @close="warmOpen = false" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useIntentStore } from '@/intent/store'
import { jobs, sheetLine, whereLine, zButtons, type Job } from '@/intent/hands'
import WarmSheet from '@/components/warm/WarmSheet.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const router = useRouter()

const hands = computed(() => store.intent?.hands ?? null)
const name = computed(() => store.intent?.printer.name ?? 'The printer')
const nozzle = computed(() => store.intent?.printer.nozzle ?? { temperature: 0, target: 0 })
const bed = computed(() => store.intent?.printer.bed ?? { temperature: 0, target: 0 })
const jobList = computed(() => (hands.value ? jobs(hands.value) : []))
const heaters = computed(() => [
  { key: 'nozzle' as const, label: 'Nozzle', now: nozzle.value, presets: hands.value?.nozzle_presets ?? [] },
  { key: 'bed' as const, label: 'Bed', now: bed.value, presets: hands.value?.bed_presets ?? [] },
])

const view = ref<'jobs' | 'move'>('jobs')
const step = ref(10)
const note = ref<string | null>(null)
const warmOpen = ref(false)

watch(() => props.open, (o) => { if (o) { view.value = 'jobs'; note.value = null } })
// a print started, or the printer went away: nothing here can be used now
watch(() => hands.value?.why_not, (why) => { if (why && props.open) close() })

const ARROW = { up: 'M12 19V5M6 11l6-6 6 6', down: 'M12 5v14M6 13l6 6 6-6', left: 'M19 12H5M11 6l-6 6 6 6', right: 'M5 12h14M13 6l6 6-6 6' }
const JOB_ICON: Record<Job['id'], string> = {
  clear: '<svg viewBox="0 0 24 24"><path d="M3 18h18M12 14V4M8 8l4-4 4 4"/></svg>',
  clean: '<svg viewBox="0 0 24 24"><path d="M4 20l7-7M10 9l5 5M14 4l6 6-5 5-6-6z"/></svg>',
  nozzle: '<svg viewBox="0 0 24 24"><path d="M6 3h12v7l-3 4H9l-3-4z"/><path d="M10 14v3l2 4 2-4v-3"/></svg>',
  bed: '<svg viewBox="0 0 24 24"><path d="M3 16h18M5 16v3M19 16v3"/><path d="M8 12c0-2 2-2 2-4M12 12c0-2 2-2 2-4M16 12c0-2 2-2 2-4"/></svg>',
  motors: '<svg viewBox="0 0 24 24"><path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12M11 11V4.5a1.5 1.5 0 0 1 3 0V12M14 11V6a1.5 1.5 0 0 1 3 0v8a7 7 0 0 1-7 7h-.5A5.5 5.5 0 0 1 5 17.5L3.5 14a1.5 1.5 0 0 1 2.6-1.4L8 15"/></svg>',
  move: '<svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/></svg>',
}

function close() {
  emit('close')
}

const pct = (h: { temperature: number; target: number }) => (h.target ? `${Math.min(100, Math.round((h.temperature / h.target) * 100))}%` : '0%')

async function send(action: string, args?: Record<string, unknown>) {
  note.value = null
  await store.act(action, args)
  return !store.actionError
}

async function pick(j: Job) {
  if (j.id === 'move') {
    view.value = 'move'
    return
  }
  if (!j.action) {   // Heat the bed with nothing in the head: which material?
    warmOpen.value = true
    return
  }
  if (!(await send(j.action, j.args))) return
  if (j.id === 'motors') {
    note.value = 'Motors off. Push the head by hand; it finds home again before it next moves.'
    return
  }
  close()
  router.push('/')   // Now says what it's holding and how to finish
}

function move(axis: 'x' | 'y' | 'z', dir: number) {
  void send('hands_move', { axis, mm: dir * step.value })
}

function heat(heater: 'nozzle' | 'bed', target: number, material?: string) {
  void send('hands_heat', { heater, target, material })
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(10 * var(--u) + 4px); }
.sheet { background: var(--a-bg); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 820px; width: 100%; max-height: 100%; overflow: auto; padding: calc(14 * var(--u) + 6px) calc(16 * var(--u) + 6px); }
.head { display: flex; align-items: center; gap: calc(8 * var(--u) + 2px); }
.title { flex: 1; min-width: 0; }
.grow { flex: 1; }
h2 { font-size: calc(22 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); margin: 2px 0 0; }
.a-btn.small { flex: none; min-height: 44px; padding: 0 calc(12 * var(--u) + 6px); font-size: calc(12 * var(--u) + 4px); display: inline-flex; align-items: center; gap: 6px; }
.a-btn .i :deep(svg) { width: 20px; height: 20px; display: block; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.note { margin: calc(10 * var(--u) + 2px) 2px 0; color: var(--a-ink-2); font-size: calc(12 * var(--u) + 4px); }
.note.err { color: var(--a-red-text); }

.jobs { display: grid; grid-template-columns: repeat(3, 1fr); gap: calc(8 * var(--u) + 4px); margin-top: calc(12 * var(--u) + 4px); }
.job {
  appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer;
  display: grid; grid-template-columns: auto 1fr; align-items: center; gap: calc(8 * var(--u) + 4px);
  min-height: calc(80 * var(--u) + 30px); padding: calc(10 * var(--u) + 4px) calc(12 * var(--u) + 4px);
  border-radius: calc(14 * var(--u) + 6px); border: 0; background: var(--a-surface);
}
.job:active { transform: scale(0.98); }
.job[disabled] { opacity: 0.6; }
.job.more { background: none; border: 1.5px dashed var(--a-line); }
.ic { width: calc(28 * var(--u) + 16px); height: calc(28 * var(--u) + 16px); border-radius: calc(8 * var(--u) + 6px); background: var(--a-surface-2); display: grid; place-items: center; }
.ic :deep(svg) { width: 60%; height: 60%; fill: none; stroke: var(--a-ink-2); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.job.more .ic { background: var(--a-accent); }
.job.more .ic :deep(svg) { stroke: var(--a-accent-ink); }
.t { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.t b { font-size: calc(14 * var(--u) + 5px); font-weight: 600; line-height: 1.15; }
.t span { font-size: calc(10 * var(--u) + 4.5px); color: var(--a-ink-3); line-height: 1.3; }

.backlink { appearance: none; border: 0; background: none; font: inherit; font-weight: 600; font-size: calc(13 * var(--u) + 5px); color: var(--a-accent-text); display: inline-flex; align-items: center; gap: 4px; cursor: pointer; padding: 8px 4px; }
.backlink svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.controls { display: grid; grid-template-columns: 1fr 1fr; gap: calc(14 * var(--u) + 6px); margin-top: calc(10 * var(--u) + 4px); }
.padz { display: grid; grid-template-columns: 2fr 1fr; gap: calc(8 * var(--u) + 4px); height: calc(170 * var(--u) + 60px); }
.pad { display: grid; grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(3, 1fr); gap: 8px; }
.pad button, .zcol button {
  appearance: none; font: inherit; cursor: pointer; border: 0; border-radius: calc(12 * var(--u) + 6px);
  background: var(--a-surface); color: var(--a-ink); display: grid; place-items: center; align-content: center; gap: 2px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
}
.pad button:active, .zcol button:active { transform: scale(0.96); background: var(--a-surface-2); }
.pad button.home { background: var(--a-surface-2); }
.pad svg, .zcol svg { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.zcol { display: grid; gap: 8px; }
.zcol button { font-size: calc(10 * var(--u) + 4px); font-weight: 600; color: var(--a-ink-2); }
.under { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: calc(8 * var(--u) + 4px); flex-wrap: wrap; }
.seg { display: inline-flex; background: var(--a-surface-2); border-radius: 99px; padding: 4px; }
.seg-opt { appearance: none; border: 0; background: none; font: inherit; font-weight: 600; font-size: calc(11 * var(--u) + 4px); color: var(--a-ink-3); padding: 0 calc(10 * var(--u) + 4px); min-height: 38px; border-radius: 99px; white-space: nowrap; cursor: pointer; }
.seg-opt.on { background: var(--a-surface); color: var(--a-ink); box-shadow: 0 1px 3px rgba(16, 24, 40, 0.15); }
.where { font-size: calc(10 * var(--u) + 4px); color: var(--a-ink-3); white-space: nowrap; }
.heats { display: grid; gap: calc(8 * var(--u) + 4px); align-content: start; }
.heat { background: var(--a-surface); border-radius: calc(14 * var(--u) + 6px); padding: calc(10 * var(--u) + 4px) calc(12 * var(--u) + 6px); }
.heat .h { display: flex; align-items: baseline; gap: 10px; }
.heat .h b { font-size: calc(13 * var(--u) + 5px); font-weight: 600; }
.heat .v { margin-left: auto; font-size: calc(20 * var(--u) + 10px); font-weight: 700; letter-spacing: -0.02em; }
.heat .v small { font-size: calc(11 * var(--u) + 5px); font-weight: 500; color: var(--a-ink-3); letter-spacing: 0; }
.bar { display: block; height: 6px; border-radius: 3px; background: var(--a-surface-2); margin: 8px 0 calc(8 * var(--u) + 4px); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--temp-warm, #e8743b); border-radius: 3px; transition: width 0.6s ease; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { appearance: none; font: inherit; cursor: pointer; min-height: 40px; padding: 0 calc(6 * var(--u) + 4px); border-radius: 99px; border: 1.5px solid var(--a-line); background: none; display: inline-flex; align-items: center; gap: 5px; font-size: calc(10 * var(--u) + 4.5px); font-weight: 600; color: var(--a-ink-2); white-space: nowrap; }
.chip small { font-weight: 500; color: var(--a-ink-3); font-size: 0.9em; }
.chip.on { background: var(--temp-warm, #e8743b); border-color: var(--temp-warm, #e8743b); color: #fff; }
.chip.on small { color: rgba(255, 255, 255, 0.85); }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 22px 22px 0 0; padding: 14px 16px 24px; }
  .jobs { grid-template-columns: 1fr; gap: 10px; }
  .job { min-height: 0; }
  .controls { grid-template-columns: 1fr; }
  .padz { height: 226px; }
}
</style>
