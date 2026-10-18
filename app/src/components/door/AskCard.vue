<template>
  <!-- Someone on the Wi-Fi asks to connect. Interrupts any screen, except while the printer needs a
       person or has stopped (those come first), and except when the Add a phone sheet is open,
       which shows the ask itself. Only where answering is allowed: the panel, or a phone at home. -->
  <Teleport to="body">
    <Transition name="ask">
      <div v-if="ask" class="scrim" role="dialog" aria-modal="true" :aria-label="title">
        <div class="card">
          <div class="top">
            <div class="icon" aria-hidden="true">
              <svg v-if="ask.kind === 'printer'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3.5" y="3" width="17" height="18" rx="2"/><path d="M3.5 7.5h17M8 12.5h8M12 7.5v5"/><path d="M7 17.5h10" stroke-linecap="round"/></svg>
              <svg v-else-if="ask.kind === 'bench'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="7" width="18" height="11" rx="2.5"/><path d="M7 14.5h4"/><circle cx="17" cy="12.5" r="1.2" fill="currentColor"/></svg>
              <svg v-else-if="ask.kind === 'computer' || ask.kind === 'hub'" viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="12" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M1.5 19.5h21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
              <svg v-else viewBox="0 0 24 24"><rect x="6.5" y="2.5" width="11" height="19" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10.5 18.5h3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
            </div>
            <div class="words">
              <h2 class="a-display">{{ title }}</h2>
              <span v-if="ask.kind === 'backup'" class="sub a-num">{{ allowWhere(ask.name, ask.at, now * 1000) }}</span>
              <span v-else class="sub a-num">{{ kindWords(ask.kind) }} on this Wi-Fi<template v-if="ask.kind !== 'printer'"> · asks for {{ left }} more</template></span>
            </div>
          </div>
          <p class="what">{{ what }}</p>
          <p v-if="error" class="err">{{ error }}</p>
          <div class="actions">
            <button class="a-btn accent" :disabled="busy" @click="reply(true)">Allow</button>
            <button class="a-btn ghost" :disabled="busy" @click="reply(false)">Not now</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { answer, asks, canAnswerAsk, kindWords } from '@/asks'
import { allowTitle, allowWhat, allowWhere } from '@/cloud'
import { useIntentStore } from '@/intent/store'

const store = useIntentStore()
const now = ref(Date.now() / 1000)
const busy = ref(false)
const error = ref<string | null>(null)

const ask = computed(() => {
  if (asks.inline) return null
  const s = store.intent?.state
  if (s === 'needs_you' || s === 'problem') return null   // the printer first; the ask waits its turn
  return asks.list.find((a) => a.expires > now.value && canAnswerAsk(a)) ?? null
})

// What saying yes lets it do. A home hub only watches and can pause or stop (the away list); a
// phone or computer gets notifications, and at home everything the panel can do.
const title = computed(() => ask.value?.kind === 'backup' ? allowTitle(ask.value.name)
  : ask.value?.kind === 'printer' ? `${ask.value.name} wants to slice here` : `${ask.value?.name} wants to connect`)
const what = computed(() => {
  if (ask.value?.kind === 'backup') return allowWhat(ask.value.backup_at ?? null, now.value * 1000)
  const printer = store.intent?.printer?.name ?? 'the printer'
  // a printer that can't slice asks this one to (design/slicing-elsewhere/, A)
  if (ask.value?.kind === 'printer')
    return `Models sent to ${ask.value.name} would be sliced on ${printer}, with ${ask.value.name}'s own settings. ${printer}'s own prints always come first.`
  // a Bench Box (design/bench-box/, first run): everything this printer does, from its screen and phones at home
  if (ask.value?.kind === 'bench')
    return `It could see and run everything ${printer} does, from its own screen and from phones at home. ${printer} keeps working on its own if the box is off.`
  return ask.value?.kind === 'hub'
    ? `It will see what ${printer} is doing, and can pause or stop a print. It can't start one.`
    : "It could watch prints and get notifications from anywhere, and start prints when it's at home."
})

const left = computed(() => {
  if (!ask.value) return ''
  const s = Math.max(0, Math.round(ask.value.expires - now.value))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})

async function reply(allow: boolean) {
  if (!ask.value) return
  busy.value = true
  error.value = null
  try {
    await answer(ask.value.id, allow)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

let timer = 0
onMounted(() => { timer = window.setInterval(() => { now.value = Date.now() / 1000 }, 1000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.scrim {
  position: fixed; inset: 0; z-index: 60;
  background: rgba(8, 12, 20, 0.45);
  display: flex; align-items: center; justify-content: center;
  padding: calc(14 * var(--u) + 6px);
}
.card {
  width: min(600px, 100%);
  background: var(--a-surface); color: var(--a-ink);
  border-radius: calc(22 * var(--u) + 6px);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  padding: calc(20 * var(--u) + 6px) calc(22 * var(--u) + 6px);
  display: flex; flex-direction: column; gap: calc(10 * var(--u) + 4px);
}
.top { display: flex; align-items: center; gap: calc(14 * var(--u) + 4px); }
.icon {
  flex: none; width: calc(44 * var(--u) + 12px); height: calc(44 * var(--u) + 12px);
  border-radius: calc(12 * var(--u) + 4px); background: var(--a-surface-2); color: var(--a-ink);
  display: flex; align-items: center; justify-content: center;
}
.icon svg { width: 55%; height: 55%; }
.words { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
h2 { margin: 0; font-size: calc(22 * var(--u) + 6px); overflow-wrap: anywhere; }
.sub { color: var(--a-ink-3); font-size: calc(13 * var(--u) + 5px); }
.what { margin: 0; color: var(--a-ink-2); font-size: calc(14 * var(--u) + 5px); line-height: 1.4; }
.err { margin: 0; color: var(--a-red-text); font-size: 15px; }
.actions { display: flex; gap: calc(10 * var(--u) + 4px); }
.actions .a-btn { flex: 1 1 0; }
.ask-enter-active, .ask-leave-active { transition: opacity 160ms ease; }
.ask-enter-from, .ask-leave-to { opacity: 0; }
</style>
