<template>
  <!-- design/printers-home/, A: grouped by what to do, pictures, said once. wide: the overview behind a printer's
       "‹ Printers" on a laptop or tablet (design/printers-open/, A): who needs you first and widest, a card per printer. -->
  <main class="list-page" :class="{ wide }">
    <header v-if="wide" class="wbar">
      <h1 class="a-display">Printers</h1>
      <span class="tools">
        <router-link to="/look" class="pill"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z" /><path d="M3.5 7 12 11.5 20.5 7M12 11.5v10" /></svg>Look at a model</router-link>
        <YouLink />
      </span>
    </header>
    <div v-else class="title">
      <h1 class="a-display">Printers</h1>
      <span class="tools"><YouLink /></span>
    </div>
    <p v-if="awayAll" class="away-chip"><i aria-hidden="true"></i>Away from home</p>

    <p v-if="!printers.length && !benches.length" class="empty">
      Add your first printer: on the printer's screen, go to <b>Care</b>, then <b>Phones</b>, then
      <b>Add a phone</b>, and scan the code with this phone's camera.
    </p>

    <template v-if="wide">
      <component :is="homeOnlyRow(p) ? 'button' : RouterLink" v-for="p in needing" :key="p.id"
                 v-bind="homeOnlyRow(p) ? { type: 'button' } : { to: `/p/${p.id}` }"
                 class="need" :class="'tone-' + statusOf(p, atHomeOnly).tone">
        <span class="glyph" aria-hidden="true">!</span>
        <span class="words">
          <span class="who">{{ p.name }} · {{ statusOf(p, atHomeOnly).word.toLowerCase() }}<small v-if="markAway(p, printers)"> · away</small></span>
          <span class="say">{{ p.intent?.headline }}</span>
          <span v-if="p.intent?.detail" class="more">{{ p.intent.detail }}</span>
        </span>
        <span class="open">Open {{ p.name }}</span>
      </component>
      <div class="grid">
        <component :is="homeOnlyRow(p) ? 'button' : RouterLink" v-for="p in others" :key="p.id"
                   v-bind="homeOnlyRow(p) ? { type: 'button' } : { to: `/p/${p.id}` }"
                   class="card" :class="['tone-' + statusOf(p, atHomeOnly).tone, 'g-' + groupOf(p)]"
                   @click="homeOnlyRow(p) && (away = true)">
          <span class="shot">
            <template v-if="snapshotOf(p) && !noCamera[p.id]">
              <img :src="snapshotOf(p, tick)!" alt="" @error="noCamera[p.id] = true" />
              <span class="live"><i></i>Live</span>
            </template>
            <img v-else-if="pictureOf(p) && !broken[p.id]" class="obj" :src="pictureOf(p)!" alt="" @error="broken[p.id] = true" />
            <span v-else-if="groupOf(p) === 'ready'" class="swatch" aria-hidden="true"><i :style="{ background: loadedColor(p) ?? 'var(--a-ink-3)' }"></i></span>
            <span v-else-if="groupOf(p) === 'off'" class="dot" aria-hidden="true"></span>
          </span>
          <span class="words">
            <span class="row">
              <span class="name">{{ p.name }}</span>
              <span class="state">{{ cardOf(p, atHomeOnly, now).word }}<small v-if="markAway(p, printers)"> · away</small></span>
            </span>
            <span class="line" v-if="cardOf(p, atHomeOnly, now).line">{{ cardOf(p, atHomeOnly, now).line }}</span>
            <span v-if="cardOf(p, atHomeOnly, now).progress !== null" class="bar" aria-hidden="true"><i :style="{ width: cardOf(p, atHomeOnly, now).progress! * 100 + '%' }"></i></span>
          </span>
        </component>
        <router-link to="/add" class="card add"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>Add a printer</router-link>
      </div>
    </template>

    <section v-else v-for="g in groups" :key="g.group" class="group" :class="['g-' + g.group, g.group === 'attention' ? 'tone-' + attentionTone(g.printers) : '']">
      <h2 class="grp">{{ groupLabel(g.group, g.printers, atHomeOnly) }}</h2>
      <div :class="g.group === 'done' ? 'stack' : 'cards'">
        <component :is="homeOnlyRow(p) ? 'button' : RouterLink" v-for="p in g.printers" :key="p.id"
                   v-bind="homeOnlyRow(p) ? { type: 'button' } : { to: `/p/${p.id}` }"
                   class="printer" :class="'tone-' + statusOf(p, atHomeOnly).tone"
                   @click="homeOnlyRow(p) && (away = true)">
          <span v-if="g.group === 'attention'" class="glyph" aria-hidden="true">!</span>
          <img v-else-if="pictureOf(p) && !broken[p.id]" class="pic" :src="pictureOf(p)!" alt="" @error="broken[p.id] = true" />
          <span v-else-if="g.group === 'ready'" class="pic swatch" aria-hidden="true"><i :style="{ background: loadedColor(p) ?? 'var(--a-ink-3)' }"></i></span>
          <span v-else-if="g.group !== 'off'" class="pic" aria-hidden="true"></span>
          <span v-else class="dot" aria-hidden="true"></span>
          <span class="words">
            <span class="row">
              <span class="name">{{ p.name }}</span>
              <span class="state">{{ rowOf(p, atHomeOnly, now).word }}<small v-if="markAway(p, printers)"> · away</small></span>
            </span>
            <span class="line" v-if="rowOf(p, atHomeOnly, now).line">{{ rowOf(p, atHomeOnly, now).line }}</span>
            <span v-if="rowOf(p, atHomeOnly, now).progress !== null" class="bar" aria-hidden="true"><i :style="{ width: rowOf(p, atHomeOnly, now).progress! * 100 + '%' }"></i></span>
            <span v-if="g.group === 'attention'" class="next">See what happened</span>
          </span>
        </component>
      </div>
    </section>

    <!-- a Bench Box (design/bench-look/, C): its own app opens from here; How would it print? asks it for its printers -->
    <section v-if="benches.length" class="group">
      <h2 class="grp">Bench Box</h2>
      <div class="cards">
        <a v-for="b in benches" :key="b.id" :href="b.addresses.away ?? undefined" target="_blank" rel="noopener" class="printer"
           :class="b.reach === 'away' ? 'tone-green' : 'tone-off'">
          <span class="dot" aria-hidden="true"></span>
          <span class="words">
            <span class="row"><span class="name">{{ b.name }}</span><span class="state">{{ benchWord(b) }}</span></span>
            <span class="line" v-if="b.printers.length">{{ b.printers.length }} printers · {{ b.printers.map((x) => x.name).join(', ') }}</span>
          </span>
        </a>
      </div>
    </section>

    <div v-if="!wide" class="quiet">
      <router-link to="/look" class="pill">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z" /><path d="M3.5 7 12 11.5 20.5 7M12 11.5v10" /></svg>
        Look at a model
      </router-link>
      <router-link to="/add" class="pill">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
        Add a printer
      </router-link>
    </div>

    <div v-if="pitch" class="strip">
      <router-link to="/you" class="strip-go">
        <span class="qi" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M7 18.5h10.5a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.6 9.6 4.5 4.5 0 0 0 7 18.5z"/></svg></span>
        <span class="tx"><b>{{ GETS[0].title }}</b><span>{{ PITCH_STRIP_LINE }}</span></span>
        <span class="chev" aria-hidden="true">›</span>
      </router-link>
      <button class="x" :aria-label="NOT_NOW" @click="notNow">×</button>
    </div>

    <!-- design/one-cloud/, A-away: out of reach without a plan that carries the printers from away -->
    <Teleport to="body">
      <div v-if="away" class="away-scrim" @click.self="away = false">
        <div class="away-sheet" role="dialog" aria-modal="true" :aria-label="AWAY_TITLE">
          <span class="grab" aria-hidden="true"></span>
          <h2 class="a-display">{{ AWAY_TITLE }}</h2>
          <p class="sub">{{ AWAY_SUB }}</p>
          <CloudGets />
          <router-link to="/you" class="a-btn accent">{{ SEE_PLAN }}</router-link>
          <p class="note">{{ ALERTS_FREE }}</p>
        </div>
      </div>
    </Teleport>

    <section v-if="kept.length" class="lately">
      <h2 class="grp">Looked at lately</h2>
      <router-link v-for="k in kept.slice(0, 3)" :key="k.id" :to="`/look?r=${encodeURIComponent(k.id)}`" class="kept">
        <img class="thumb" :src="k.thumb" alt="" />
        <span class="name">{{ k.name }}</span>
        <span class="chev" aria-hidden="true">›</span>
      </router-link>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { benches, printers, type LiveBench } from '../printers'
