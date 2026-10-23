<template>
  <!-- The printer gone, on a phone (design/power/): off, restarting, or not answering, instead of its last state -->
  <section v-if="gone" class="now gone" :class="['now-' + lay, 'gone-' + gone.kind]">
    <div class="gone-body">
      <svg class="gone-glyph" viewBox="0 0 24 24" aria-hidden="true">
        <path v-if="gone.kind === 'restarting'" d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5" />
        <path v-else d="M12 3.5v8M6.6 6.9a7.6 7.6 0 1 0 10.8 0" />
      </svg>
      <h1 class="headline a-display">{{ gone.headline }}</h1>
      <p class="detail">{{ gone.detail }}</p>
    </div>
  </section>

  <section v-else-if="intent" class="now" :class="['is-' + state, 'now-' + lay, { 'has-cam': showCam }]">
    <!-- the light's switch where there's no camera and no top bar: inside the Printers app (design/chamber-light/, A) -->
    <LightButton v-if="lightWhere === 'now'" variant="pill" class="now-light" />
    <!-- Ready: calm idle -->
    <div v-if="state === 'ready'" class="body ready" :class="{ 'has-actions': actions.length }">
      <div class="left">
        <!-- a job from Move and heat holding the printer (design/hands-on/, C): what's hot, or how high -->
        <span v-if="handsChip" class="warmchip" :class="{ cool: intent.hands?.held?.kind === 'clear' }"><i></i>{{ handsChip }}</span>
        <div v-else-if="!warmOn && !firstLayerCard" class="bigclock a-display a-num">{{ bigClock }}</div>
        <span v-else-if="warmOn" class="warmchip" :class="{ done: intent.warm?.warm }"><i></i>{{ intent.warm?.warm ? 'Warm' : 'Warming up' }}</span>
        <h1 class="headline a-display">{{ intent.headline }}</h1>
        <!-- one question at a time: the first-layer card takes the clock's and the spools' room -->
        <p v-if="!firstLayerCard || intent.phase === 'cancelled'" class="detail">{{ intent.detail }}</p>
        <FirstLayerCard v-if="firstLayerCard" :card="firstLayerCard" />
        <WarmMeters v-if="warmOn" :warm="intent.warm!" class="warm-meters" />
        <!-- Ready stays calm: its rare action sits with the words, not as a full-width bar -->
        <div v-if="actions.length && !firstLayerCard" class="inline-actions">
          <button
            v-for="a in actions"
            :key="a.id"
            :class="a.id === 'warm_choose' && !a.primary ? 'link' : ['a-btn', a.primary ? (a.style === 'default' ? 'accent' : a.style) : 'ghost']"
            :disabled="busy !== null"
            @click="onAction(a)"
          >{{ busy === a.id ? '…' : a.label }}</button>
        </div>
        <SpoolRow v-if="!warmOn && !firstLayerCard" :spools="intent.spools" hide-empty class="spools" />
        <!-- off the panel, the space under the spools: what's next (design/ready-phone/, C) -->
        <LostCard v-if="lost && lay !== 'panel'" :lost="lost" :thumb="lostThumb" compact :disabled="busy !== null" @rest="openRest" @again="onStartOver" />
        <UpNext v-if="upRows.length" :rows="upRows" class="up-next" @pick="onUpNext" />
      </div>
      <LostCard v-if="lost && lay === 'panel'" :lost="lost" :thumb="lostThumb" class="right" :disabled="busy !== null" @rest="openRest" @again="onStartOver" />
      <button v-else class="right hint" @click="door.away ? router.push('/print') : onPrintAgain()">
        <ObjectImage :src="lastThumb" :alt="lastName" class="hint-img" />
        <span class="hint-text">
          <span class="a-display">{{ lastJob ? 'Print again' : 'Print' }}</span>
          <span class="sub">{{ door.away ? 'Start prints at the printer' : (lastJob ? lastName : 'Recent prints') }}</span>
        </span>
      </button>
      <!-- off the panel, the camera leads Now in Ready too: is the bed clear? (design/camera-anytime/, A) -->
      <NowCamera v-if="showCam" :camera="camera!" :idle="camWay === 'idle'" class="hero" @failed="camFailed = true" />
    </div>

    <!-- Preparing: checklist beside the object -->
    <div v-else-if="state === 'preparing'" class="body two">
      <div class="left">
        <p v-if="camDown" class="camchip"><span>Camera isn't answering</span><button class="link" @click="camFailed = false">Try again</button></p>
        <h1 class="headline a-display">{{ intent.job && !change && !carrying && !powerWait && !outage ? 'Getting ready' : intent.headline }}</h1>
        <div v-if="intent.job && !change && !carrying && !powerWait && !outage" class="chip">
          <ObjectImage :src="thumbUrl" :alt="intent.job.name" class="chip-img" />
          <span class="chip-name">{{ intent.job.name }}</span>
          <span class="chip-meta a-num"><template v-if="intent.job.estimated_s">about {{ human(intent.job.estimated_s) }}</template><template v-if="matchedShort"> · {{ matchedShort }}</template></span>
        </div>
        <p v-else class="detail">{{ intent.detail }}</p>
        <ol class="steps" :class="{ cols: change && change.kind !== 'colour' && intent.steps.length > 4, snug: change?.kind === 'colour' }" v-if="intent.steps.length">
          <li v-for="s in intent.steps" :key="s.id" :class="['step-' + s.status, { you: s.you }]">
            <span class="chk" aria-hidden="true">{{ s.status === 'done' ? '✓' : '' }}</span>
            <span>{{ s.label }}<small v-if="s.detail && s.status === 'now'" class="step-detail"> · {{ s.detail }}</small></span>
            <em v-if="s.you && s.status !== 'done'" class="you-tag">you</em>
          </li>
        </ol>
      </div>
      <NowCamera v-if="showCam" :camera="camera!" :progress="prepProgress" :thumb="intent.job && !change ? thumbUrl : undefined" :alt="intent.job?.name" :pill="change ? changePill : prepPill" class="hero" @failed="camFailed = true" />
      <!-- turning off or restarting (design/power/): the ring empties as the nozzle cools to its fan's 50° -->
      <Ring v-else-if="powerWait" :value="1 - (intent.power?.progress ?? 0)" label="" :color="'var(--a-accent)'" class="ring">
        <template #face><svg class="nozzle-glyph" viewBox="-14 -12 52 52" aria-hidden="true"><path d="M6 2h12v8l-3 4h-6l-3-4z" /><path d="M9 14v4l3 6 3-6v-4" /></svg></template>
        {{ Math.round(intent.printer.nozzle.temperature) }}°
      </Ring>
      <!-- the power is back (design/power-loss/, A): the wait for it to settle, then the nozzle warming -->
      <Ring v-else-if="outageRing" :value="outageRing.value" :label="outageRing.label" :color="'var(--a-accent)'" class="ring">{{ outageRing.text }}</Ring>
      <Ring v-else-if="change" :value="prepProgress" label="" :color="'var(--a-accent)'" class="ring">
        <template #face><UnitArt v-if="unitArt" :art="change.art" :slot="change.slot ?? 0" :color="change.out?.color" /><HeadArt v-else :art="(change.art as any)" :out="change.out?.color" :in="change.in?.color" /></template>
        {{ changePill }}
      </Ring>
      <!-- no camera: the step, drawn from the printer's own numbers (design/now-illustrated/, A) -->
      <Ring v-else-if="intent.job && art?.stage" :value="prepProgress" label="" :color="'var(--a-accent)'" class="ring">
        <template #art><StepArt :art="art" :bed="intent.printer.bed" :nozzle="intent.printer.nozzle" :chamber="intent.printer.chamber" :filament="filament" :moving="true" /></template>
        {{ prepPill }}
      </Ring>
      <Ring v-else-if="intent.job" :value="prepProgress" label="" :color="'var(--a-accent)'" :image="thumbUrl" :alt="intent.job.name" class="ring">
        {{ prepPill }}
      </Ring>
    </div>

    <!-- Printing: name, finish time, ring -->
    <div v-else-if="state === 'printing'" class="body two">
      <div class="left">
        <p v-if="camDown" class="camchip"><span>Camera isn't answering</span><button class="link" @click="camFailed = false">Try again</button></p>
        <h1 class="headline big a-display">{{ intent.headline }}</h1>
        <p class="detail">
          <template v-if="intent.job?.eta_clock">Done at about <b class="a-num">{{ intent.job.eta_clock }}</b></template>
          <template v-else>{{ intent.detail }}</template>
          <br />
          <span class="muted a-num"><template v-if="intent.job?.layer">Layer {{ intent.job.layer }}<template v-if="intent.job.layers"> of {{ intent.job.layers }}</template> · </template>{{ remainingLabel }}</span>
        </p>
        <!-- It carried on with a matching spool by itself (design/slots/, B) -->
        <div v-if="intent.carried" class="carried">
          <span class="dot" :style="{ '--c': carriedColor }"></span>
          <span class="w"><b>{{ intent.carried.headline }}</b><span>{{ intent.carried.detail }}</span></span>
          <button v-for="a in intent.carried.actions" :key="a.id" class="a-btn ghost" :disabled="busy !== null" @click="onAction(a)">{{ a.label }}</button>
        </div>
        <!-- First layer (design/first-layer/, B): one quiet button while layers 1 to 3 go down -->
        <p v-if="showCheck" class="check"><button class="a-btn accent" @click="checking = true">Check the first layer</button></p>
        <!-- the panel has room for one of the two during the first layers; the board gives it to the button -->
        <!-- More than one part on the plate: skip one that fails (design/skip-objects/, A). On the panel it takes the spools' place. -->
        <PartsRow v-if="intent.parts && !(showCheck && lay === 'panel')" :parts="intent.parts" @open="partsOpen = true" />
        <SpoolRow v-if="!(showCheck && lay === 'panel') && !intent.carried && !(intent.parts && lay === 'panel')" :spools="intent.spools" :highlight="intent.job?.colors ?? []" only-in-use feeding class="spools" />
      </div>
      <NowCamera v-if="showCam" :camera="camera!" :progress="intent.job?.progress ?? 0" :thumb="thumbUrl" :alt="intent.job?.name" :pill="pct + '%'" class="hero" @failed="camFailed = true" />
      <!-- no camera: the object built up to the layer it's on -->
      <Ring v-else-if="building" :value="intent.job?.progress ?? 0" :label="remainingLabel" :color="'var(--a-accent)'" class="ring">
        <template #art><BuildArt :src="thumbUrl" :alt="intent.job?.name" :built="art!.built!" :moving="true" /></template>
        {{ pct }}<small>%</small>
      </Ring>
      <Ring v-else :value="intent.job?.progress ?? 0" :label="remainingLabel" :color="'var(--a-accent)'" :image="thumbUrl" :alt="intent.job?.name" class="ring">
        {{ pct }}<small>%</small>
      </Ring>
    </div>

    <!-- Needs you: one sentence, the spool that matters -->
    <div v-else-if="state === 'needs_you'" class="body two attention" :class="{ 'colour-panel': colourPause && lay === 'panel' }">
      <div class="left">
        <h1 class="headline a-display" :class="{ wrap: change?.kind === 'colour' }"><StateGlyph v-if="showCam && !colourPause && change?.kind !== 'colour'" kind="needs_you" class="inline-glyph" />{{ intent.headline }}</h1>
        <p class="detail">{{ showCam && change?.look ? change.look + ' ' : '' }}{{ intent.detail }}{{ colourPause?.asks && lay !== 'panel' ? ' ' + colourPause.asks : '' }}</p>
        <!-- a colour change on a printer with a unit (design/colour-change/, A): the spools are the answer -->
        <template v-if="colourPause">
          <ColourPick :colour="colourPause" :picked="pickedSlot" :away="door.away" :compact="lay !== 'panel'"
                      :warm="warmShort" :disabled="busy !== null" @pick="pickTile" />
          <p v-if="pstep.says" class="says" :class="{ asking: pstep.tone }">
            <b>{{ pstep.says[0] }}</b>{{ pstep.says[1] }}
            <button v-if="pickedTile?.link && stageDone === 0 && !(door.away && pickedTile.at_printer)" class="link" :disabled="busy !== null"
                    @click="onAction(pickedTile.link!)">{{ pickedTile.link.label }}</button>
          </p>
          <p v-if="door.away && colourPause.away_note" class="away-note">{{ colourPause.away_note }}</p>
        </template>
        <!-- switching colour on a phone: the steps, the check last (SPhone) -->
        <ol v-if="change?.kind === 'colour' && lay !== 'panel' && intent.steps.length" class="steps colour-steps">
          <li v-for="s in intent.steps" :key="s.id" :class="['step-' + s.status, { you: s.you }]">
            <span class="chk" aria-hidden="true">{{ s.status === 'done' ? '✓' : '' }}</span>
            <span>{{ s.label }}</span>
            <em v-if="s.you && s.status !== 'done'" class="you-tag">you</em>
          </li>
        </ol>
        <!-- changing filament: "What is it?" as one-tap answers -->
        <div v-if="change && (change.choices.length || change.ask)" class="choices" role="group" aria-label="What is the new filament?">
          <button
            v-for="c in change.choices"
            :key="c.label"
            class="choice"
            :class="{ on: c.primary }"
            :disabled="busy !== null || !allowedHere(c.id)"
            @click="onAction(c)"
          ><span class="dot" :style="{ '--c': (c.args?.color as string) || 'transparent' }"></span>{{ c.label }}</button>
          <button class="choice plain" :disabled="busy !== null || !allowedHere('change_what')" @click="picking = true">Something else</button>
        </div>
        <p v-if="change && holdLabel && (change.kind !== 'colour' || change.step === 'put')" class="hold">{{ holdLabel }}</p>
        <!-- holding on a battery (design/power-loss/, A) -->
        <ul v-if="outage" class="hold-facts">
          <li v-for="f in holdFacts(outage)" :key="f">{{ f }}</li>
        </ul>
        <SpoolRow v-else-if="!change && !colourPause" :spools="intent.spools" :note="holdLabel" class="spools" />
        <PartsRow v-if="intent.parts && !change && lay !== 'panel'" :parts="intent.parts" @open="partsOpen = true" />
      </div>
      <NowCamera v-if="showCam" :camera="camera!" tone="amber" class="hero" @failed="camFailed = true" />
      <Ring v-else-if="outageRing" :value="outageRing.value" :label="outageRing.label" :color="'var(--a-amber)'" class="ring">{{ outageRing.text }}</Ring>
      <Ring v-else-if="change" :value="prepProgress" label="" :color="'var(--a-amber)'" :ink="'var(--a-amber-ink)'" class="ring">
        <template #face><UnitArt v-if="unitArt" :art="change.art" :slot="change.slot ?? 0" :color="change.in?.color" you /><HeadArt v-else :art="(change.art as any)" :out="change.out?.color" :in="change.in?.color" you /></template>
        {{ changePill }}
      </Ring>
      <!-- paused by a person: the print where it stopped, still and dimmed; nothing is moving -->
      <Ring v-else-if="pausedArt" :value="intent.job?.progress ?? 0" label="" :color="'var(--a-amber)'" :ink="'var(--a-amber-ink)'" class="ring">
        <template #art><BuildArt :src="thumbUrl" :alt="intent.job?.name" :built="art!.built!" :moving="false" /></template>
        Paused
      </Ring>
      <StateGlyph v-else-if="!(colourPause && lay === 'panel')" kind="needs_you" class="glyph" />
    </div>

    <!-- Problem: reason, what already happened, what to try -->
    <div v-else-if="state === 'problem'" class="body two attention">
      <div class="left">
        <h1 class="headline a-display"><StateGlyph v-if="showCam" kind="problem" class="inline-glyph" />{{ intent.headline }}</h1>
        <p class="detail">{{ intent.detail }}</p>
        <p v-if="showRaw && intent.raw" class="raw">{{ intent.raw }}</p>
        <!-- design/report/, B: quiet, so it never competes with what to try; on the panel it sits under the sign -->
        <button v-if="lay !== 'panel' || showCam" class="tell-link" @click="openTell">Tell Elyir about this ›</button>
      </div>
      <NowCamera v-if="showCam" :camera="camera!" tone="red" class="hero" @failed="camFailed = true" />
      <div v-else class="glyph-side">
        <StateGlyph kind="problem" class="glyph" />
        <button v-if="lay === 'panel'" class="tell-link" @click="openTell">Tell Elyir about this ›</button>
      </div>
    </div>

    <!-- Finished: release countdown -->
    <div v-else-if="state === 'finished'" class="body two">
      <div class="left">
        <h1 class="headline big a-display">{{ intent.headline }}</h1>
        <p class="detail">{{ intent.detail }}</p>
        <p v-if="intent.job" class="summary a-num">{{ intent.job.name }}<template v-if="intent.job.elapsed_s"> · {{ human(intent.job.elapsed_s) }}</template><template v-if="intent.job.grams"> · {{ intent.job.grams }} g</template></p>
        <FirstLayerCard v-if="firstLayer?.keep" :card="firstLayer.keep" />
        <PartsRow v-else-if="intent.parts" :parts="intent.parts" finished @open="partsOpen = true" />
        <!-- a part skipped mid-print, printed again the way the plate was (design/skip-objects/, A) -->
        <p v-if="againOffered" class="again">
          <button class="a-btn accent" :disabled="againBusy" @click="printSkippedAgain">{{ againBusy ? 'Getting it ready…' : againLabel }}</button>
          <span v-if="againError" class="err">{{ againError }}</span>
        </p>
      </div>
      <NowCamera v-if="showCam" :camera="camera!" :thumb="thumbUrl" :alt="intent.job?.name" :pill="Math.round(intent.printer.bed.temperature) + '°'" class="hero" @failed="camFailed = true" />
      <Ring v-else :value="coolProgress" :label="intent.phase === 'ready_to_lift' ? 'ready to lift' : 'bed cooling'" :color="'var(--a-green)'" :ink="'var(--a-green-ink)'" :image="thumbUrl" :alt="intent.job?.name" class="ring">
        {{ Math.round(intent.printer.bed.temperature) }}<small>°</small>
      </Ring>
    </div>

    <!-- Finish setting up (design/getting-started/, C): under Ready, never on the panel -->
    <SetupCard v-if="lay !== 'panel'" :ready="state === 'ready'" class="setup" />

    <Vitals v-if="lay !== 'panel'" :intent="intent" tiles class="tiles" />

    <!-- the first-layer question is answered first; the board has no action row beside it -->
    <div class="actions" :class="{ tight: colourPause && lay === 'panel', 'lone-right': change?.kind === 'colour' && actions.length === 1 && lay !== 'compact' }" v-if="actions.length && state !== 'ready' && !(state === 'finished' && firstLayerCard)">
      <template v-for="a in actions" :key="a.id">
        <!-- Ending a print is held, never tapped (AGENTS.md, 3 October 2026) -->
        <HoldButton
          v-if="a.hold"
          :label="a.label"
          :class="a.primary ? (a.style === 'default' ? 'accent' : a.style) : 'ghost'"
          :disabled="busy !== null"
          :busy="busy === a.id"
          @run="onAction(a)"
        />
        <button
          v-else
          class="a-btn"
          :class="a.primary ? (a.style === 'default' ? 'accent' : a.style) : 'ghost'"
          :disabled="busy !== null && a.id !== 'help'"
          @click="onAction(a)"
        >{{ busy === a.id ? '…' : a.label }}</button>
      </template>
    </div>
    <p v-if="heldBack" class="at-printer">{{ actions.length ? 'The rest is done at the printer.' : 'This is done at the printer.' }}</p>
    <p v-if="error" class="err">{{ error }}</p>
    <FileSheet v-if="lib" :item="opened" :check="opened ? lib.checks.value[opened.filename] : null" :printer="intent?.printer.name || 'the printer'"
               @close="opened = null" @refused="c => (refusal = c)" />
    <PrintCheckSheet :check="refusal" @close="refusal = null" />
    <PrintRestSheet v-if="lost" :open="restOpen" :lost="lost" :thumb="lostThumb" :printer="intent.printer.name" :why="restWhy"
                    :busy="restBusy" :error="restError" @close="restOpen = false" @rest="onRest" @again="onStartOver" />
    <ChangeWhatSheet :open="picking" @close="picking = false" />
    <WarmSheet :open="warmPicking" @close="warmPicking = false" />
    <HandsSheet :open="handsOpen" @close="handsOpen = false" />
    <TellSheet :open="telling" :context="tellContext" :printer-name="intent?.printer.name" @close="telling = false" />
    <FirstLayerSheet :open="checking" @close="checking = false" />
    <PartsSheet v-if="intent?.parts" :open="partsOpen" :parts="intent.parts" :printer="intent.printer.name" :busy="busy === 'skip_part'"
                :wide="lay === 'panel'" :finished="state === 'finished'" @close="partsOpen = false" @skip="skipPart" />
  </section>

  <section v-else class="now waiting">
    <p class="detail">Waking up…</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { IntentAction, PrintCheck } from '@/intent/types'
