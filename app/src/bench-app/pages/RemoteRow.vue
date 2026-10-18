<template>
  <!-- The box's own public name (design/bench-remote/, A): whether the bench can be reached from away, said plainly,
       with Turn on (an invite code from Elyir the first time) and Turn off, which ends every connection from away. -->
  <div v-if="r" class="card" :class="{ off: !row!.on }">
    <span class="t"><b>{{ row!.title }}</b><span>{{ why || row!.line }}</span>
      <label v-if="asking" class="inv"><span>Invite code</span>
        <input v-model="invite" class="a-num" spellcheck="false" autocapitalize="characters" placeholder="From Elyir, the first time" /></label>
      <span v-if="err" class="err">{{ err }}</span></span>
    <span class="acts">
      <button v-if="asking" class="a-btn ghost" @click="asking = false">Not now</button>
      <button class="a-btn" :class="row!.on ? 'ghost' : 'accent'" :disabled="busy" @click="press">
        {{ busy ? (row!.on ? 'Turning off…' : 'Turning on…') : confirming ? 'Turn off?' : row!.button }}</button>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { remoteRow, type BoxRemote } from '../away'
import { getRemote, turnRemote } from '../here'

const r = ref<BoxRemote | null>(null)
const row = computed(() => (r.value ? remoteRow(r.value) : null))
const asking = ref(false)
const invite = ref('')
const busy = ref(false)
const confirming = ref(false)
const err = ref('')
const why = ref('')

async function refresh() { r.value = await getRemote() }
defineExpose({ refresh })

async function press() {
  if (!row.value) return
  if (row.value.on && !confirming.value) { confirming.value = true; return }
  if (!row.value.on && row.value.needsCode && !asking.value) { asking.value = true; return }
  busy.value = true
  err.value = ''
  const res = await turnRemote(!row.value.on, invite.value.trim() || undefined)
  busy.value = false
  confirming.value = false
  if (res.error) { err.value = res.error; return }
  asking.value = false
  invite.value = ''
  why.value = res.why ? `On, but not reachable yet: ${res.why}.` : ''
  await refresh()
}

let timer = 0
onMounted(() => { refresh(); timer = window.setInterval(refresh, 10000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.card { display: flex; align-items: center; gap: 24px; padding: 18px 22px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); }
.t { flex: 1; display: grid; gap: 4px; min-width: 0; }
.t b { font-size: 21px; } .t > span { color: var(--a-ink-3); font-size: 17px; }
.inv { display: flex; align-items: center; gap: 12px; margin-top: 6px; font-size: 15px; font-weight: 650; color: var(--a-ink-2); }
.inv input { font: inherit; font-size: 18px; color: var(--a-ink); background: var(--a-bg); border: 1.5px solid var(--a-line); border-radius: 12px; padding: 9px 12px; width: 260px; outline: none; }
.inv input:focus { border-color: var(--a-accent); }
.t .err { color: var(--a-red-text); font-size: 15px; }
.acts { display: flex; gap: 10px; flex: none; }
.acts .a-btn { height: 52px; padding: 0 24px; border-radius: 999px; font-size: 18px; white-space: nowrap; }
@media (max-width: 599px) {
  .card { flex-wrap: wrap; gap: 10px; padding: 12px 14px; } .t b { font-size: 16px; } .t > span { font-size: 13px; }
  .inv input { width: 100%; } .acts .a-btn { height: 40px; font-size: 14px; padding: 0 14px; }
}
</style>
