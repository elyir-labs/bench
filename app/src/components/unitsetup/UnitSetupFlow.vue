<template>
  <!-- Set up a filament unit (design/unit-setup/, B, stage 2): boards b-unit, b-board, b-install and b-phone -->
  <section class="flow" :class="['step-' + us.step, { phone }]" aria-live="polite">
    <header class="fhead">
      <button class="back" :disabled="!back || !!store.busyAction" :aria-label="back?.label ?? 'Back'" @click="back && act(back)">
        <svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" /></svg>
      </button>
      <span class="where">{{ phone && (us.step === 'installing' || us.step === 'failed') ? `${SETUP_TITLE} · ${stepLabel(us)}` : us.where }}</span>
      <span v-if="!phone || (us.step !== 'installing' && us.step !== 'failed')" class="step a-num">{{ stepLabel(us) }}<span class="dots" aria-hidden="true"><i v-for="(d, i) in dots(us)" :key="i" :class="d"></i></span></span>
    </header>

    <!-- 1 of 5: which unit, by its picture -->
    <div v-if="us.step === 'unit'" class="body">
      <h1 class="a-display fh1">{{ us.headline }}</h1>
      <p class="fd small">{{ us.detail }}</p>
      <div class="tiles">
        <button v-for="u in us.units" :key="u.id" class="tile" :class="{ on: us.unit === u.id }" :disabled="!!store.busyAction || us.looking" @click="act(pick('unit', u.id))">
          <span class="pic"><UnitArt :kind="u.id" /></span>
          <b>{{ u.name }}</b><span class="ln">{{ u.line }}</span>
        </button>
        <button class="tile dashed" @click="guides = 'unit'">
          <span class="pic"><UnitArt kind="other" /></span>
          <b>Something else</b><span class="ln">Their guides, on your phone</span>
        </button>
      </div>
    </div>

    <!-- 2 of 5: which board, and how many slots -->
    <div v-else-if="us.step === 'board'" class="body">
      <h1 class="a-display fh1">{{ us.headline }}</h1>
      <p class="fd small">{{ us.looking ? 'Bench looks for the unit’s board…' : us.found }}</p>
      <div class="tiles">
        <button v-for="b in us.boards" :key="b.family" class="tile" :class="{ on: us.family === b.family }" :disabled="!!store.busyAction" @click="act(pick('board', b.board))">
          <span v-if="b.probably" class="badge">Probably</span>
          <span class="pic"><UnitArt :kind="b.family" /></span>
          <b>{{ b.name }}</b><span class="ln">{{ b.line }}</span>
        </button>
        <button class="tile dashed" @click="guides = 'board'">
          <span class="pic"><UnitArt kind="other" /></span>
          <b>Another board</b><span class="ln">Not yet: {{ guideName }}'s guide shows how</span>
        </button>
      </div>
      <div class="rows">
        <div v-if="versions.length" class="row"><span class="rl">Version</span>
          <button v-for="v in versions" :key="v.board" class="chip a-num" :class="{ on: us.board === v.board }" :disabled="!!store.busyAction" @click="act(pick('board', v.board))">{{ v.label }}</button>
        </div>
        <div v-if="us.slots" class="row"><span class="rl">Slots on this unit</span>
          <button v-for="n in us.slots.choices" :key="n" class="chip a-num" :class="{ on: us.slots.value === n }" :disabled="!!store.busyAction" @click="act(pick('slots', n))">{{ n }}</button>
        </div>
        <div v-if="us.ports.length" class="row"><span class="rl">Which one</span>
          <button v-for="p in us.ports" :key="p.mcu" class="chip" :class="{ on: us.mcu === p.mcu }" :disabled="!!store.busyAction" @click="act(pick('port', p.mcu))">{{ p.label }}</button>
        </div>
      </div>
    </div>

    <!-- 3 of 5: installing, or what stopped it -->
    <div v-else-if="us.step === 'installing' || us.step === 'failed'" class="body two">
      <div class="words">
        <h1 class="a-display fh1">{{ phone ? us.headline_phone : us.headline }}</h1>
        <ul class="list">
          <li v-for="s in us.progress?.steps ?? []" :key="s.id" :class="s.state">
            <span class="mk"><svg v-if="s.state === 'done'" viewBox="0 0 24 24"><path d="M6 12.5l4 4 8-9" /></svg><b v-else-if="s.state === 'failed'">!</b></span>
            <span class="lt"><span class="lb">{{ s.label }}</span><span v-if="s.sub && !phone" class="sb">{{ s.sub }}</span></span>
          </li>
        </ul>
        <p v-if="us.step === 'failed'" class="why">{{ us.why }}</p>
        <div v-else-if="us.progress" class="prog">
          <span class="bar"><i :style="{ width: us.progress.pct * 100 + '%' }"></i></span>
          <span v-if="!phone" class="pw">{{ us.progress.words }}</span>
        </div>
      </div>
      <aside v-if="!phone && us.note" class="note">
        <b>{{ us.note.title }}</b>
        <p>{{ us.note.text }}</p>
        <p class="foot">{{ us.note.foot }}</p>
      </aside>
      <aside v-if="phone && us.next && us.step === 'installing'" class="note next">
        <b>{{ us.next.title }}</b>
        <p>{{ us.next.text }}</p>
      </aside>
    </div>

    <!-- installed (waiting for the unit to show up), putting back, put back -->
    <div v-else class="body">
      <h1 class="a-display fh1">{{ us.headline }}</h1>
      <p class="fd"><span v-if="!us.actions.length" class="spin"></span>{{ us.detail }}</p>
    </div>

    <footer class="fbar">
      <span class="t">{{ us.step === 'unit' ? 'The name is usually on the front of the unit.' : '' }}</span>
      <template v-if="phone && us.step === 'installing' && !carry">
        <button class="a-btn accent wide" @click="carry = true">Carry on here</button>
        <button class="linkish" @click="leftToPanel = true">Use {{ printer }}'s screen</button>
      </template>
      <button
        v-for="a in barButtons(us)" :key="a.id + a.label" class="a-btn" :class="a.primary ? 'accent' : 'ghost'"
        :disabled="!!store.busyAction || (a.primary && !primaryReady(us))" @click="act(a)"
      >{{ store.busyAction === a.id ? '…' : a.label }}</button>
    </footer>

    <!-- Something else, Another board: the two projects' own guides (direction C) -->
    <div v-if="guides" class="sheet" role="dialog" @click.self="guides = null">
      <div class="card">
        <b>{{ card.title }}</b>
        <p>{{ card.text }}</p>
        <a v-for="g in card.guides" :key="g.url" class="guide" :href="g.url" target="_blank" rel="noopener">{{ g.name }}'s guide <span>{{ host(g.url) }}</span></a>
        <button class="a-btn ghost" @click="guides = null">Close</button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentAction } from '@/intent/types'