import { useRouter } from 'vue-router'
import Ring from '@/components/now/Ring.vue'
import SpoolRow from '@/components/now/SpoolRow.vue'
import ObjectImage from '@/components/now/ObjectImage.vue'
import StateGlyph from '@/components/now/StateGlyph.vue'
import PrintCheckSheet from '@/components/print/PrintCheckSheet.vue'
import FileSheet from '@/components/print/FileSheet.vue'
import UpNext from '@/components/now/UpNext.vue'
import LostCard from '@/components/now/LostCard.vue'
import PrintRestSheet from '@/components/now/PrintRestSheet.vue'
import { holdFacts, holdRing } from '@/intent/lost'
import { useLibrary } from '@/print/useLibrary'
import { upNext, type UpRow } from '@/print/upnext'
import type { Item } from '@/print/library'
import { careOf } from '@/intent/care'
import { goneView, nextMemo, type Gone, type PowerMemo } from '@/intent/power'
import HoldButton from '@/components/now/HoldButton.vue'
import HeadArt from '@/components/now/HeadArt.vue'
import UnitArt from '@/components/now/UnitArt.vue'
import StepArt from '@/components/now/StepArt.vue'
import BuildArt from '@/components/now/BuildArt.vue'
import ChangeWhatSheet from '@/components/now/ChangeWhatSheet.vue'
import WarmMeters from '@/components/warm/WarmMeters.vue'
import WarmSheet from '@/components/warm/WarmSheet.vue'
import HandsSheet from '@/components/hands/HandsSheet.vue'
import TellSheet from '@/components/report/TellSheet.vue'
import { contextOf, type ReportContext } from '@/report/words'
import FirstLayerSheet from '@/components/now/FirstLayerSheet.vue'
import FirstLayerCard from '@/components/now/FirstLayerCard.vue'
import PartsRow from '@/components/now/PartsRow.vue'
import PartsSheet from '@/components/now/PartsSheet.vue'
import ColourPick from '@/components/now/ColourPick.vue'
import { needsSheet, offered, pauseStep, tileOf } from '@/intent/colour'
import { canPrintAgain, canPrintRest, printAgain, printRest } from '@/slice/again'
import { checkShown } from '@/intent/firstLayer'
import { prettyName } from '@/intent/jobs'
import NowCamera from '@/components/now/NowCamera.vue'
import Vitals from '@/components/now/Vitals.vue'
import SetupCard from '@/components/setup/SetupCard.vue'
import { layout as currentLayout } from '@/shell/useLayout'
import type { Layout } from '@/shell/layout'
import { useCameras } from '@/camera/useCameras'
import { nowCamera } from '@/camera/cameras'
import LightButton from '@/components/light/LightButton.vue'
import { lightPlace, nowCameraShown } from '@/intent/light'
import { embedded } from '@/auth'