import { statusOf } from '../status'
import { allAway, attentionTone, cardOf, groupOf, grouped, groupLabel, loadedColor, markAway, pictureOf, rowOf, snapshotOf } from '../home'
import { account, dismissPitch, pitchDismissed } from '../account'
import { ALERTS_FREE, AWAY_SUB, AWAY_TITLE, GETS, NOT_NOW, PITCH_STRIP_LINE, SEE_PLAN, homeOnly } from '../you'
import CloudGets from '../CloudGets.vue'
import YouLink from '../YouLink.vue'
import { recent, type Looked } from '../look'

const props = defineProps<{ wide?: boolean }>()

const benchWord = (b: LiveBench) => (b.reach === 'away' ? '' : b.reach === 'checking' ? 'Looking…' : b.reach === 'unpaired' ? 'Not paired any more' : "Can't reach it")
const groups = computed(() => grouped(printers))
const needing = computed(() => groups.value.find((g) => g.group === 'attention')?.printers ?? [])
const others = computed(() => groups.value.filter((g) => g.group !== 'attention').flatMap((g) => g.printers))
const noCamera = reactive<Record<string, boolean>>({})
const awayAll = computed(() => allAway(printers))
const broken = reactive<Record<string, boolean>>({})

const dismissed = ref(pitchDismissed())
const pitch = computed(() => printers.length > 0 && !dismissed.value && account.state !== 'checking' && account.state !== 'error' &&
  !(account.state === 'in' && account.me?.plan.on))
