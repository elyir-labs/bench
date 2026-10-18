<template>
  <!-- Finish setting up (design/getting-started/, C "Ready first"): one card under Ready on a phone, a row at a
       time, gone once each row is done or closed. The panel never shows it (docs/setup-card.md). -->
  <div class="setup-slot" :class="{ empty: !(shown && info) }">
    <div v-if="shown && info" class="setup-card" role="region" aria-label="Finish setting up">
      <div class="head">
        <b>Finish setting up</b>
        <span class="left">{{ leftWords(left) }}</span>
        <button class="x" aria-label="Close Finish setting up" :disabled="pending !== null" @click="dismissAll" v-html="CLOSE"></button>
      </div>
      <component
        :is="r.opens ? 'button' : 'div'" v-for="r in rows" :key="r.id" class="task"
        :class="{ done: r.done, amber: r.amber, opens: !!r.opens, solo: !r.button && !r.opens }"
        @click="r.opens && (sheet = 'works')"
      >
        <span class="ic" aria-hidden="true" v-html="ROW_ICONS[r.icon]"></span>
        <span class="words">
          <b>{{ r.title }}</b>
          <small v-if="r.line">{{ r.line }}</small>
          <span v-if="r.progress" class="bar" aria-hidden="true"><i></i></span>
        </span>
        <button
          v-if="r.button" class="btn" :class="{ accent: r.button.primary }"
          :disabled="pending !== null || pushBusy" @click.stop="press(r.button.press)"
        >{{ busyFor(r.button.press) ? '…' : r.button.label }}</button>
        <span v-else-if="r.opens" class="chev" aria-hidden="true" v-html="CHEVRON"></span>
      </component>
      <form v-if="renaming" class="foot rename" @submit.prevent="rename">
        <input ref="nameIn" v-model="draft" class="name-in" maxlength="40" aria-label="The printer's name" autocomplete="off" />
        <button type="button" class="link" @click="renaming = false">Cancel</button>
        <button type="submit" class="link" :disabled="!draft.trim() || pending !== null">Save</button>
      </form>
      <div v-else class="foot">{{ nameLine(info.name, info.name_from) }} · <button class="link" @click="startRename">Change</button></div>
      <p v-if="error" class="err">{{ error }}</p>
    </div>
    <WorksSheet
      v-if="info" :open="sheet === 'works'" :info="info" :busy="pending !== null" :error="sheetError"
      @close="sheet = null" @include="sheet = 'include'"
    />
    <IncludeSheet
      v-if="info" :open="sheet === 'include'" :info="info" :busy="pending !== null" :error="sheetError"
      @back="sheet = 'works'" @close="sheet = null" @add="include(true)" @remove="include(false)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { enablePush, pushStatus, type PushStatus } from '@/push'
import { newPairCode } from '@/door'
import { cardRows, cardShown, leftCount, leftWords, nameLine, settling, type RowPress, type SetupInfo } from '@/intent/setup'
import { CHEVRON, CLOSE, ROW_ICONS } from './icons'
import WorksSheet from './WorksSheet.vue'
import IncludeSheet from './IncludeSheet.vue'

// ready: Now is on Ready. The card sits under it then; its sheets stay open through a Klipper restart.
const props = defineProps<{ ready: boolean }>()
const store = useIntentStore()
const intent = computed(() => store.intent)
const open = computed(() => !!intent.value?.setup?.open)

const info = ref<SetupInfo | null>(null)
const push = ref<PushStatus | null>(null)
const pushBusy = ref(false)
const pending = ref<string | null>(null)
const error = ref<string | null>(null)
const sheetError = ref<string | null>(null)
const sheet = ref<'works' | 'include' | null>(null)

const rows = computed(() => cardRows(info.value, push.value))
const left = computed(() => leftCount(rows.value))
const shown = computed(() => props.ready && cardShown(open.value, rows.value))

/** Everything the card and its sheets need, asked when the card shows and after each action. */
async function load() {
  if (!store.connected) return
  try {
    info.value = await store.call<SetupInfo>('printer.intent.setup')
  } catch {
    // a printer whose intent layer predates the card: nothing to show
  }
}

// The intent says when to ask again: the card opening, a trial starting or ending, the name changing.
watch(() => [open.value, !!intent.value?.printer.screen_trial, intent.value?.printer.name, store.connected].join('|'), () => {
  if (open.value || sheet.value) load()
}, { immediate: true })

// Fetching the screen's parts, a trial, the include going in: the printer moves on by itself, so ask every few seconds.
let poll = 0
onMounted(async () => {
  poll = window.setInterval(() => { if (settling(info.value) && (open.value || sheet.value)) load() }, 2000)
  push.value = await pushStatus()
})
onBeforeUnmount(() => window.clearInterval(poll))

// Once the line is in (or out), back to What works, where the features have moved.
watch(() => info.value?.works.include, (now, before) => {
  if (sheet.value === 'include' && ((before === 'adding' && now === 'on') || (before === 'removing' && now === 'off'))) sheet.value = 'works'
})
watch(sheet, () => { sheetError.value = null })

async function send(action: string, args?: Record<string, unknown>): Promise<boolean> {
  pending.value = action
  await store.act(action, args)
  const failed = store.actionError
  await load()
  pending.value = null
  return !failed
}

function busyFor(p: RowPress): boolean {
  if (p === 'push_on' || p === 'pair_here') return pushBusy.value
  return pending.value === (p === 'screen_ok' ? 'setup_dismiss' : p)
}