// The shell passes the arrangement for the Now pane; as a route (panel, phone) it follows the window.
const props = defineProps<{ layout?: Layout }>()
const lay = computed<Layout>(() => props.layout ?? currentLayout.value)
import { allowedHere, door } from '@/door'
import { isPanel } from '@/theme'
import { heldChip } from '@/intent/hands'

const store = useIntentStore()
// Tell Elyir about this (design/report/, B): the moment the problem screen showed goes with the report
const telling = ref(false)
const tellContext = ref<ReportContext | null>(null)
function openTell() { tellContext.value = contextOf(store.intent); telling.value = true }
const intent = computed(() => store.intent)
const state = computed(() => intent.value?.state ?? 'ready')
const busy = computed(() => store.busyAction)
const error = computed(() => store.actionError)
const showRaw = ref(false)
const router = useRouter()

// Off the panel, a camera takes the ring's place (B with the camera, design/responsive/).
// A camera that stops answering hands back to the ring, and gets another try a minute later.
const { cameras } = useCameras()
const camera = computed(() => cameras.value[0] ?? null)
const camFailed = ref(false)
let camRetry = 0
watch(camFailed, (f) => { if (f) camRetry = window.setTimeout(() => (camFailed.value = false), 60000) })
onBeforeUnmount(() => window.clearTimeout(camRetry))
// Turning off or restarting (design/power/): the wait for the nozzle, drawn as a ring; no camera for it
const powerWait = computed(() => intent.value?.phase === 'turning_off' || intent.value?.phase === 'restarting')
// Warming up before a print (design/warm-up/, D): Ready shows it instead of the clock
const warmOn = computed(() => !!intent.value?.warm?.active)
const camWay = computed(() => nowCamera(intent.value?.state, { warming: warmOn.value }))
const showCam = computed(() => lay.value !== 'panel' && !!camera.value && !camFailed.value && !!camWay.value && !powerWait.value)
watch(showCam, (v) => { nowCameraShown.value = v }, { immediate: true })
onBeforeUnmount(() => { nowCameraShown.value = false })
const lightWhere = computed(() => lightPlace({ light: !!intent.value?.light, cameraOnNow: showCam.value, embedded }))

