<template>
  <!-- First layer (design/first-layer/, "At the end"; design/first-layer-sheets/, C): what the kept value is for -->
  <div class="keep" role="group" :aria-label="card.headline">
    <b>{{ card.headline }}</b>
    <span>{{ card.detail }}</span>
    <div v-if="actions.length" class="row2" :class="{ three: actions.length > 2 }">
      <button
        v-for="a in actions"
        :key="a.id"
        class="a-btn"
        :class="a.primary ? 'accent' : 'ghost'"
        :disabled="store.busyAction !== null"
        @click="press(a)"
      >{{ store.busyAction === a.id ? '…' : a.label }}</button>
    </div>
    <span v-else class="at-printer">Answer this at the printer.</span>
  </div>
  <Teleport to="body">
    <div v-if="naming" class="scrim" @click.self="naming = false">
      <div class="pick" role="dialog" aria-label="Which sheet is on the bed?">
        <b>Which sheet is on the bed?</b>
        <span>It keeps this first layer. Every other print stays as it was.</span>
        <div class="chips">
          <button v-for="n in card.sheets ?? []" :key="n" class="chip" :class="{ on: n === picked && !typing }" @click="picked = n; typing = false">{{ n }}</button>
          <button class="chip" :class="{ on: typing }" @click="typing = true; picked = ''">Another…</button>
        </div>
        <input v-if="typing" v-model="typed" class="name" maxlength="24" placeholder="Its name, like Glass" aria-label="The sheet's name" />
        <div class="row2">
          <button class="a-btn accent" :disabled="!name || store.busyAction !== null" @click="keepFor()">{{ store.busyAction === 'keep_for_sheet' ? '…' : 'Keep it' }}</button>
          <button class="a-btn ghost" @click="naming = false">Back</button>
        </div>
        <span v-if="badName" class="at-printer">Letters, numbers and spaces, up to 24.</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentAction } from '@/intent/types'
import { allowedHere } from '@/door'

const props = defineProps<{ card: { headline: string; detail: string; actions: IntentAction[]; sheets?: string[] } }>()
const store = useIntentStore()
const actions = computed(() => props.card.actions.filter((a) => allowedHere(a.id)))
const naming = ref(false)
const picked = ref('')
const typing = ref(false)
const typed = ref('')
const name = computed(() => (typing.value ? typed.value.trim() : picked.value))
const badName = computed(() => typing.value && !!typed.value.trim() && !/^[A-Za-z0-9][A-Za-z0-9 .+-]{0,23}$/.test(typed.value.trim()))

function press(a: IntentAction) {
  if (a.id === 'keep_for_sheet') {
    naming.value = true
    return
  }
  store.act(a)
}

function keepFor() {
  if (!name.value || badName.value) return
  store.act('keep_for_sheet', { name: name.value })
}
</script>

<style scoped>
.keep { background: var(--a-surface); border-radius: calc(14 * var(--u) + 6px); padding: calc(12 * var(--u) + 4px) calc(14 * var(--u) + 4px); box-shadow: var(--a-card-shadow); display: grid; gap: 4px; margin-top: calc(16 * var(--u) + 6px); max-width: 460px; text-align: left; }
.keep b { font-size: calc(15 * var(--u) + 5px); line-height: 1.25; }
.keep span { font-size: calc(11 * var(--u) + 4px); color: var(--a-ink-2); line-height: 1.35; }
.row2 { display: flex; gap: 10px; margin-top: 10px; }
.row2 .a-btn { flex: 1; min-height: calc(38 * var(--u) + 12px); font-size: calc(13 * var(--u) + 4px); border-radius: 15px; padding: 0 12px; }
.row2.three { display: grid; grid-template-columns: 1.1fr 1fr 1fr; gap: 8px; }
.row2.three .a-btn { padding: 4px 8px; line-height: 1.15; white-space: normal; font-size: calc(12 * var(--u) + 4px); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.chip { min-height: calc(30 * var(--u) + 10px); padding: 0 16px; border-radius: 999px; border: 1.5px solid var(--a-line); background: none; color: var(--a-ink); font: inherit; font-size: calc(12 * var(--u) + 4px); font-weight: 600; }
.chip.on { border-color: var(--a-accent); color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 10%, transparent); }
.name { margin-top: 8px; min-height: calc(32 * var(--u) + 10px); border-radius: 12px; border: 1.5px solid var(--a-line); background: var(--a-bg); color: var(--a-ink); font: inherit; font-size: calc(12 * var(--u) + 4px); padding: 0 12px; }
.at-printer { color: var(--a-ink-3) !important; margin-top: 6px; }
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(16 * var(--u) + 6px); }
.pick { background: var(--a-surface); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 560px; width: 100%; max-height: 100%; overflow: auto; padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px); display: grid; gap: 4px; text-align: left; }
.pick b { font-size: calc(17 * var(--u) + 6px); line-height: 1.2; }
.pick span { font-size: calc(11 * var(--u) + 4px); color: var(--a-ink-2); line-height: 1.35; }
</style>
