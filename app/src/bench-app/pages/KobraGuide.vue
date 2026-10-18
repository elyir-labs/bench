<template>
  <!-- Bringing a Kobra onto the bench (design/kobra-lan/, B): the LAN mode switch on its own screen, drawn, while the box
       watches for it; once it's on, the box adds it by itself and says what works. -->
  <div class="scrim" @click.self="emit('close')">
    <div class="sheet" role="dialog" aria-modal="true" :aria-label="`Bring ${row.name} onto the bench`">
      <p class="step">{{ row.name.toUpperCase() }} · {{ done ? 2 : 1 }} OF 2</p>
      <template v-if="!done">
        <h2 class="a-display">Turn on LAN mode on {{ row.name }}'s screen.</h2>
        <div class="two">
          <div class="kobra" aria-hidden="true">
            <div class="bar"><span>‹</span><b>Network</b></div>
            <div class="list">
              <div class="item muted"><span>Wi-Fi</span><span>Home</span></div>
              <div class="item on"><span>LAN mode</span><i class="switch"><i></i></i></div>
              <div class="note">LAN mode turns off Anycubic's cloud on this printer</div>
            </div>
          </div>
          <div class="how">
            <span><b>Settings</b>, then <b>Network</b>, then <b>LAN mode</b> on.</span>
            <span class="muted">Anycubic's app stops reaching it. Its own screen works as before.</span>
            <span v-if="error" class="bad">{{ error }}</span>
            <span v-else class="watching"><i></i>{{ adding ? `Adding ${row.name}…` : 'Watching for it…' }}</span>
          </div>
        </div>
        <div class="acts"><button class="a-btn ghost" @click="emit('close')">Not now</button></div>
      </template>
      <template v-else>
        <h2 class="a-display">{{ row.name }} is on the bench.</h2>
        <div class="works">
          <div class="col">
            <div v-for="w in yes" :key="w" class="w ok"><b>✓</b><span>{{ w }}</span></div>
          </div>
          <div v-if="no.length" class="col">
            <div v-for="w in no" :key="w" class="w"><b>–</b><span>{{ w }}</span></div>
            <span class="muted small">Rinkhals adds those: a USB stick and ten minutes.</span>
          </div>
        </div>
        <div class="acts"><button class="a-btn accent" @click="emit('close')">Done</button></div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

export interface FoundKobra { id: string; name: string; on: boolean; why?: string | null; via?: 'lan' | 'moonraker' | null }

const props = defineProps<{ row: FoundKobra }>()
const emit = defineEmits<{ close: []; added: [] }>()
const adding = ref(false)
const error = ref<string | null>(null)
const addedVia = ref<FoundKobra['via']>(props.row.on ? props.row.via : null)
const done = computed(() => !!addedVia.value)

const yes = computed(() => ["What it's doing, and when it's done", 'Print a model from the box', 'Pause and stop',
  'Your phone, at home and away', ...(addedVia.value === 'moonraker' ? ['Typing G-code, and Mainsail on the printer'] : [])])
const no = computed(() => (addedVia.value === 'moonraker' ? [] : ['Typing G-code', 'Mainsail on the printer']))

// The box looks at the Wi-Fi every few seconds (SetupPage); once LAN mode is on, this Kobra can be added: add it.
async function add() {
  if (adding.value || done.value) return
  adding.value = true
  error.value = null
  try {
    const r = await fetch(`/bench/add/${encodeURIComponent(props.row.id)}`, { method: 'POST' })
    const body = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(body.error || `The box said ${r.status}.`)
    addedVia.value = props.row.via ?? 'lan'
    emit('added')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    adding.value = false
  }
}
watch(() => [props.row.why, props.row.on] as const, ([why, on]) => {
  if (on && !done.value) addedVia.value = props.row.via ?? 'lan'
  else if (!why && !on) void add()
}, { immediate: true })
</script>

<style scoped>
.scrim { position: fixed; inset: 0; background: rgba(16, 20, 28, .42); display: grid; place-items: center; z-index: 20; padding: 16px; }
.sheet { width: min(900px, 100%); box-sizing: border-box; background: var(--a-surface); border-radius: 28px; box-shadow: var(--a-card-shadow);
  padding: 34px 40px; display: grid; gap: 16px; }
.step { margin: 0; color: var(--a-ink-3); font-size: 16px; font-weight: 700; letter-spacing: .1em; }
h2 { margin: 0; font-size: 40px; line-height: 1.08; letter-spacing: -.02em; }
.two { display: grid; grid-template-columns: auto 1fr; gap: 30px; align-items: center; }
.how { display: grid; gap: 14px; font-size: 21px; }
.muted { color: var(--a-ink-3); font-size: 18px; }
.small { font-size: 16px; margin-top: 6px; }
.bad { color: var(--a-amber-text, #8f5200); font-weight: 650; }
.watching { display: flex; align-items: center; gap: 12px; color: var(--a-accent-text); font-weight: 650; }
.watching i { width: 14px; height: 14px; border-radius: 50%; border: 3px solid currentColor; border-right-color: transparent; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.acts { display: flex; justify-content: flex-end; gap: 12px; }
.acts .a-btn { flex: none; width: auto; height: 54px; font-size: 19px; padding: 0 30px; }
.works { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 40px; }
.col { display: grid; gap: 8px; align-content: start; }
.w { display: flex; gap: 12px; align-items: baseline; font-size: 20px; color: var(--a-ink-3); }
.w b { width: 22px; }
.w.ok { color: var(--a-ink); }
.w.ok b { color: var(--a-green-text); }
/* the Kobra's own screen, drawn: its network settings with LAN mode */
.kobra { width: 400px; aspect-ratio: 480 / 272; border-radius: 14px; background: #1b1e24; border: 7px solid #2b2f37; color: #e8ebf0;
  font-size: 18px; display: grid; grid-template-rows: auto 1fr; overflow: hidden; box-shadow: 0 8px 24px rgba(0, 0, 0, .25); }
.kobra .bar { display: flex; gap: 10px; padding: 10px 14px; background: #262a32; }
.kobra .bar span { opacity: .6; }
.kobra .list { padding: 10px 14px; display: grid; gap: 8px; align-content: start; }
.kobra .item { display: flex; justify-content: space-between; align-items: center; }
.kobra .item.muted { opacity: .7; color: inherit; font-size: inherit; }
.kobra .item.on { padding: 6px 8px; margin: 0 -8px; border-radius: 6px; box-shadow: 0 0 0 2px #f2a024; }
.kobra .switch { width: 44px; height: 22px; border-radius: 99px; background: #555b66; position: relative; }
.kobra .switch i { position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; border-radius: 50%; background: #fff; }
.kobra .note { opacity: .5; font-size: 14px; }
@media (max-width: 760px) {
  .sheet { padding: 20px; } h2 { font-size: 26px; } .two { grid-template-columns: 1fr; } .kobra { width: 100%; }
  .how { font-size: 17px; } .works { grid-template-columns: 1fr; } .w { font-size: 17px; }
}
</style>