const thumbUrl = computed(() => store.fileUrl(intent.value?.job?.thumbnail))
// Without a camera (or with it off), the ring shows what the printer is doing (design/now-illustrated/, A).
// A camera that was there and stopped answering says so, off the panel; one that was never there doesn't.
const camDown = computed(() => lay.value !== 'panel' && !!camera.value && camFailed.value)
const art = computed(() => intent.value?.art ?? null)
const building = computed(() => !!thumbUrl.value && art.value?.built != null)
const pausedArt = computed(() => intent.value?.phase === 'paused' && building.value && !change.value)
const filament = computed(() => intent.value?.spools.find((s) => s.in_use)?.color ?? null)
const lastJob = computed(() => store.lastJob)
const lastThumb = computed(() => store.thumbOf(lastJob.value))
const lastName = computed(() => (lastJob.value ? prettyName(lastJob.value.filename) : ''))
const refusal = ref<PrintCheck | null>(null)
// The printer gone (design/power/), on a phone only: the panel is the printer. This browser remembers seeing it
// go off or restart (it can't ask once it's gone) and the printer's name, for a page opened while it's off.
const POWER_KEY = 'elyir-bench.power', NAME_KEY = 'elyir-bench.printerName'
const stored = <T,>(k: string): T | null => { try { return JSON.parse(localStorage.getItem(k) ?? 'null') } catch { return null } }
const store_ = (k: string, v: unknown) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)) } catch { /* private window */ } }
const powerMemo = ref<PowerMemo | null>(stored<PowerMemo>(POWER_KEY))
const lostAt = ref<number | null>(null)
const clockNow = ref(Date.now() / 1000)
const goneTimer = isPanel ? 0 : window.setInterval(() => { clockNow.value = Date.now() / 1000 }, 1000)
onBeforeUnmount(() => window.clearInterval(goneTimer))
watch(() => store.connected, (c) => { lostAt.value = c ? null : Date.now() / 1000 }, { immediate: true })
watch(() => (store.connected && intent.value ? [intent.value.power, intent.value.printer.name] as const : null), (v) => {
  if (!v) return
  const [power, name] = v
  const next = nextMemo(powerMemo.value, power, name, Date.now() / 1000)
  if (next !== powerMemo.value) { powerMemo.value = next; store_(POWER_KEY, next) }
  if (name && stored<string>(NAME_KEY) !== name) store_(NAME_KEY, name)
}, { immediate: true })
const gone = computed<Gone | null>(() => isPanel ? null : goneView({
  connected: store.connected, name: intent.value?.printer.name || stored<string>(NAME_KEY) || '', memo: powerMemo.value,
  lostFor: lostAt.value == null ? 0 : clockNow.value - lostAt.value, now: clockNow.value,
}))
// Up next (design/ready-phone/, C): the panel keeps its Print again card and never loads the library for this
const lib = isPanel ? null : useLibrary()
const opened = ref<Item | null>(null)
const upRows = computed<UpRow[]>(() => {
  // the phone only: a tablet or laptop shows the Print tab beside Now, and the rows would repeat it
  if (!lib?.loaded.value || lay.value !== 'compact' || warmOn.value || firstLayerCard.value) return []
  return upNext(lib.items.value, careOf(intent.value)?.items, lib.now.value)
})
function onUpNext(r: UpRow) {
  if (r.kind === 'care') router.push('/care')
  else if (r.kind === 'start') router.push('/print/model')
  else opened.value = r.item
}
// Changing filament (design/change-filament/, B): a state of Now, with the head drawn in the ring
const change = computed(() => intent.value?.change ?? null)
const changePill = computed(() => {
  const c = change.value
  if (!c) return ''
  if (c.pill) return c.pill
  return c.step === 'resume' ? 'Ready to carry on' : `Step ${c.n} of ${c.of}`
})
const picking = ref(false)
// Swapping the spool in a slot (design/slots/, B): the unit is drawn, except while it leaves the head
const unitArt = computed(() => (change.value?.kind === 'slot' && change.value.art !== 'out')
  || (change.value?.kind === 'colour' && ['insert', 'back', 'still'].includes(change.value.art)))
