<template>
  <!-- Who can reach this printer, and who is asking to. The "wants to connect" notification opens here.
       Answering only at home or on the panel; away this page says so instead. -->
  <section class="phones-page">
    <h1 class="a-display title">Phones</h1>

    <template v-if="canAnswer()">
      <h2 class="label" v-if="waiting.length">Waiting</h2>
      <div v-for="a in waiting" :key="a.id" class="ask">
        <div class="who">
          <span class="dot" aria-hidden="true"></span>
          <span class="words">
            <span class="name">{{ a.name }}</span>
            <span class="meta a-num">{{ kindWords(a.kind) }} · wants to connect · {{ leftOf(a) }} left</span>
          </span>
        </div>
        <div class="actions">
          <button class="a-btn accent" :disabled="busy === a.id" @click="reply(a.id, true)">Allow</button>
          <button class="a-btn ghost" :disabled="busy === a.id" @click="reply(a.id, false)">Not now</button>
        </div>
      </div>
    </template>
    <p v-else class="note">New devices are allowed at home or on the printer's screen.</p>

    <h2 class="label">Paired</h2>
    <ul v-if="phones && phones.length" class="list">
      <li v-for="p in phones" :key="p.id">
        <span class="words">
          <span class="name">{{ p.name }}</span>
          <span class="meta">{{ p.notifications ? 'Notifications on' : 'Notifications off' }}</span>
        </span>
        <button v-if="canAnswer()" class="a-btn ghost small" :disabled="busy === p.id" @click="remove(p.id)">{{ confirming === p.id ? 'Remove?' : 'Remove' }}</button>
      </li>
    </ul>
    <p v-else-if="phones" class="note">No phones yet.</p>
    <p v-else class="note">The list of phones is shown at home and on the printer's screen.</p>
    <p v-if="error" class="err">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { answer, asks, canAnswer, kindWords, type Ask } from '@/asks'
import { listPhones, removePhone, type DoorPhone } from '@/door'

const phones = ref<DoorPhone[] | null>(null)
const busy = ref<string | null>(null)
const confirming = ref<string | null>(null)
const error = ref<string | null>(null)
const now = ref(Date.now() / 1000)

const waiting = computed(() => asks.list.filter((a) => a.expires > now.value && a.kind !== 'backup'))
const leftOf = (a: Ask) => {
  const s = Math.max(0, Math.round(a.expires - now.value))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

async function refresh() {
  phones.value = canAnswer() ? await listPhones() : null
}

async function reply(id: string, allow: boolean) {
  busy.value = id
  error.value = null
  try {
    await answer(id, allow)
    if (allow) await refresh()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = null
  }
}

async function remove(id: string) {
  if (confirming.value !== id) { confirming.value = id; return }   // a second tap confirms
  busy.value = id
  try {
    await removePhone(id)
    await refresh()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = null
    confirming.value = null
  }
}

// asks being answered elsewhere (the panel, another phone) can change who is paired
watch(() => asks.list.length, refresh)
let timer = 0
onMounted(() => { refresh(); timer = window.setInterval(() => { now.value = Date.now() / 1000 }, 1000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.phones-page { flex: 1; padding: calc(8 * var(--u) + 4px) calc(28 * var(--u) + 8px) calc(16 * var(--u) + 6px); overflow: auto; }
.title { font-size: calc(30 * var(--u) + 8px); margin: 0 0 calc(10 * var(--u) + 4px); }
.label { margin: calc(12 * var(--u) + 4px) 0 calc(6 * var(--u) + 2px); font-size: calc(11 * var(--u) + 4px); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--a-ink-3); }
.ask {
  background: var(--a-surface); border-radius: calc(16 * var(--u) + 6px); box-shadow: var(--a-card-shadow);
  padding: calc(12 * var(--u) + 4px) calc(14 * var(--u) + 5px); display: flex; flex-direction: column; gap: calc(10 * var(--u) + 2px);
  margin-bottom: calc(10 * var(--u) + 2px);
}
.who { display: flex; align-items: center; gap: 12px; }
.dot { width: 12px; height: 12px; border-radius: 50%; background: var(--a-amber); flex: none; }
.words { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.name { font-weight: 700; font-size: calc(16 * var(--u) + 5px); color: var(--a-ink); overflow-wrap: anywhere; }
.meta { color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); }
.actions { display: flex; gap: calc(10 * var(--u) + 2px); }
.actions .a-btn { flex: 1 1 0; }
.list { list-style: none; margin: 0; padding: 0; background: var(--a-surface); border-radius: calc(16 * var(--u) + 6px); }
.list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0; padding: calc(12 * var(--u) + 4px) calc(14 * var(--u) + 5px); border-top: 1px solid var(--a-line); color: var(--a-ink); }
.list li:first-child { border-top: 0; }
.small { flex: none; padding: 8px 14px; min-height: 40px; font-size: calc(13 * var(--u) + 4px); }
.note { color: var(--a-ink-2); font-size: calc(14 * var(--u) + 5px); line-height: 1.45; margin: 0 0 8px; }
.err { color: var(--a-red-text); font-size: 15px; }
</style>