function notNow() { dismissPitch(); dismissed.value = true }
const atHomeOnly = computed(() => homeOnly(account.state === 'in' ? account.me : null, account.state === 'no-house'))
const away = ref(false)
const homeOnlyRow = (p: { reach: string }) => atHomeOnly.value && p.reach === 'offline'

const kept = ref<Looked[]>([])
onMounted(async () => { kept.value = await recent() })

// "2:30 pm" turns into "Yesterday" overnight
const now = ref(Date.now())
let minutes = 0
onMounted(() => { minutes = window.setInterval(() => { now.value = Date.now() }, 60_000) })
onBeforeUnmount(() => window.clearInterval(minutes))

// the overview's camera stills, a fresh one every few seconds while it's open
const tick = ref(0)
let stills = 0
onMounted(() => { if (props.wide) stills = window.setInterval(() => { tick.value++ }, 5000) })
onBeforeUnmount(() => window.clearInterval(stills))
</script>

<style scoped>
.list-page {
  min-height: 100dvh; box-sizing: border-box;
  padding: calc(18px + env(safe-area-inset-top, 0px)) 20px calc(28px + env(safe-area-inset-bottom, 0px));
  max-width: 640px; margin: 0 auto;
  background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font);
}
.list-page.wide { max-width: none; padding: 0 0 calc(28px + env(safe-area-inset-bottom, 0px)); }
.list-page.wide > :not(.wbar) { margin-left: 40px; margin-right: 40px; }
h1 { font-size: 34px; margin: 6px 0 10px; }
.title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tools { display: flex; align-items: center; gap: 10px; margin-top: -4px; }
.wbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; height: 64px; box-sizing: border-box;
  padding: env(safe-area-inset-top, 0px) 24px 0; border-bottom: 1px solid var(--a-line); margin-bottom: 30px; }
.wbar h1 { font-size: 28px; margin: 0; }
.wbar .tools { margin: 0; }
.away-chip { display: inline-flex; align-items: center; gap: 8px; margin: 0 0 6px; padding: 4px 12px; border-radius: 99px; font-size: 14px; font-weight: 650;
  color: var(--a-amber-text); background: color-mix(in srgb, var(--a-amber) 18%, transparent); }
.away-chip i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.empty { color: var(--a-ink-2); font-size: 17px; line-height: 1.5; margin: 8px 0 20px; }
.empty b { color: var(--a-ink); }

.group { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.grp { font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); margin: 8px 4px 0; }
.g-attention.tone-red .grp { color: var(--a-red-text); }
.g-attention.tone-amber .grp { color: var(--a-amber-text); }
.cards { display: flex; flex-direction: column; gap: 8px; }
.stack { display: flex; flex-direction: column; border-radius: 20px; background: var(--a-surface); box-shadow: var(--a-card-shadow); overflow: hidden; }