const carrying = computed(() => intent.value?.phase === 'carrying_on' || intent.value?.phase === 'colour_resuming')
// A colour change on a printer with a unit (design/colour-change/, A): a tap on a tile picks it, the amber button
// says what will happen, and another material or a switch from away asks once more before anything is sent.
const colourPause = computed(() => (state.value === 'needs_you' ? intent.value?.colour ?? null : null))
const pickedSlot = ref<number | null>(null)
const stageDone = ref(0)
// a string, so a new intent object every second doesn't undo what was tapped
watch(() => `${colourPause.value?.n}|${colourPause.value?.picked}|${colourPause.value?.reason}|${door.away}`, () => {
  const c = colourPause.value
  const t = tileOf(c, c?.picked)
  pickedSlot.value = t && offered(t, door.away) ? t.slot : null
  stageDone.value = 0
}, { immediate: true })
const pickedTile = computed(() => tileOf(colourPause.value, pickedSlot.value))
const pstep = computed(() => pauseStep(pickedTile.value, door.away, stageDone.value))
function pickTile(slot: number) {
  pickedSlot.value = slot
  stageDone.value = 0
}
const warmShort = computed(() => {
  const exp = intent.value?.expires
  if (!exp) return ''
  const ms = new Date(exp).getTime() - nowTick.value
  return ms <= 0 ? 'Cooling down to stay safe' : `Kept warm for ${human(ms / 1000)} more`
})
const carriedColor = computed(() => intent.value?.spools.find((s) => s.slot === intent.value?.carried?.to)?.color || 'transparent')
const handsChip = computed(() => heldChip(intent.value?.hands?.held ?? null, intent.value?.printer.nozzle.temperature ?? 0))
const warmPicking = ref(false)
const handsOpen = ref(false)
watch(() => change.value?.ask, (ask) => { if (!ask) picking.value = false })
// First layer (design/first-layer/, B): the button, its sheet, and the questions after
const firstLayer = computed(() => intent.value?.first_layer ?? null)
const showCheck = computed(() => checkShown(intent.value, allowedHere))
// Keep it? at the end (Finished, or Print stopped.); Clear it? on Ready when tap arrives
const firstLayerCard = computed(() => firstLayer.value?.keep ?? (state.value === 'ready' ? firstLayer.value?.ask : null) ?? null)
const checking = ref(false)
// Away, only what the door allows; the rest is named once, not offered and refused.
const actions = computed(() => {
  const list = (intent.value?.actions ?? []).filter((a) => allowedHere(a.id))
  if (!colourPause.value) return list
  // the amber button reads the picked tile (APause): its words, and what a tap sends
  return list.flatMap((a) => (a.id !== 'colour_choose' ? [a]
    : pstep.value.label ? [{ ...a, label: pstep.value.label, args: pstep.value.send?.args ?? a.args }] : []))
})
const heldBack = computed(() => (intent.value?.actions.length ?? 0) > actions.value.length)

// A power cut (design/power-loss/, A): held on a battery, carrying on once it's back, or a print it took
const outage = computed(() => intent.value?.outage ?? null)
const outageRing = computed(() => (outage.value ? holdRing(outage.value, intent.value?.printer.nozzle.temperature ?? 0) : null))
const lost = computed(() => (state.value === 'ready' ? intent.value?.lost ?? null : null))
const lostThumb = computed(() => (lost.value && lastJob.value?.filename === lost.value.file ? lastThumb.value : null))
const restOpen = ref(false)
const restBusy = ref(false)
const restError = ref('')
const restWhy = ref<string | null>(null)
async function openRest() {
  if (!lost.value) return
  restError.value = ''
  restWhy.value = isPanel ? 'It\'s sliced on a phone or laptop: Print the rest is on Now there.'
    : door.away ? 'It\'s sliced at home: Print the rest from a phone or laptop on the same Wi-Fi.'
    : (await canPrintRest(store.call, lost.value.file)) ? null : 'It wasn\'t sliced here, so there\'s no model to cut.'
  restOpen.value = true
}
async function onRest() {
  const i = intent.value
  if (!lost.value || !i) return
  restBusy.value = true
  restError.value = ''
  try {
    await printRest(store.call, lost.value, (i.spools ?? []) as any, i.printer.name)
    restOpen.value = false
    router.push('/print/model')
  } catch (e) {
    restError.value = e instanceof Error ? e.message : String(e)
  } finally {
    restBusy.value = false
  }
}
async function onStartOver() {
  if (!lost.value) return
  restOpen.value = false
  const check = await store.requestPrint(lost.value.file)
  if (needsSheet(check)) refusal.value = check
}

async function onPrintAgain() {
  if (!lastJob.value) return router.push('/print')
  const check = await store.requestPrint(lastJob.value.filename)
  if (needsSheet(check)) refusal.value = check
}

const pct = computed(() => Math.floor((intent.value?.job?.progress ?? 0) * 100))

function human(seconds: number | null | undefined): string {
  if (seconds == null) return ''
  const m = Math.round(seconds / 60)
  if (m < 1) return 'under a minute'
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `${h} h ${r} m` : `${h} h`
}
const remainingLabel = computed(() => {
  const r = intent.value?.job?.remaining_s
  return r == null ? 'working it out' : `${human(r)} left`
})

// "Keeping warm for 18 more minutes"
const nowTick = ref(Date.now())
let t = 0
onMounted(() => { t = window.setInterval(() => (nowTick.value = Date.now()), 15000) })
onBeforeUnmount(() => window.clearInterval(t))
const holdLabel = computed(() => {
  const exp = intent.value?.expires
  if (!exp) return ''
  const ms = new Date(exp).getTime() - nowTick.value
  if (ms <= 0) return 'Cooling down to stay safe'
  return `Keeping everything warm for ${human(ms / 1000)} more`
})

// Finished: how far the bed has cooled toward release (from 60 → 35 as a visual)
const coolProgress = computed(() => {
  const bed = intent.value?.printer.bed.temperature ?? 0
  const hi = 60, lo = 35
  return Math.max(0, Math.min(1, (hi - bed) / (hi - lo)))
})

// preflight progress for the ring: done steps, plus half credit for the one running
const prepProgress = computed(() => {
  const st = intent.value?.steps ?? []
  if (!st.length) return 0
  const done = st.filter(s => s.status === 'done').length
  const now = st.some(s => s.status === 'now') ? 0.5 : 0
  return (done + now) / st.length
})
const prepPill = computed(() => {
  const st = intent.value?.steps ?? []
  const i = st.findIndex(s => s.status === 'now')
  return st.length ? `Step ${(i < 0 ? st.filter(s => s.status === 'done').length : i) + 1} of ${st.length}` : ''
})
const matchedShort = computed(() => matchedNote.value.replace(/^Matched to |^Using /, ''))

// "Matched to slots 1 and 6" while preparing
const matchedNote = computed(() => {
  const colors = intent.value?.job?.colors ?? []
  const spools = intent.value?.spools ?? []
  const dist = (a: string, b: string) => {
    const p = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16))
    const [r1, g1, b1] = p(a), [r2, g2, b2] = p(b)
    return Math.hypot(r1 - r2, g1 - g2, b1 - b2)
  }
  const slots = colors.map(c => spools.find(s => s.color && s.status !== 'empty' && dist(c.toUpperCase(), s.color.toUpperCase()) < 70)?.slot)
  const found = slots.filter((x): x is number => typeof x === 'number').map(x => x + 1)
  if (!found.length) return ''
  if (found.length === 1) return `Using slot ${found[0]}`
  return `Matched to slots ${found.slice(0, -1).join(', ')} and ${found[found.length - 1]}`
})