import {
  SETUP_TITLE, backAction, barButtons, dots, guidesCard, pick, primaryReady, stepLabel, versionsOf,
  type UnitSetupView,
} from '@/intent/unitSetup'
import UnitArt from './UnitArt.vue'
import { leftToPanel } from './handover'

const props = defineProps<{ us: UnitSetupView; phone: boolean; printer: string }>()
const store = useIntentStore()

const back = computed(() => backAction(props.us))
const versions = computed(() => versionsOf(props.us))
const guides = ref<'unit' | 'board' | null>(null)
const card = computed(() => guidesCard(props.us, guides.value ?? 'unit'))
const guideName = computed(() => props.us.program?.replace(/\s[\d.]+$/, '') ?? 'its software')
const carry = ref(false)

function host(url: string): string {
  try { return new URL(url).host } catch { return '' }
}

async function act(a: IntentAction) {
  await store.act(a)
}
</script>

<style scoped>
.flow { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: calc(6 * var(--u) + 2px) 36px 22px; overflow: auto; position: relative; }
.fhead { display: flex; align-items: center; gap: 12px; height: 38px; flex: none; }
.back { appearance: none; border: 0; width: 38px; height: 38px; border-radius: 50%; background: var(--a-surface); box-shadow: var(--a-card-shadow); display: grid; place-items: center; flex: none; color: var(--a-ink-2); cursor: pointer; padding: 0; }
.back svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.back[disabled] { opacity: 0.4; cursor: default; }
.where { font-size: 16px; font-weight: 600; color: var(--a-ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.step { margin-left: auto; display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600; color: var(--a-ink-3); white-space: nowrap; }
.dots { display: flex; gap: 5px; }
.dots i { width: 8px; height: 8px; border-radius: 50%; background: var(--a-surface-2); }
.dots i.d { background: var(--a-accent); }
.dots i.n { background: var(--a-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--a-accent) 22%, transparent); }

.body { flex: 1; min-height: 0; margin-top: 14px; }
.body.two { display: flex; gap: 24px; justify-content: space-between; align-items: flex-start; }
.words { flex: 0 1 420px; min-width: 0; }
.fh1 { font-size: 32px; line-height: 1.08; margin: 0; text-wrap: pretty; }
.fd { font-size: 19px; color: var(--a-ink-2); line-height: 1.35; margin: 8px 0 0; display: flex; align-items: center; gap: 10px; }
.fd.small { font-size: 17px; margin-top: 4px; }

.tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.step-board .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 18px; }
.step-board .tile { min-height: 0; padding-bottom: 10px; }
.step-board .pic { height: 54px; }
.step-board .fbar { margin-top: 0; }
.tile { appearance: none; position: relative; background: var(--a-surface); border: 2px solid transparent; border-radius: 18px; box-shadow: var(--a-card-shadow); padding: 10px 10px 12px; display: grid; justify-items: center; align-content: start; gap: 4px; cursor: pointer; color: var(--a-ink); font: inherit; text-align: center; min-height: 160px; }
.tile.on { border-color: var(--a-accent); }
.tile.dashed .pic { background: transparent; border: 1.5px dashed var(--a-line); }
.tile[disabled] { cursor: default; }
.pic { width: 100%; height: 66px; border-radius: 12px; background: var(--a-surface-2); display: block; padding: 4px; box-sizing: border-box; margin-bottom: 6px; }
.tile b { font-size: 17px; line-height: 1.15; }
.tile .ln { font-size: 13px; color: var(--a-ink-3); line-height: 1.3; }
.badge { position: absolute; top: -10px; left: 50%; transform: translateX(-50%); background: var(--a-accent); color: #fff; font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; padding: 2px 10px; border-radius: 999px; }

.rows { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-top: 10px; }
.row { display: flex; align-items: center; gap: 8px; }
.rl { font-size: 15px; color: var(--a-ink-2); margin-right: 6px; }
.chip { appearance: none; border: 1.5px solid var(--a-line); background: var(--a-surface); color: var(--a-ink); border-radius: 999px; min-width: 44px; height: 38px; padding: 0 14px; font: inherit; font-size: 16px; font-weight: 600; cursor: pointer; }
.chip.on { border-color: var(--a-accent); color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 10%, var(--a-surface)); }

