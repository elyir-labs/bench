<template>
  <!-- "How does the first line look?" (design/first-layer/, B: the sheet on panel and phone) -->
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open && adjust" class="scrim" :class="{ phone: !panel }" @click.self="$emit('close')">
        <div class="sheet" role="dialog" aria-modal="true" :aria-label="SHEET_TITLE">
          <div v-if="!panel" class="grab" aria-hidden="true"></div>
          <div class="head">
            <h2 class="a-display">{{ SHEET_TITLE }}</h2>
            <button v-if="panel" class="a-btn ghost done-top" @click="$emit('close')">Done</button>
          </div>
          <p class="sub">{{ sheetSub(panel) }}</p>
          <CameraView v-if="camera" :camera="camera" watching class="cam" @failed="camFailed = true" />
          <div class="beads" :class="{ compact: !panel }">
            <div v-for="b in BEADS" :key="b.kind" class="bead">
              <svg :viewBox="BEAD_VIEWBOX" aria-hidden="true">
                <component :is="s.tag" v-for="(s, i) in beadShapes(b.kind)" :key="i" v-bind="s.attrs" />
              </svg>
              <b>{{ b.title }}</b>
              <span v-if="panel">{{ b.note }}</span>
            </div>
          </div>
          <div class="squish">
            <button class="sq" :disabled="!canPress(fl, 'squish_less', busy)" @click="press('squish_less')">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V6M6 12l6-6 6 6" /></svg>Further
            </button>
            <span class="val" aria-live="polite"><b>{{ adjust.words }}</b><span class="a-num">{{ adjust.mm }}</span></span>
            <button class="sq" :disabled="!canPress(fl, 'squish_more', busy)" @click="press('squish_more')">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v13M6 12l6 6 6-6" /></svg>Closer
            </button>
          </div>
          <p v-if="store.actionError" class="err">{{ store.actionError }}</p>
          <button v-if="!panel" class="a-btn accent done-bottom" @click="$emit('close')">Done</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import { BEADS, BEAD_VIEWBOX, SHEET_TITLE, beadShapes, canPress, sheetSub } from '@/intent/firstLayer'
import CameraView from '@/components/camera/CameraView.vue'
import { useCameras } from '@/camera/useCameras'
import { layout } from '@/shell/useLayout'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const store = useIntentStore()
const fl = computed(() => store.intent?.first_layer ?? null)
const adjust = computed(() => fl.value?.adjust ?? null)
const busy = computed(() => store.busyAction)
const panel = computed(() => layout.value === 'panel')

// Off the panel the camera sits on top: it's how you see the line from across the room.
const { cameras } = useCameras()
const camFailed = ref(false)
const camera = computed(() => (!panel.value && !camFailed.value ? cameras.value[0] ?? null : null))

// After layer 3 there's nothing left to adjust: the sheet goes with the button.
watch(adjust, (a) => { if (!a && props.open) emit('close') })

async function press(id: 'squish_less' | 'squish_more') {
  await store.act(id)
}
</script>

<style scoped>
.scrim { position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; padding: calc(16 * var(--u) + 6px); }
.sheet { background: var(--a-surface); border-radius: calc(22 * var(--u) + 8px); box-shadow: var(--a-card-shadow); max-width: 740px; width: 100%; max-height: 100%; overflow: auto; padding: calc(16 * var(--u) + 6px) calc(20 * var(--u) + 6px); }
.head { display: flex; align-items: baseline; gap: 12px; }
h2 { flex: 1; margin: 0; font-size: calc(26 * var(--u) + 8px); line-height: 1.1; letter-spacing: -.025em; }
.done-top { flex: none; font-size: calc(11 * var(--u) + 4px); min-height: 40px; padding: 0 calc(12 * var(--u) + 4px); border-radius: 14px; }
.sub { color: var(--a-ink-2); font-size: calc(13 * var(--u) + 4px); margin: 4px 0 calc(10 * var(--u) + 4px); line-height: 1.35; }

.beads { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.bead { background: var(--a-surface); border-radius: 16px; padding: 10px 10px 12px; display: grid; gap: 6px; justify-items: center; }
.bead svg { width: calc(70 * var(--u) + 22px); height: auto; }
.bead b { font-size: calc(11 * var(--u) + 4px); }
.bead span { font-size: calc(8 * var(--u) + 4px); color: var(--a-ink-3); text-align: center; line-height: 1.25; }
.bead :deep(.bed) { fill: color-mix(in srgb, var(--a-ink-3) 45%, transparent); }
.bead :deep(.line) { fill: var(--a-accent); }
.bead :deep(.thin) { opacity: .7; }

.squish { display: flex; align-items: center; gap: 12px; margin-top: calc(10 * var(--u) + 4px); background: var(--a-surface); border-radius: 20px; padding: 10px 12px; box-shadow: var(--a-card-shadow); }
.sq {
  appearance: none; border: 0; font: inherit; color: var(--a-ink); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  height: calc(48 * var(--u) + 16px); padding: 0 calc(14 * var(--u) + 4px); border-radius: 16px;
  background: var(--a-surface-2); font-weight: 700; font-size: calc(15 * var(--u) + 5px); white-space: nowrap;
}
.sq svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.sq:active { filter: brightness(1.1); transform: scale(0.98); }
.sq[disabled] { opacity: .4; cursor: default; }
.val { flex: 1; text-align: center; display: grid; gap: 2px; }
.val b { font-size: calc(15 * var(--u) + 5px); }
.val span { font-size: calc(9 * var(--u) + 4px); color: var(--a-ink-3); }
.err { color: var(--a-red-text); font-size: 14px; margin: 8px 0 0; }

/* The panel's sheet: the drawings stand on the sheet itself; the controls are a card */
.scrim:not(.phone) .bead { padding-top: calc(16 * var(--u) + 4px); }

/* Off the panel: a sheet from the bottom with the camera on top (B · The sheet, phone) */
.phone .sheet { background: var(--a-bg); }
.phone .bead { box-shadow: var(--a-card-shadow); }
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-ink-3); opacity: .5; margin: 0 auto 12px; }
.phone h2 { font-size: 22px; letter-spacing: -.02em; }
.phone .sub { font-size: 14.5px; color: var(--a-ink-3); margin: 4px 0 12px; }
.cam { border-radius: 18px; overflow: hidden; margin-bottom: 12px; max-height: 34vh; }   /* bigger than the board's strip: the line is what you're judging */
.phone .bead svg { width: 70px; }
.phone .bead b { font-size: 15px; }
.phone .squish { margin-top: 12px; }
.phone .sq { height: 52px; padding: 0 12px; font-size: 16px; gap: 5px; }
.phone .sq svg { width: 18px; height: 18px; }
.phone .val b { font-size: 16px; }
.phone .val span { font-size: 13px; }
.done-bottom { width: 100%; height: 52px; border-radius: 16px; margin-top: 12px; font-size: 18px; }

.sheet-enter-active, .sheet-leave-active { transition: opacity 0.18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
@media (max-width: 640px) {
  .scrim.phone { align-items: flex-end; padding: 0; background: rgba(8, 12, 20, .38); }
  .phone .sheet { border-radius: 28px 28px 0 0; padding: 10px 20px 28px; max-width: none; box-shadow: 0 -10px 40px rgba(16, 24, 40, .25); }
}
</style>