const bigClock = computed(() => {
  nowTick.value // re-run on tick
  return new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).replace(/\s?[ap]m$/i, '')
})

// Skip a part (design/skip-objects/, A): Klipper's EXCLUDE_OBJECT, through the engine, which checks it first.
const partsOpen = ref(false)
async function skipPart(name: string) { await store.act('skip_part', { name }) }
// Print a skipped part again: off the panel and at home (Print a model isn't on the panel, nor away yet)
const againBusy = ref(false)
const againError = ref('')
const againOffered = computed(() => state.value === 'finished' && !isPanel && !door.away && canPrintAgain(intent.value?.parts))
const againLabel = computed(() => {
  const sk = intent.value?.parts?.skipped ?? []
  return sk.length === 1 ? `Print ${sk[0].charAt(0).toLowerCase()}${sk[0].slice(1)} again` : `Print the ${sk.length} skipped again`
})
async function printSkippedAgain() {
  const i = intent.value
  if (!i?.parts || !i.job?.filename) return
  againBusy.value = true
  againError.value = ''
  try {
    await printAgain(store.call, i.job.filename, i.parts, (i.spools ?? []) as any, i.printer.name)
    router.push('/print/model')
  } catch (e) {
    againError.value = e instanceof Error ? e.message : String(e)
  } finally {
    againBusy.value = false
  }
}

async function onAction(a: IntentAction) {
  if (a.id === 'help') {
    // Nothing to send to the printer: show the underlying text right here.
    showRaw.value = !showRaw.value
    return
  }
  if (a.id === 'hands_open') {
    handsOpen.value = true
    return
  }
  if (a.id === 'warm_choose') {
    warmPicking.value = true
    return
  }
  if (a.id === 'open_materials') {
    router.push('/materials')
    return
  }
  if (a.id === 'colour_choose' && colourPause.value && a.args?.how !== 'swap') {
    const st = pstep.value
    if (!st.send) {
      stageDone.value += 1   // ask once more first (another material; a switch from away)
      return
    }
    await store.act(st.send)
    stageDone.value = 0
    return
  }
  await store.act(a)
}
</script>

<style scoped>
.now {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: calc(6 * var(--u) + 2px) calc(28 * var(--u) + 8px) calc(14 * var(--u) + 4px);
  gap: calc(10 * var(--u) + 4px);
  min-height: 0;
  overflow: hidden;
}
.body { flex: 1; display: grid; align-items: safe center; align-content: safe center; gap: calc(24 * var(--u) + 8px); min-height: 0; overflow: hidden; margin: 0 -12px; padding: 0 12px; container-type: size; }
.body.two { grid-template-columns: minmax(0, 1.25fr) auto; }
.body.ready { grid-template-columns: minmax(0, 1.4fr) auto; }
.body.one { grid-template-columns: minmax(0, 1fr); gap: 0; }
.body.attention { grid-template-columns: minmax(0, 1fr) auto; gap: calc(20 * var(--u) + 8px); }
.is-preparing .headline { font-size: calc(30 * var(--u) + 8px); }
.is-preparing .chip { margin-top: calc(4 * var(--u) + 2px); }
.is-preparing .chip-img { width: calc(28 * var(--u) + 6px); height: calc(28 * var(--u) + 6px); }
.is-preparing .chip-name { font-size: calc(16 * var(--u) + 5px); }
.is-preparing .steps { margin-top: calc(5 * var(--u) + 2px); gap: calc(4 * var(--u) + 1px); }
.is-preparing .headline { line-height: 1; }
.body.attention .detail { max-width: none; font-size: calc(17 * var(--u) + 5px); }
.body.attention .headline { font-size: calc(33 * var(--u) + 10px); }
.body.attention .spools { margin-top: calc(2 * var(--u) + 1px); }
.left { min-width: 0; }

.headline {
  margin: 0;
  font-size: calc(36 * var(--u) + 10px);
  color: var(--a-ink);
}
.headline.big { font-size: calc(48 * var(--u) + 12px); }
/* the panel has room for one line of name while printing: a long one (a plate of several parts) wrapped and
   pushed the first-layer button and the parts row off the screen */