.printer {
  appearance: none; border: 0; font: inherit; text-align: left; width: 100%; box-sizing: border-box; cursor: pointer;
  display: flex; align-items: center; gap: 14px; padding: 12px 16px 12px 12px;
  border-radius: 20px; background: var(--a-surface); box-shadow: var(--a-card-shadow);
  color: inherit; text-decoration: none;
}
.printer:active { transform: scale(0.99); }
.printer:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 2px; }
.stack .printer { border-radius: 0; box-shadow: none; border-top: 1px solid var(--a-line); }
.stack .printer:first-child { border-top: 0; }
.g-attention .printer { box-shadow: 0 0 0 2px var(--a-red), var(--a-card-shadow); }
.g-attention .tone-amber { box-shadow: 0 0 0 2px var(--a-amber), var(--a-card-shadow); }
.g-off .printer { background: color-mix(in srgb, var(--a-surface) 60%, transparent); box-shadow: none; }

.pic { width: 52px; height: 52px; border-radius: 14px; flex: none; object-fit: contain; display: grid; place-items: center;
  background: radial-gradient(circle at 50% 38%, var(--a-obj-hi), var(--a-obj-lo)); }
.swatch { background: var(--a-surface-2); }
.swatch i { width: 22px; height: 22px; border-radius: 50%; box-shadow: 0 0 0 3px var(--a-surface-2), 0 0 0 5px var(--a-line); }
.glyph { width: 48px; height: 48px; border-radius: 50%; flex: none; display: grid; place-items: center; margin: 2px;
  font-weight: 800; font-size: 26px; color: #fff; background: var(--a-red); box-shadow: 0 0 0 5px color-mix(in srgb, var(--a-red) 18%, transparent); }
.tone-amber .glyph { background: var(--a-amber); color: var(--a-amber-ink, #241500); box-shadow: 0 0 0 5px color-mix(in srgb, var(--a-amber) 22%, transparent); }
.dot { width: 12px; height: 12px; border-radius: 50%; flex: none; margin: 0 6px; box-sizing: border-box; border: 2px solid var(--a-ink-3); }
.tone-green .dot { background: var(--a-green); border-color: var(--a-green); }

.words { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.name { font-weight: 700; font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.state { color: var(--a-ink); font-size: 14.5px; font-weight: 650; white-space: nowrap; }
.state small { color: var(--a-ink-3); font-size: 13px; font-weight: 600; }
.tone-busy .state { color: var(--a-accent-text); }
.tone-amber .state { color: var(--a-amber-text); }
.tone-red .state { color: var(--a-red-text); }
.g-done .state, .tone-off .state { color: var(--a-ink-3); font-weight: 600; }
.line { color: var(--a-ink-3); font-size: 14.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.g-attention .line { white-space: normal; line-height: 1.35; }
.bar { height: 6px; border-radius: 3px; background: var(--a-surface-2); overflow: hidden; margin-top: 4px; }
.bar i { display: block; height: 100%; border-radius: 3px; background: var(--a-accent); }
.next { align-self: flex-start; margin-top: 8px; padding: 9px 16px; border-radius: 99px; font-size: 15px; font-weight: 650;
  background: var(--a-accent); color: var(--a-accent-ink, #fff); }

.quiet { display: flex; flex-wrap: wrap; gap: 10px; margin: 18px 0 14px; }
.pill { display: inline-flex; align-items: center; gap: 8px; height: 42px; padding: 0 16px; border-radius: 99px; text-decoration: none;
  background: var(--a-surface); box-shadow: var(--a-card-shadow); color: var(--a-ink-2); font-weight: 650; font-size: 15px; }
.pill svg { width: 18px; height: 18px; color: var(--a-accent-text); }

.strip { display: flex; align-items: center; border-radius: 18px; background: var(--a-surface); box-shadow: var(--a-card-shadow); margin-bottom: 18px; }
.strip-go { flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 12px 4px 12px 12px; color: inherit; text-decoration: none; }
.qi { width: 36px; height: 36px; border-radius: 12px; flex: none; display: grid; place-items: center; color: var(--a-accent-text); background: color-mix(in srgb, var(--a-accent) 14%, transparent); }
.qi svg { width: 21px; height: 21px; }
.tx { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.tx b { font-size: 15.5px; font-weight: 650; }
.tx span { font-size: 13.5px; color: var(--a-ink-3); }
.x { appearance: none; border: 0; background: none; font: inherit; font-size: 22px; color: var(--a-ink-3); width: 44px; height: 44px; cursor: pointer; flex: none; }
.chev { color: var(--a-ink-3); font-size: 22px; flex: none; }

.away-scrim { position: fixed; inset: 0; z-index: 50; background: rgba(16, 20, 28, .36); display: flex; align-items: flex-end; justify-content: center; }
.away-sheet { width: 100%; max-width: 640px; box-sizing: border-box; background: var(--a-surface); color: var(--a-ink); font-family: var(--a-font);
  border-radius: 26px 26px 0 0; padding: 10px 20px calc(24px + env(safe-area-inset-bottom, 0px)); display: flex; flex-direction: column; gap: 14px;
  box-shadow: 0 -10px 30px rgba(16, 20, 28, .18); }
.away-sheet .grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); align-self: center; }
.away-sheet h2 { font-size: 26px; margin: 0; }
.away-sheet .sub { color: var(--a-ink-2); font-size: 16px; line-height: 1.4; margin: -4px 0 0; }
.away-sheet .a-btn { text-decoration: none; display: grid; place-items: center; font-size: 18px; }
.away-sheet .note { color: var(--a-ink-3); font-size: 14px; text-align: center; margin: 0; }

.lately { margin-bottom: 22px; }
.lately .grp { margin: 4px 2px 8px; }
.kept {
  display: flex; align-items: center; gap: 12px; padding: 10px 14px; margin-bottom: 8px;
  border-radius: 16px; background: var(--a-surface); color: inherit; text-decoration: none;
}
.kept .name { flex: 1; min-width: 0; font-size: 16px; font-weight: 600; }
.thumb { width: 40px; height: 40px; border-radius: 9px; flex: none; background: radial-gradient(circle at 50% 38%, var(--a-obj-hi), var(--a-obj-lo)); }

/* the wide overview (design/printers-open/, A) */
.need { appearance: none; border: 0; font: inherit; text-align: left; cursor: pointer; color: inherit; text-decoration: none;
  display: flex; align-items: center; gap: 22px; padding: 22px 26px; margin-bottom: 22px; border-radius: 24px; background: var(--a-surface);
  box-shadow: 0 0 0 2px var(--a-red), var(--a-card-shadow); }
.need.tone-amber { box-shadow: 0 0 0 2px var(--a-amber), var(--a-card-shadow); }
.need .glyph { width: 64px; height: 64px; font-size: 34px; box-shadow: 0 0 0 7px color-mix(in srgb, var(--a-red) 18%, transparent); }
.need.tone-amber .glyph { box-shadow: 0 0 0 7px color-mix(in srgb, var(--a-amber) 22%, transparent); }
.need .words { gap: 4px; }
.who { font-weight: 700; font-size: 17px; color: var(--a-ink-2); }
.who small { color: var(--a-ink-3); font-weight: 600; }
.say { font-size: 26px; font-weight: 750; letter-spacing: -.015em; line-height: 1.2; }
.more { font-size: 15px; color: var(--a-ink-3); line-height: 1.4; }
.open { flex: none; padding: 12px 22px; border-radius: 99px; font-weight: 650; font-size: 16px; background: var(--a-accent); color: var(--a-accent-ink, #fff); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 22px; margin-bottom: 22px; }
.card { appearance: none; border: 0; font: inherit; text-align: left; cursor: pointer; color: inherit; text-decoration: none; padding: 0;
  display: flex; flex-direction: column; border-radius: 24px; background: var(--a-surface); box-shadow: var(--a-card-shadow); overflow: hidden; }
.card:focus-visible, .need:focus-visible { outline: 2px solid var(--a-accent); outline-offset: 3px; }
.card .shot { position: relative; height: 196px; display: grid; place-items: center; overflow: hidden;
  background: radial-gradient(circle at 50% 40%, var(--a-obj-hi), var(--a-obj-lo)); }
.card .shot img { width: 100%; height: 100%; object-fit: cover; }
.card .shot img.obj { width: 62%; height: 80%; object-fit: contain; }
.card .shot .swatch { width: 64px; height: 64px; border-radius: 50%; display: grid; place-items: center; background: none; }
.card .shot .swatch i { width: 56px; height: 56px; }
.live { position: absolute; left: 12px; top: 12px; display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 99px;
  background: rgba(0, 0, 0, .6); color: #fff; font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.live i { width: 7px; height: 7px; border-radius: 50%; background: #f26060; }
.card .words { padding: 14px 18px 18px; }
.card .name { font-size: 19px; }
.card .state { font-size: 15px; }
.card.g-done .state { color: var(--a-green-text); font-weight: 650; }
.card.g-off { background: color-mix(in srgb, var(--a-surface) 60%, transparent); box-shadow: none; }
.card.add { background: transparent; box-shadow: none; border: 2px dashed var(--a-line); min-height: 260px; align-items: center; justify-content: center;
  gap: 8px; color: var(--a-ink-3); font-weight: 650; }
.card.add svg { width: 26px; height: 26px; color: var(--a-accent-text); }
</style>
