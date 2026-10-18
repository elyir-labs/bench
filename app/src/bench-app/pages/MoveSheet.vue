<template>
  <!-- Moving a model of the plan (design/bench-several/, C-move): its copies, where else it can print, its own bed, or
       out of this print; or a whole bed (Change printer on its card), without copies. On the box the sheet sits at the side, so the cards re-form beside it as you pick; on a phone it
       rises from the foot. Each pick is a change to the plan, planned again at once; Done only closes.
       Lying (11 October 2026): which side down, kept with the model; it opens the model page's sheet (SideSheet). -->
  <div class="mwrap" @click.self="emit('close')">
    <aside class="msheet" role="dialog" :aria-label="`Move ${title}`">
      <div class="top">
        <h2 class="a-display">{{ title }}</h2>
        <p class="muted">{{ sub }}</p>
      </div>
      <div v-if="pick" class="copies"><span>Copies</span>
        <button class="cstep" :disabled="pick.copies <= 1" aria-label="One fewer" @click="emit('change', { copies: pick.copies - 1 })">−</button>
        <b class="a-num">{{ pick.copies }}</b>
        <button class="cstep" :disabled="pick.copies >= 200" aria-label="One more" @click="emit('change', { copies: pick.copies + 1 })">+</button></div>
      <button v-if="side" class="side" :disabled="!side.can" @click="emit('side')">
        <span class="k">Lying</span>
        <span class="t"><b>{{ side.value }}</b><span>{{ side.line }}</span></span>
        <svg v-if="side.can" class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" /></svg>
      </button>
      <template v-if="fils?.length">
        <p class="label">In</p>
        <div class="chips" role="radiogroup" aria-label="Filament">
          <button v-for="f in fils" :key="f.key" role="radio" :aria-checked="f.key === fil" class="chip" :class="{ on: f.key === fil }"
                  @click="f.key === fil || emit('change', { in: filOf(f) })"><i :style="{ background: f.color ?? 'var(--a-surface-2)' }"></i>{{ f.name }}</button>
        </div>
      </template>
      <p class="label">Print it on</p>
      <div class="opts" role="radiogroup" aria-label="Print it on">
        <button v-for="o in options" :key="o.key" role="radio" :aria-checked="o.on" class="opt" :class="{ on: o.on, off: o.off }" :disabled="o.off"
                @click="o.on || emit('change', o.patch)">
          <span class="radio" aria-hidden="true"></span>
          <span class="t"><b>{{ o.title }}</b><span>{{ o.line }}</span></span>
        </button>
      </div>
      <div class="foot">
        <button class="takeout" @click="emit('change', { out: true })">{{ out ?? 'Take it out of this print' }}</button>
        <button class="a-btn accent done" @click="emit('close')">Done</button>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { filOf, type MoveOption, type PlanPick } from '../several'
import type { Filament } from '../shelf'

defineProps<{ title: string; sub: string; pick?: PlanPick; options: MoveOption[]; out?: string; fils?: Filament[]; fil?: string | null
  side?: { value: string; line: string; can: boolean } | null }>()
const emit = defineEmits<{ change: [patch: Partial<PlanPick>]; side: []; close: [] }>()
</script>

<style scoped>
.mwrap { position: fixed; inset: 0 0 86px auto; width: 510px; z-index: 20; padding: 16px 16px 14px 24px; box-sizing: border-box; display: flex; }
.msheet { flex: 1; min-height: 0; background: var(--a-surface); border-radius: 24px; box-shadow: 0 18px 50px rgba(16, 24, 40, .22), var(--a-card-shadow);
          display: flex; flex-direction: column; padding: 26px 24px 20px; gap: 12px; }
.top { display: grid; gap: 4px; }
.top h2 { margin: 0; font-size: 30px; letter-spacing: -.02em; line-height: 1.1; }
.muted { margin: 0; color: var(--a-ink-3); font-size: 17px; }
.copies { display: flex; align-items: center; gap: 12px; font-size: 19px; color: var(--a-ink-2); }
.copies > span { flex: 1; }
.copies b { font-size: 24px; min-width: 32px; text-align: center; color: var(--a-ink); }
.cstep { width: 46px; height: 46px; border-radius: 50%; border: 1px solid var(--a-line); background: var(--a-surface); color: var(--a-ink-2); font: inherit; font-size: 24px; cursor: pointer; }
.cstep:disabled { opacity: .4; cursor: default; }
.side { appearance: none; border: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 12px;
        padding: 10px 14px; border-radius: 16px; background: var(--a-surface-2); }
.side:disabled { cursor: default; }
.side:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.side .k { width: 64px; flex: none; color: var(--a-ink-3); font-size: 16px; }
.side .t b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.side .t span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chev { width: 18px; height: 18px; flex: none; fill: none; stroke: var(--a-ink-3); stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.label { margin: 6px 0 0; color: var(--a-ink-3); font-size: 14px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; max-height: 128px; overflow: auto; }
.chip { display: inline-flex; align-items: center; gap: 8px; border: 0; border-radius: 999px; padding: 8px 14px; font: inherit; font-size: 16px;
        font-weight: 650; background: var(--a-surface-2); color: var(--a-ink-2); cursor: pointer; }
.chip i { width: 14px; height: 14px; border-radius: 50%; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, .2); }
.chip.on { background: var(--a-ink); color: var(--a-bg); }
.opts { flex: 1; min-height: 0; overflow: auto; display: grid; align-content: start; }
.opt { appearance: none; border: 0; border-top: 1px solid var(--a-line); background: none; font: inherit; color: inherit; text-align: left; cursor: pointer;
       display: flex; align-items: center; gap: 14px; padding: 12px 12px; min-height: 64px; }
.opt.on { box-shadow: inset 0 0 0 2px var(--a-accent); border-radius: 4px; border-top-color: transparent; }
.opt.off { opacity: .5; cursor: default; }
.radio { width: 24px; height: 24px; flex: none; border-radius: 50%; box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--a-ink) 30%, transparent); }
.opt.on .radio { box-shadow: inset 0 0 0 2px var(--a-accent), inset 0 0 0 6px var(--a-surface); background: var(--a-accent); }
.t { flex: 1; min-width: 0; display: grid; gap: 2px; }
.t b { font-size: 18px; } .t span { color: var(--a-ink-3); font-size: 15px; }
.foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 8px; }
.takeout { appearance: none; border: 0; background: none; font: inherit; font-size: 18px; font-weight: 650; color: var(--a-red-text); padding: 8px 0; min-height: 48px; cursor: pointer; }
.done { width: auto; flex: none; height: 54px; font-size: 19px; padding: 0 30px; }
@media (max-width: 599px) {
  .mwrap { inset: 0; width: auto; padding: 0; background: rgba(16, 20, 28, .42); align-items: flex-end; }
  .msheet { border-radius: 24px 24px 0 0; max-height: 88dvh; padding: 18px 16px calc(12px + env(safe-area-inset-bottom, 0px)); gap: 8px; }
  .top h2 { font-size: 24px; } .muted { font-size: 14px; }
  .chip { font-size: 14px; padding: 6px 11px; }
  .copies { font-size: 16px; } .cstep { width: 40px; height: 40px; font-size: 20px; }
  .side { padding: 8px 12px; } .side .k { width: 52px; font-size: 14px; }
  .opt { min-height: 56px; padding: 10px 8px; } .t b { font-size: 16px; } .t span { font-size: 13px; }
  .takeout { font-size: 15px; } .done { height: 46px; font-size: 16px; padding: 0 22px; }
}
</style>