.list { list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 8px; }
.list li { display: flex; gap: 12px; align-items: flex-start; }
.mk { width: 26px; height: 26px; border-radius: 50%; flex: none; display: grid; place-items: center; box-sizing: border-box; border: 2px solid var(--a-line); }
.done .mk { background: var(--a-green, #1f8a4c); border-color: transparent; }
.mk svg { width: 16px; height: 16px; fill: none; stroke: #fff; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.now .mk { border-color: var(--a-surface-2); border-top-color: var(--a-accent); animation: spin 0.9s linear infinite; }
.failed .mk { background: var(--a-amber, #d08a1a); border-color: transparent; color: #fff; font-size: 15px; }
.lt { display: grid; gap: 1px; }
.lb { font-size: 18px; line-height: 1.3; }
.next .lb { color: var(--a-ink-3); }
.sb { font-size: 14px; color: var(--a-ink-3); }
.why { font-size: 17px; line-height: 1.35; margin: 14px 0 0; color: var(--a-ink); }
.prog { margin-top: 18px; display: grid; gap: 8px; }
.bar { display: block; width: 420px; max-width: 100%; height: 8px; border-radius: 4px; background: var(--a-surface-2); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--a-accent); border-radius: 4px; transition: width 0.5s linear; }
.pw { font-size: 16px; color: var(--a-ink-3); }

.note { flex: 0 0 290px; background: var(--a-surface); border-radius: 18px; box-shadow: var(--a-card-shadow); padding: 16px 18px; display: grid; gap: 6px; }
.note b { font-size: 18px; }
.note p { margin: 0; font-size: 16px; color: var(--a-ink-2); line-height: 1.35; }
.note .foot { font-size: 14px; color: var(--a-ink-3); margin-top: 6px; }

.spin { width: 18px; height: 18px; border-radius: 50%; border: 2.5px solid var(--a-surface-2); border-top-color: var(--a-accent); flex: none; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.fbar { flex: none; display: flex; align-items: center; gap: 14px; min-height: 60px; margin-top: 10px; }
.fbar .t { flex: 1; min-width: 0; font-size: 16px; color: var(--a-ink-3); }
.fbar .a-btn { flex: none; height: 60px; min-height: 60px; font-size: 21px; border-radius: 20px; padding: 0 30px; }
.fbar .a-btn[disabled] { opacity: .45; }
.linkish { appearance: none; border: 0; background: none; color: var(--a-accent); font: inherit; font-size: 15px; font-weight: 600; cursor: pointer; padding: 6px; }

.sheet { position: absolute; inset: 0; background: color-mix(in srgb, var(--a-bg, #000) 55%, transparent); display: grid; place-items: center; padding: 20px; z-index: 5; }
.card { background: var(--a-surface); border-radius: 22px; box-shadow: var(--a-card-shadow); padding: 20px 22px; max-width: 460px; display: grid; gap: 10px; }
.card b { font-size: 20px; }
.card p { margin: 0; font-size: 16px; color: var(--a-ink-2); line-height: 1.4; }
.guide { display: flex; justify-content: space-between; gap: 10px; align-items: center; padding: 12px 14px; border-radius: 14px; background: var(--a-surface-2); color: var(--a-ink); text-decoration: none; font-weight: 600; }
.guide span { font-weight: 400; color: var(--a-ink-3); font-size: 14px; }
.card .a-btn { justify-self: end; min-height: 48px; padding: 0 22px; }

/* Phones: one column, the tiles two across, the buttons across the bottom (board b-phone) */
.phone.flow { padding: 8px 20px calc(16px + env(safe-area-inset-bottom, 0px)); }
.phone .where { font-size: 15px; }
.phone .body { margin-top: 18px; }
.phone .body.two { flex-direction: column; align-items: stretch; justify-content: flex-start; gap: 20px; }
.phone .words { flex: none; }
.phone .fh1 { font-size: 28px; }
.phone .tiles, .phone.step-board .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.phone .tile { min-height: 140px; }
.phone .bar { width: 100%; }
.phone .note { flex: none; }
.phone .note p { font-size: 15.5px; }
.phone .fbar { flex-wrap: wrap; justify-content: center; }
.phone .fbar .t { flex: 1 1 100%; font-size: 15px; }
.phone .fbar .t:empty { display: none; }
.phone .fbar .a-btn { flex: 1 1 0; height: 56px; min-height: 56px; font-size: 18px; padding: 0 16px; }
.phone .fbar .a-btn.wide { flex: 1 1 100%; }
.phone .fbar .linkish { flex: 1 1 100%; }
</style>