.now-panel.is-printing .headline.big, .now-panel.is-needs_you .headline { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail {
  margin: calc(6 * var(--u) + 4px) 0 0;
  font-size: calc(18 * var(--u) + 5px);
  line-height: 1.35;
  color: var(--a-ink-2);
  max-width: 34ch;
}
.detail b { color: var(--a-ink); font-weight: 600; }
.one .detail { max-width: 56ch; font-size: calc(17 * var(--u) + 5px); }
.one .headline { font-size: calc(34 * var(--u) + 10px); }
.muted { color: var(--a-ink-3); font-size: 0.85em; }
.spools { margin-top: calc(6 * var(--u) + 2px); }

.bigclock {
  font-weight: 400;
  font-size: calc(84 * var(--u) + 16px);
  letter-spacing: -0.04em;
  line-height: 1;
  color: var(--a-ink-2);
  margin-bottom: calc(6 * var(--u) + 2px);
}
.ready .headline { font-size: calc(30 * var(--u) + 8px); }
.hint {
  appearance: none; border: 0; font: inherit; color: inherit; text-align: left;
  justify-self: end;
  align-self: center;
  display: flex;
  flex-direction: column;
  padding: 0;
  border-radius: calc(20 * var(--u) + 6px);
  background: var(--a-surface);
  width: calc(230 * var(--u) + 50px);
  overflow: hidden;
  cursor: pointer;
  box-shadow: var(--a-card-shadow);
}
.hint:active { filter: brightness(1.12); }
.hint-img { width: 100%; aspect-ratio: 4 / 3; }
.hint-text { display: flex; flex-direction: column; padding: calc(12 * var(--u) + 4px) calc(16 * var(--u) + 6px) calc(14 * var(--u) + 5px); }
.hint .a-display { font-size: calc(22 * var(--u) + 7px); }
.hint .sub { color: var(--a-ink-3); font-size: calc(13 * var(--u) + 4px); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.hold-facts { margin: calc(10 * var(--u) + 4px) 0 0; padding: 0; list-style: none; display: grid; gap: calc(4 * var(--u) + 3px); max-width: 40ch; }
.hold-facts li { position: relative; padding-left: 18px; color: var(--a-ink-2); font-size: calc(13 * var(--u) + 5px); line-height: 1.3; }
.hold-facts li::before { content: ''; position: absolute; left: 2px; top: .5em; width: 7px; height: 7px; border-radius: 50%; background: var(--a-amber); }

.chip {
  display: inline-flex; align-items: center; gap: calc(10 * var(--u) + 4px);
  margin-top: calc(6 * var(--u) + 2px);
  padding: calc(4 * var(--u) + 1px) calc(14 * var(--u) + 4px) calc(4 * var(--u) + 1px) calc(4 * var(--u) + 1px);
  border-radius: calc(14 * var(--u) + 4px);
  background: var(--a-surface);
  max-width: 100%;
}
.chip-img { width: calc(32 * var(--u) + 8px); height: calc(32 * var(--u) + 8px); border-radius: calc(8 * var(--u) + 3px); flex: none; }
.chip + .detail { margin-top: calc(6 * var(--u) + 2px); }
.chip ~ .spools { margin-top: calc(6 * var(--u) + 2px); }
.chip-name { font-weight: 600; font-size: calc(18 * var(--u) + 5px); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chip-meta { color: var(--a-ink-3); font-size: calc(13 * var(--u) + 4px); white-space: nowrap; }
.again { margin: calc(6 * var(--u) + 6px) 0 0; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.again .err { font-size: 14px; color: var(--a-red-text); }
.summary { margin: calc(8 * var(--u) + 3px) 0 0; color: var(--a-ink-3); font-size: calc(15 * var(--u) + 4px); }

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: calc(6 * var(--u) + 2px);
  margin-top: calc(8 * var(--u) + 3px);
  font-size: calc(13 * var(--u) + 4px);
  color: var(--a-ink-2);
  white-space: nowrap;
}
.steps li { display: flex; align-items: center; gap: calc(10 * var(--u) + 4px); line-height: 1.2; }
.steps .chk {
  width: calc(18 * var(--u) + 5px); height: calc(18 * var(--u) + 5px);
  border-radius: 50%;
  border: 1.5px solid var(--a-line);
  display: grid; place-items: center;
  font-size: 0.7em;
  flex: none;
}
.steps li.step-done { color: var(--a-ink-3); text-decoration: line-through; }
.steps li.step-done .chk { background: var(--a-green); border-color: var(--a-green); color: var(--a-green-ink); }
.steps li.step-now { color: var(--a-ink); font-weight: 600; }
.steps li.step-now .chk { border-color: var(--a-accent); box-shadow: 0 0 0 4px color-mix(in srgb, var(--a-accent) 25%, transparent); }
.step-detail { font-size: .92em; font-weight: 500; color: var(--a-accent-text); }
.camchip { display: flex; align-items: center; gap: 10px; margin: 0 0 10px; font-size: 15px; color: var(--a-ink-2); }
.glyph-side { display: flex; flex-direction: column; align-items: center; gap: calc(8 * var(--u)); }
.glyph-side .tell-link { text-align: center; }
.tell-link { appearance: none; border: 0; background: none; padding: calc(6 * var(--u) + 2px) 0 0; font: inherit;
  font-size: calc(14 * var(--u) + 5px); font-weight: 650; color: var(--a-accent-text); cursor: pointer; text-align: left; }
.camchip .link { font: inherit; font-weight: 600; color: var(--a-accent-text); background: none; border: 0; padding: 4px 2px; cursor: pointer; }
/* changing filament has up to six steps: two columns of three, read down */
.steps.cols { display: grid; grid-template-rows: repeat(3, auto); grid-auto-flow: column; grid-auto-columns: max-content; column-gap: calc(22 * var(--u) + 8px); }
.now-compact .steps.cols { display: flex; }
.you-tag {
  font-style: normal; font-size: 0.68em; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  padding: 2px 7px; border-radius: 99px; text-decoration: none;
  background: color-mix(in srgb, var(--a-amber) 22%, transparent); color: var(--a-amber-text);
}

/* changing filament: "What is it?" */
.choices { display: flex; flex-wrap: wrap; gap: calc(8 * var(--u) + 2px); margin-top: calc(12 * var(--u) + 4px); }
.choice {
  appearance: none; font: inherit; font-weight: 600; cursor: pointer; color: var(--a-ink);
  display: inline-flex; align-items: center; gap: 8px; white-space: nowrap;
  font-size: calc(14 * var(--u) + 4px); min-height: 44px;
  padding: 0 calc(13 * var(--u) + 4px) 0 calc(7 * var(--u) + 2px);
  border-radius: 99px; border: 1px solid var(--a-line); background: var(--a-surface);
}
.choice.plain { padding: 0 calc(13 * var(--u) + 4px); }
.choice.on { border-color: var(--a-amber); box-shadow: 0 0 0 2px var(--a-amber); }
.choice .dot { width: calc(20 * var(--u) + 6px); height: calc(20 * var(--u) + 6px); border-radius: 50%; background: var(--c); border: 2px solid var(--a-swatch-edge); }
.choice[disabled] { cursor: default; opacity: .6; }
.hold { margin: calc(10 * var(--u) + 3px) 0 0; color: var(--a-ink-3); font-size: calc(12 * var(--u) + 4px); }
/* the colour-change pause (design/colour-change/, A): on the panel the tiles take the ring's room */
.body.attention.colour-panel { grid-template-columns: minmax(0, 1fr); }
.colour-panel .detail { margin-top: calc(4 * var(--u) + 2px); }
.colour-panel .headline { font-size: calc(36 * var(--u)); }
/* APause: the tiles take room the buttons give up */
.actions.tight :deep(.a-btn), .actions.tight .a-btn { padding-block: calc(12 * var(--u) + 6px); }
.says { margin: calc(9 * var(--u) + 2px) 0 0; font-size: calc(15 * var(--u) + 2px); color: var(--a-ink-2); line-height: 1.35; }
.says b { color: var(--a-ink); font-weight: 700; }
.says.asking { color: var(--a-amber-text); }
.says.asking b { color: var(--a-amber-text); }
.says .link { appearance: none; border: 0; background: none; padding: 0 0 0 calc(10 * var(--u)); cursor: pointer; font: inherit;
              color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px; }
.away-note { margin: 8px 0 0; font-size: 14px; color: var(--a-ink-3); line-height: 1.35; }
.now-compact .says, .now-split .says, .now-stacked .says { font-size: 15px; }
.colour-steps { margin-top: 14px; }
/* switching colour: Stop alone sits under the ring, as on the boards (CAuto, SSwitch, SWhat) */
.actions.lone-right { justify-content: flex-end; }
.actions.lone-right > * { flex: 0 0 calc(50% - 6 * var(--u) - 2px); }
/* five steps fit beside the ring (SSwitch), and the check's question may take two lines (SCheck) */
.is-preparing .steps.snug { gap: calc(5 * var(--u) + 1px); margin-top: calc(6 * var(--u) + 2px); }
.steps.snug li { margin: 0; }
.is-preparing .headline:has(+ .detail) { line-height: 1.05; }
.now-panel.is-needs_you .headline.wrap { white-space: normal; font-size: calc(32 * var(--u) + 4px); line-height: 1.12; }

.ring { justify-self: end; --size: min(calc(196 * var(--u) + 34px), calc(100cqh - 14px)); align-self: start; margin-top: 2px; }

.actions { display: flex; gap: calc(12 * var(--u) + 4px); }
.at-printer { margin: calc(6 * var(--u) + 2px) 0 0; color: var(--a-ink-3); font-size: calc(14 * var(--u) + 4px); }
/* a Ready screen with something to do gives the clock's room to the words and buttons */
.ready.has-actions .bigclock { font-size: calc(56 * var(--u) + 14px); }
.inline-actions { display: flex; gap: calc(10 * var(--u) + 4px); margin: calc(2 * var(--u) + 2px) 0 calc(10 * var(--u) + 4px); }
.inline-actions { align-items: center; flex-wrap: wrap; }
.inline-actions .link {
  appearance: none; border: 0; background: none; padding: 6px 2px; cursor: pointer; font: inherit;
  font-size: calc(14 * var(--u) + 4px); color: var(--a-accent-text); text-decoration: underline; text-underline-offset: 3px;
}
.carried {
  display: flex; align-items: center; gap: calc(10 * var(--u) + 4px); margin-top: calc(12 * var(--u) + 4px);
  padding: calc(10 * var(--u) + 2px) calc(10 * var(--u) + 2px) calc(10 * var(--u) + 2px) calc(14 * var(--u) + 2px);
  border-radius: calc(14 * var(--u) + 4px); background: color-mix(in srgb, var(--a-accent) 16%, var(--a-surface));
}
.carried .dot { width: calc(26 * var(--u) + 6px); height: calc(26 * var(--u) + 6px); border-radius: 50%; flex: none;
                background: var(--c); border: 3px solid var(--a-swatch-edge); box-sizing: border-box; }
.carried .w { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; font-size: calc(12 * var(--u) + 3px); color: var(--a-ink-2); }
.carried .w b { font-size: calc(15 * var(--u) + 3px); color: var(--a-ink); }
.carried .a-btn { flex: none; padding: calc(6 * var(--u) + 3px) calc(14 * var(--u) + 4px); font-size: calc(14 * var(--u) + 3px); min-height: 40px; }
.warmchip {
  display: inline-flex; align-items: center; gap: 8px; align-self: flex-start;
  padding: 5px 12px 5px 9px; border-radius: 99px; font-weight: 600; font-size: calc(12 * var(--u) + 4px);
  background: color-mix(in srgb, #e8743b 20%, var(--a-surface)); color: var(--a-ink); margin-bottom: calc(8 * var(--u) + 3px);
}
.warmchip i { width: 10px; height: 10px; border-radius: 50%; background: #e8743b; box-shadow: 0 0 0 4px rgba(232, 116, 59, .25); }
.warmchip.cool { background: color-mix(in srgb, var(--a-accent) 14%, var(--a-surface)); }
.warmchip.cool i { background: var(--a-accent); box-shadow: 0 0 0 4px color-mix(in srgb, var(--a-accent) 25%, transparent); }
.warmchip.done i { background: var(--a-green); box-shadow: 0 0 0 4px color-mix(in srgb, var(--a-green) 25%, transparent); }
.warm-meters { margin: calc(10 * var(--u) + 3px) 0 calc(12 * var(--u) + 4px); }
.now-compact .warm-meters { margin-inline: auto; }
.now-compact .inline-actions { justify-content: center; }
.inline-actions .a-btn { flex: none; font-size: calc(16 * var(--u) + 4px); padding: calc(8 * var(--u) + 3px) calc(18 * var(--u) + 6px); min-height: 40px; }
.err { color: var(--a-red-text); font-size: 14px; margin: 0; }
.check { margin: calc(12 * var(--u) + 6px) 0 0; }
.check .a-btn { flex: none; height: calc(34 * var(--u) + 12px); font-size: calc(13 * var(--u) + 4px); padding: 0 calc(14 * var(--u) + 4px); border-radius: 14px; }
.now-compact .check { text-align: center; }
.now-compact.has-cam .check { text-align: left; }
.raw {
  margin: 12px 0 0;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
  color: var(--a-ink-3);
  white-space: pre-wrap;
  max-width: 70ch;
}
.waiting { align-items: center; justify-content: center; }

/* ---- off the panel (design/responsive/, B) ------------------------------------------------
   compact: the phone's Now tab; split: the laptop's Now column; stacked: the tablet's Now card.
   The hero (ring, glyph or camera) comes first, then the words, then temperatures and buttons. */
.now-compact, .now-split, .now-stacked { overflow-y: auto; }
.now-compact .body, .now-split .body { grid-template-columns: minmax(0, 1fr) !important; align-content: start; overflow: visible; container-type: normal; }
.now-compact .body > .ring, .now-compact .body > .glyph, .now-compact .body > .hero,
.now-split .body > .ring, .now-split .body > .glyph, .now-split .body > .hero { order: -1; justify-self: center; align-self: auto; margin: 0; }
.now-compact .ring { --size: min(64vw, 270px); }
.now-split .ring { --size: 270px; }
.now-compact .left { text-align: center; }
.now-compact .detail { max-width: none; margin-inline: auto; }
.now-compact .spools { display: flex; flex-direction: column; align-items: center; }
.now-compact.has-cam .left, .now-split .left { text-align: left; }
.now-compact.has-cam .spools { align-items: flex-start; }
.now-compact.has-cam .warm-meters { margin-inline: 0; }
.now-compact.has-cam .inline-actions { justify-content: flex-start; }
.now-compact .chip { max-width: 100%; }
.now-compact .steps { align-items: center; }
.now-compact.has-cam .steps { align-items: flex-start; }
.now-compact .actions, .now-split .actions { margin-top: auto; flex-direction: row; flex-wrap: wrap; }
.now-compact .actions .a-btn, .now-split .actions .a-btn { min-width: 140px; }
.now-compact .glyph, .now-split .glyph { --size: 120px; }
/* Ready: the Print tab sits right beside Now on wide screens and a tap away on phones, so no "Print again" card here */
.now-compact .hint, .now-split .hint, .now-stacked .hint { display: none; }
/* turning off (design/power/): the nozzle drawn in the ring; and the printer gone, on a phone */
.nozzle-glyph { display: block; width: 100%; height: 100%; fill: none; stroke: var(--a-ink-3); stroke-width: 1.5; stroke-linejoin: round; }
.now.gone { display: flex; align-items: center; justify-content: center; text-align: center; }
.gone-body { max-width: 420px; padding: 0 24px; display: flex; flex-direction: column; align-items: center; gap: 12px; }
.gone-glyph { width: 112px; height: 112px; padding: 26px; border-radius: 50%; background: var(--a-surface); fill: none; stroke: var(--a-ink-3); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.gone .headline { margin: 8px 0 0; }
.gone .detail { margin: 0; }
/* the phone: Up next under the spools instead of the panel's card (design/ready-phone/, C) */
.up-next { margin-top: 28px; }
.now-stacked.is-ready .left { grid-column: 1 / -1; }
.now-stacked.is-ready.has-cam .left { grid-column: 2; }
.tiles { flex: none; }
/* the setup card: 16 px from the phone's edges as drawn, so out past Now's own padding */
.setup { flex: none; margin: 12px calc(16px - (28 * var(--u) + 8px)) 0; }
.now-split .setup, .now-stacked .setup { margin: 8px 0 0; }
.now-stacked .setup { grid-column: 1 / -1; }
.now-compact .body, .now-split .body { flex: none; }
.now-split { padding: 18px 28px 26px; }
.now-compact { padding-top: 12px; }

/* tablet held upright: one card, hero on the left */
.now-stacked {
  flex: none;
  margin: 14px 28px 0;
  padding: 20px;
  border-radius: 22px;
  background: var(--a-surface);
  box-shadow: var(--a-card-shadow);
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
  column-gap: 26px;
  row-gap: 12px;
  overflow: visible;
}
.now-stacked .body { display: contents; }
.now-stacked .body > .ring, .now-stacked .body > .glyph, .now-stacked .body > .hero { grid-column: 1; grid-row: 1 / span 3; align-self: center; justify-self: center; margin: 0; }
.now-stacked .ring { --size: 240px; }
.now-stacked .glyph { --size: 140px; }
.now-stacked .left { grid-column: 2; }
.now-stacked .tiles, .now-stacked .actions, .now-stacked .err { grid-column: 2; }
.now-stacked .actions .a-btn { padding: 12px 16px; }

.headline > .inline-glyph { display: inline-grid; vertical-align: -0.12em; margin-right: 12px; --size: 1.1em; }
.hero { min-width: 0; }
.now { position: relative; }
.now-light { position: absolute; top: 12px; right: calc(28 * var(--u) + 8px); z-index: 2; }

/* Phone: stack */
@media (max-width: 640px) {
  .body.two, .body.ready { grid-template-columns: 1fr; align-content: start; }
  .ring { justify-self: start; }
  .glyph { justify-self: center; --size: calc(110 * var(--u) + 40px); }
  .hint { display: none; }
  .actions { flex-direction: column; }
  .detail { max-width: none; }
}
</style>
