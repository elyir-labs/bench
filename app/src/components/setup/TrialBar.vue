<template>
  <!-- The screen trial, on the printer's own screen (design/getting-started/, c-panel-try): it switched over and asks
       here, going back to KlipperScreen by itself if nobody answers. -->
  <div class="trial" role="alertdialog" :aria-label="TRIAL_ASK">
    <b class="ask">{{ TRIAL_ASK }}</b>
    <span class="when a-num" aria-live="off">{{ trialWords(left) }}</span>
    <button class="back" :disabled="pending !== null" @click="answer('screen_back')">{{ pending === 'screen_back' ? '…' : 'Back to KlipperScreen' }}</button>
    <button class="keep" :disabled="pending !== null" @click="answer('screen_keep')">{{ pending === 'screen_keep' ? '…' : 'Keep' }}</button>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { TRIAL_ASK, secondsLeft, trialWords } from '@/intent/setup'

// seconds_left as the printer last said it; the bar counts on from there by itself
const props = defineProps<{ secondsLeft: number }>()
const store = useIntentStore()

let said = { left: props.secondsLeft, at: Date.now() }
const left = ref(props.secondsLeft)
watch(() => props.secondsLeft, (s) => {
  said = { left: s, at: Date.now() }
  left.value = s
})
let timer = 0
onMounted(() => { timer = window.setInterval(() => { left.value = secondsLeft(said.left, said.at, Date.now()) }, 250) })
onBeforeUnmount(() => window.clearInterval(timer))

const pending = ref<string | null>(null)
async function answer(action: 'screen_back' | 'screen_keep') {
  pending.value = action
  await store.act(action)
  pending.value = null
}
</script>

<style scoped>
/* the panel at its design size: 68 px tall, in the accent, above the printer's name */
.trial {
  height: calc(68 * var(--u));
  background: var(--a-accent); color: var(--a-accent-ink);
  display: flex; align-items: center; gap: calc(14 * var(--u));
  padding: 0 calc(14 * var(--u)) 0 calc(28 * var(--u));
  white-space: nowrap;
}
.ask { flex: 1; min-width: 0; font-size: calc(20 * var(--u)); font-weight: 650; overflow: hidden; text-overflow: ellipsis; }
.when { font-size: calc(16 * var(--u)); opacity: .75; }
button {
  appearance: none; border: 0; font: inherit; cursor: pointer;
  height: calc(46 * var(--u)); border-radius: 999px; font-size: calc(17 * var(--u)); font-weight: 650;
}
.back { padding: 0 calc(20 * var(--u)); background: rgba(6, 17, 31, .16); color: var(--a-accent-ink); }
.keep { padding: 0 calc(26 * var(--u)); background: #06111f; color: #fff; }
button[disabled] { opacity: .6; cursor: default; }
button:active { transform: scale(.98); }
</style>
