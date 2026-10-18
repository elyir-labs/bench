<template>
  <!-- A queued print, set up for its printer, waiting for its bed (design/bench-queue/, Queue A): the same bed question as
       Print on, from the queue's row or the printer's tile. Nothing starts until someone says the bed is clear. -->
  <div class="scrim" @click.self="emit('close')">
    <div class="sheet" role="dialog" aria-modal="true" :aria-label="`Is ${item.printer_name}'s bed clear?`">
      <h2 class="a-display">{{ refused ? refused.headline || `${item.printer_name} says no.` : `Is ${item.printer_name}'s bed clear?` }}</h2>
      <template v-if="refused && refused.ask">
        <p v-if="refused.detail" class="muted">{{ refused.detail }}</p>
        <div class="acts"><button class="a-btn accent grow" :disabled="busy" @click="start(false, true)">{{ busy ? 'Starting…' : 'Yes, print' }}</button>
          <router-link :to="`/p/${item.printer}/materials`" class="a-btn ghost" @click="emit('close')">No, it's something else</router-link></div>
      </template>
      <template v-else-if="refused">
        <p class="muted">{{ refused.detail }}</p>
        <div class="acts"><button class="a-btn amber grow" :disabled="busy" @click="start(true)">Print anyway</button><button class="a-btn ghost" @click="emit('close')">Not now</button></div>
      </template>
      <template v-else>
        <BenchCamera v-if="item.printer" :printer="item.printer" :name="item.printer_name ?? ''" />
        <p class="muted">Take a look at {{ item.printer_name }}: nothing left on the bed, and nothing in the way.</p>
        <p class="status" :class="{ bad: error }">{{ error || `Set up for ${item.printer_name} · ${queueTitle(item)}${item.time ? ` · ${humanDuration(item.time)}` : ''}` }}</p>
        <div class="acts">
          <button class="a-btn accent grow" :disabled="busy || !!error" @click="start(false)">{{ busy ? 'Starting…' : "It's clear, print" }}</button>
          <button class="a-btn ghost" @click="emit('close')">Not yet</button>
        </div>
        <p class="muted small">Not yet: it stays first for {{ item.printer_name }}.</p>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { humanDuration } from '@/intent/jobs'
import { queueTitle, type QueueItem } from '../shelf'
import { startQueued } from '../shelf-api'
import { loadQueue } from '../live'
import BenchCamera from './BenchCamera.vue'

const props = defineProps<{ item: QueueItem }>()
const emit = defineEmits<{ close: [] }>()
const router = useRouter()
const busy = ref(false)
const error = ref('')
const refused = ref<{ headline?: string; detail?: string; ask?: boolean } | null>(null)

// confirm: the printer asked what's on its one spool, and someone said it's what the file uses
async function start(anyway: boolean, confirm = false) {
  busy.value = true
  try {
    const r = await startQueued(props.item.id, anyway, confirm)
    if (r.refused) { refused.value = r.refused; return }
    await loadQueue()
    emit('close')
    await router.push(`/p/${r.printer}`)
  } catch (e) {
    error.value = (e as Error).message
    refused.value = null
    void loadQueue()
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; background: rgba(16, 20, 28, .42); display: grid; place-items: center; z-index: 20; padding: 16px; }
.sheet { width: min(640px, 100%); box-sizing: border-box; background: var(--a-surface); border-radius: 24px; padding: 28px 30px; display: grid; gap: 14px; box-shadow: var(--a-card-shadow); }
.sheet h2 { margin: 0; font-size: 34px; letter-spacing: -.02em; }
.sheet p { margin: 0; font-size: 18px; }
.muted { color: var(--a-ink-3); }
.status { font-weight: 650; color: var(--a-green-text); }
.status.bad { color: var(--a-red-text); }
.acts { display: flex; gap: 14px; flex-wrap: wrap; }
.a-btn { height: 62px; font-size: 21px; padding: 0 28px; }
.grow { flex: 1; }
.small { font-size: 15px !important; }
@media (max-width: 599px) { .sheet { padding: 20px; } .sheet h2 { font-size: 24px; } .sheet p { font-size: 15px; } .a-btn { height: 52px; font-size: 17px; } }
</style>
