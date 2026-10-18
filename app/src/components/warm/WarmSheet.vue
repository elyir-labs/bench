<template>
  <!-- "What are you printing next?" (design/warm-up/, D: B's question) -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="scrim" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" aria-label="What are you printing next?">
          <h2 class="a-display">What are you printing next?</h2>
          <p class="sub">I'll warm the bed{{ anyChamber ? ' and chamber' : '' }} for it.</p>
          <div class="rows">
            <button v-for="o in options" :key="'m' + o.label" class="row" :disabled="!!store.busyAction" @click="go(o.args?.material as string)">
              <span class="sw" :style="{ '--c': (o.args?.color as string) || 'transparent' }"></span>
              <span class="t"><b>{{ o.label }}</b><span>{{ o.args?.note }}</span></span>
            </button>
            <button v-for="r in recent" :key="'r' + r.filename" class="row" :disabled="!!store.busyAction" @click="go(r.material)">
              <ObjectImage :src="store.thumbOf(r.job)" :alt="r.name" class="thumb" />
              <span class="t"><b>{{ r.name }}</b><span>{{ r.material }} · {{ r.when }}</span></span>
            </button>
          </div>
          <div v-if="!options.length && !recent.length" class="mats">
            <button v-for="m in MATERIALS" :key="m" class="chip" @click="go(m)">{{ m }}</button>
          </div>
          <div class="actions"><button class="a-btn ghost" @click="$emit('close')">Back</button></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { HistoryJob } from '@/intent/types'
import { prettyName } from '@/intent/jobs'
import { MATERIALS } from '@/components/materials/palette'
import ObjectImage from '@/components/now/ObjectImage.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()

const options = computed(() => store.intent?.warm?.options ?? [])
const anyChamber = computed(() => options.value.some(o => ['ABS', 'ASA', 'PA', 'PC'].includes(String(o.args?.material))))

// Recent prints know their own material: two of them, newest first, one per material
const recent = ref<{ filename: string; name: string; material: string; when: string; job: HistoryJob }[]>([])
watch(() => props.open, async (o) => {
  if (!o) return
  const jobs = await store.recentJobs(10)
  const seen = new Set<string>()
  recent.value = []
  for (const j of jobs) {
    const m = String(j.metadata?.filament_type ?? '').split(';')[0].trim().toUpperCase()
    if (!MATERIALS.includes(m) || seen.has(j.filename)) continue
    seen.add(j.filename)
    recent.value.push({ filename: j.filename, name: prettyName(j.filename), material: m, when: recent.value.length ? 'recent print' : 'last print', job: j })
    if (recent.value.length === 2) break
  }
})

async function go(material: string) {
  await store.act('warm_up', { material })
  if (!store.actionError) emit('close')
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(14 * var(--u) + 6px); }
.sheet { background: var(--a-surface); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 760px; width: 100%; max-height: 100%; overflow: auto; padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px); }
h2 { font-size: calc(24 * var(--u) + 6px); margin: 0; }
.sub { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 5px); margin: 4px 0 calc(10 * var(--u) + 4px); }
.rows { display: grid; grid-template-columns: 1fr 1fr; gap: calc(8 * var(--u) + 2px); }
.row {
  appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer;
  display: flex; align-items: center; gap: calc(10 * var(--u) + 4px); min-height: 56px;
  padding: calc(8 * var(--u) + 2px) calc(10 * var(--u) + 4px); border-radius: calc(12 * var(--u) + 4px);
  border: 1px solid var(--a-line); background: var(--a-ghost-bg);
}
.row:first-child { border-color: var(--a-accent); box-shadow: 0 0 0 1px var(--a-accent); }
.sw { width: calc(26 * var(--u) + 10px); height: calc(26 * var(--u) + 10px); border-radius: 50%; background: var(--c); border: 3px solid var(--a-swatch-edge); flex: none; box-sizing: border-box; }
.thumb { width: calc(30 * var(--u) + 10px); height: calc(30 * var(--u) + 10px); border-radius: 10px; flex: none; }
.t { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.t b { font-size: calc(15 * var(--u) + 4px); }
.t span { font-size: calc(11 * var(--u) + 4px); color: var(--a-ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mats { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { appearance: none; font: inherit; font-weight: 700; cursor: pointer; min-height: 42px; padding: 0 16px; border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-ghost-bg); color: var(--a-ink-2); }
.actions { display: flex; justify-content: flex-end; margin-top: calc(12 * var(--u) + 4px); }
.actions .a-btn { flex: none; padding: calc(8 * var(--u) + 3px) calc(18 * var(--u) + 6px); min-height: 40px; }
.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .scrim { align-items: flex-end; padding: 0; }
  .sheet { border-radius: 22px 22px 0 0; }
  .rows { grid-template-columns: 1fr; }
}
</style>