async function press(p: RowPress) {
  error.value = null
  if (p === 'pair_here') {
    // a pairing code for this phone, then the secure link with it: there it's paired, and notifications work
    pushBusy.value = true
    try {
      const code = await newPairCode()
      window.location.href = code.shell_url ?? code.url
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Couldn't set this phone up. Try again in a moment."
      pushBusy.value = false
    }
    return
  }
  if (p === 'push_on') {
    // straight from the tap: iOS only asks for permission inside a user gesture
    pushBusy.value = true
    try {
      push.value = await enablePush()
    } catch {
      error.value = "Couldn't turn them on. Try again in a moment."
    } finally {
      pushBusy.value = false
    }
    return
  }
  const ok = p === 'screen_try' ? await send('screen_try') : await send('setup_dismiss', { row: 'screen' })
  if (!ok) error.value = store.actionError
}

/** ×: every row still on the card is closed; the card goes for good. */
async function dismissAll() {
  error.value = null
  for (const r of rows.value) {
    if (!(await send('setup_dismiss', { row: r.id }))) {
      error.value = store.actionError
      return
    }
  }
}

const renaming = ref(false)
const draft = ref('')
const nameIn = ref<HTMLInputElement | null>(null)
async function startRename() {
  draft.value = info.value?.name ?? ''
  renaming.value = true
  await nextTick()
  nameIn.value?.select()
}
async function rename() {
  error.value = null
  if (await send('setup_name', { name: draft.value.trim() })) renaming.value = false
  else error.value = store.actionError
}

async function include(on: boolean) {
  sheetError.value = null
  if (!(await send(on ? 'include_add' : 'include_remove'))) sheetError.value = store.actionError
}
</script>

<style scoped>
/* one root, so Now can place it; nothing there while the card isn't (its sheets live in <body>) */
.setup-slot.empty { display: none; }
/* Sizes from the boards, in px: the phone's arrangement has a fixed scale (layout.ts, compact) */
.setup-card { background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); overflow: hidden; text-align: left; }
.head { display: flex; align-items: center; gap: 10px; padding: 14px 16px 12px; }
.head b { font-size: 17px; font-weight: 650; color: var(--a-ink); }
.head .left { font-size: 14px; color: var(--a-ink-3); }
.x {
  appearance: none; border: 0; background: none; color: var(--a-ink-3); cursor: pointer;
  margin: -10px -10px -10px auto; width: 40px; height: 40px; display: grid; place-items: center; border-radius: 50%;
}
.x :deep(svg) { display: block; }

.task {
  appearance: none; border: 0; border-top: 1px solid var(--a-line); background: none; font: inherit; color: inherit; text-align: left;
  width: 100%; display: grid; grid-template-columns: 38px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 13px 16px;
}
.task.solo { grid-template-columns: 38px minmax(0, 1fr); }
.task.opens { cursor: pointer; }
.task.opens:active { background: color-mix(in srgb, var(--a-ink) 4%, transparent); }
.ic { width: 38px; height: 38px; border-radius: 12px; background: var(--a-tint-blue); color: var(--a-accent-text); display: grid; place-items: center; }
.ic :deep(svg) { display: block; }
.done .ic { background: var(--a-tint-green); color: var(--a-green-text); }
.amber .ic { background: var(--a-tint-amber); color: var(--a-amber-text); }
.words { min-width: 0; display: block; }
.words b { display: block; font-size: 16px; font-weight: 650; color: var(--a-ink); line-height: 1.3; }
.done .words b { color: var(--a-ink-2); }
.words small { display: block; font-size: 14px; color: var(--a-ink-3); line-height: 1.35; }
/* fetching: apt gives no percentage, so the bar moves without saying how far */
.bar { display: block; height: 6px; border-radius: 3px; background: var(--a-track, color-mix(in srgb, var(--a-ink) 10%, transparent)); margin-top: 10px; overflow: hidden; position: relative; }
.bar i { position: absolute; top: 0; bottom: 0; width: 40%; border-radius: 3px; background: var(--a-accent); animation: setup-fetch 1.6s ease-in-out infinite; }
@keyframes setup-fetch { from { left: -40%; } to { left: 100%; } }

.btn {
  appearance: none; font: inherit; cursor: pointer; white-space: nowrap;
  height: 36px; padding: 0 16px; border-radius: 999px; font-size: 15px; font-weight: 650;
  background: var(--a-ghost-bg); border: 1px solid var(--a-line); color: var(--a-ink-2);
}
.btn.accent { background: var(--a-accent); border-color: transparent; color: var(--a-accent-ink); }
.btn[disabled] { opacity: .6; cursor: default; }
.chev { color: var(--a-ink); opacity: .4; display: grid; }

.foot { padding: 11px 16px 13px; border-top: 1px solid var(--a-line); font-size: 14px; color: var(--a-ink-3); }
.link { appearance: none; border: 0; background: none; padding: 0; font: inherit; font-weight: 650; color: var(--a-accent-text); cursor: pointer; }
.link[disabled] { opacity: .5; cursor: default; }
.rename { display: flex; align-items: center; gap: 14px; padding-block: 8px; }
.name-in {
  flex: 1; min-width: 0; font: inherit; font-size: 16px; color: var(--a-ink); user-select: text; -webkit-user-select: text;
  background: var(--a-surface-2); border: 0; border-radius: 10px; padding: 8px 12px;
}
.err { margin: 0; padding: 0 16px 13px; font-size: 14px; color: var(--a-red-text); }
</style>
