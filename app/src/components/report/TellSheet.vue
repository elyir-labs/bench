<template>
  <!-- Tell Elyir something (design/report/, B): from Care, the three kinds; from a problem screen, straight to what goes
       with it, the moment filled in. On the printer nothing is typed: an idea shows a code that opens the form on a phone. -->
  <SliceSheet :open="open" :title="title" :sub="sub" wide @close="close">
    <div class="tell" :class="{ compact: isPanel }">
    <template v-if="step === 'kinds'">
      <div class="kinds" role="radiogroup" aria-label="What it's about">
        <button v-for="k in KINDS" :key="k.kind" class="kind" role="radio" :aria-checked="kind === k.kind"
                :class="{ on: kind === k.kind }" @click="kind = k.kind">
          <span class="dot" aria-hidden="true"><i v-if="kind === k.kind"></i></span>
          <span><b>{{ k.title }}</b><span class="line">{{ k.line }}</span></span>
        </button>
      </div>
      <div class="acts">
        <button class="a-btn ghost" @click="close">Not now</button>
        <button class="a-btn accent" @click="next">Next</button>
      </div>
    </template>

    <template v-else-if="step === 'review'">
      <div v-if="context" class="moment"><i aria-hidden="true"></i><span><b>{{ context.headline }}</b> {{ momentLine(context) }}</span></div>
      <ul v-if="!(isPanel && showFiles)" class="goes">
        <li v-for="g in goesWith(context)" :key="g.title"><Tick /><span><b>{{ g.title }}</b> {{ g.line }}</span></li>
      </ul>
      <template v-if="!isPanel">
        <label class="field">A few words, if you like<textarea v-model="note" rows="2" maxlength="4000" placeholder="What were you doing when it happened?"></textarea></label>
        <label class="field">Where we can answer<input v-model="email" type="email" autocomplete="email" placeholder="you@example.net"></label>
      </template>
      <button class="link" @click="toggleFiles">{{ showFiles ? 'Hide the list' : 'See everything first' }}</button>
      <ul v-if="showFiles" class="files">
        <li v-if="files === null">Gathering…</li>
        <li v-else-if="!files.length">The printer couldn't list it just now.</li>
        <li v-for="f in files ?? []" :key="f">{{ f }}</li>
        <li v-if="files?.length && bytes" class="tiny">{{ Math.max(1, Math.round(bytes / 1024)) }} KB, passwords, keys and Wi-Fi details taken out</li>
      </ul>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <div class="acts">
        <button class="a-btn ghost" :disabled="sending" @click="close">Not now</button>
        <button class="a-btn accent" :disabled="sending" @click="send">{{ sending ? 'Sending…' : 'Send' }}</button>
      </div>
    </template>

    <template v-else-if="step === 'qr'">
      <div class="qr-row">
        <div class="qr"><QrCode :value="writeAt" label="The form, on your phone" /></div>
        <p class="qr-words">Point your phone's camera here. It opens a form with {{ printer.name || 'this printer' }} already chosen.
          <span class="tiny">Or from a computer: bench.elyir.com/write, or reply to your invite at testers@elyir.dev.</span></p>
      </div>
      <div class="acts one"><button class="a-btn ghost" @click="close">Done</button></div>
    </template>

    <template v-else-if="step === 'write'">
      <label class="field">{{ kind === 'idea' ? 'Your idea or request' : 'What you want to say' }}<textarea v-model="note" rows="4" maxlength="4000" required></textarea></label>
      <label class="switch-row"><span><b>Add {{ printer.name || "this printer" }}'s details</b><span class="line">Release, board, logs and settings. Off unless you want them.</span></span>
        <input v-model="details" type="checkbox" role="switch"></label>
      <label class="field">Where we can answer<input v-model="email" type="email" autocomplete="email" placeholder="you@example.net"></label>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <div class="acts">
        <button class="a-btn ghost" :disabled="sending" @click="close">Not now</button>
        <button class="a-btn accent" :disabled="sending || !note.trim()" @click="send">{{ sending ? 'Sending…' : 'Send to Elyir' }}</button>
      </div>
    </template>

    <template v-else-if="step === 'sent'">
      <div class="sent">
        <span class="ok" aria-hidden="true"><Tick /></span>
        <p>If you write to us, give this number:</p>
        <b class="code a-num">{{ code }}</b>
        <p class="tiny">Only Elyir can read it, and it's deleted after 90 days.</p>
      </div>
      <div class="acts one"><button class="a-btn ghost" @click="close">Done</button></div>
    </template>
    </div>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import QrCode from '@/components/door/QrCode.vue'
import { isPanel } from '@/theme'
import { KINDS, goesWith, momentLine, writeUrl, type ReportContext, type ReportKind, type ReportPrinter } from '@/report/words'
import { previewReport, sendReport } from '@/report/api'

const props = defineProps<{ open: boolean; context?: ReportContext | null; printerName?: string }>()
const emit = defineEmits<{ close: [] }>()

type Step = 'kinds' | 'review' | 'qr' | 'write' | 'sent'
const step = ref<Step>('kinds')
const kind = ref<ReportKind>('wrong')
const note = ref('')
const email = ref('')
const details = ref(false)
const sending = ref(false)
const error = ref<string | null>(null)
const code = ref('')
const showFiles = ref(false)
const files = ref<string[] | null>(null)
const bytes = ref(0)
const printer = ref<ReportPrinter>({})
const context = computed(() => props.context ?? null)

watch(() => props.open, (open) => {
  if (!open) return
  printer.value = { name: props.printerName }
  step.value = context.value ? 'review' : 'kinds'
  kind.value = 'wrong'
  note.value = ''; details.value = false; error.value = null; code.value = ''
  showFiles.value = false; files.value = null; bytes.value = 0
})

const title = computed(() => step.value === 'sent' ? 'Sent to Elyir.'
  : step.value === 'qr' ? 'Write it on your phone'
  : context.value ? 'Tell Elyir about this'
  : step.value === 'write' ? KINDS.find((k) => k.kind === kind.value)!.title
  : 'Tell Elyir something')
const sub = computed(() => step.value === 'kinds' ? 'Something wrong, an idea, a request: it all reaches the people who make Elyir Bench.'
  : step.value === 'review' ? 'Nothing goes until you tap Send.' : undefined)
const writeAt = computed(() => writeUrl(kind.value, printer.value))

async function next() {
  if (kind.value === 'wrong') { step.value = 'review'; return }
  if (!isPanel) { step.value = 'write'; return }
  step.value = 'qr'
  const p = await previewReport(kind.value)        // the release and board go into the code, so the message says which
  if (p?.printer) printer.value = { ...printer.value, ...p.printer }
}

async function toggleFiles() {
  showFiles.value = !showFiles.value
  if (showFiles.value && files.value === null) {
    const p = await previewReport('wrong')
    files.value = p?.files ?? []
    bytes.value = p?.bundle_bytes ?? 0
  }
}

async function send() {
  sending.value = true
  error.value = null
  try {
    code.value = await sendReport({ kind: kind.value, note: note.value.trim() || undefined, email: email.value.trim() || undefined,
      details: kind.value === 'wrong' || details.value, context: context.value })
    step.value = 'sent'
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    sending.value = false
  }
}

function close() { emit('close') }

const Tick = () => h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2.6, 'stroke-linecap': 'round',
  'stroke-linejoin': 'round', 'aria-hidden': 'true' }, [h('path', { d: 'M5 12.5l4.5 4.5L19 7.5' })])
</script>

<style scoped>
.kinds { display: grid; gap: 10px; margin-bottom: 14px; }
.kind { appearance: none; font: inherit; text-align: left; color: var(--a-ink); display: flex; gap: 14px; align-items: center; cursor: pointer;
  padding: 14px 18px; border-radius: 18px; border: 0; background: var(--a-surface); box-shadow: var(--a-card-shadow); }
.kind.on { box-shadow: 0 0 0 2px var(--a-accent); }
.kind b { display: block; font-size: 18px; }
.line { display: block; color: var(--a-ink-3); font-size: 14.5px; margin-top: 2px; }
.dot { width: 22px; height: 22px; flex: none; border-radius: 50%; border: 2px solid var(--a-line); display: grid; place-items: center; }
.kind.on .dot { border-color: var(--a-accent); }
.dot i { width: 10px; height: 10px; border-radius: 50%; background: var(--a-accent); }
.moment { display: flex; gap: 12px; align-items: center; padding: 12px 16px; border-radius: 16px; background: var(--a-surface);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--a-red) 35%, transparent); margin-bottom: 10px; font-size: 16px; color: var(--a-ink-3); }
.moment i { width: 12px; height: 12px; border-radius: 50%; background: var(--a-red); flex: none; }
.moment b { color: var(--a-ink); }
.goes { list-style: none; margin: 0 0 10px; padding: 0; border-radius: 16px; background: var(--a-surface); box-shadow: var(--a-card-shadow); }
.goes li { display: flex; gap: 12px; align-items: flex-start; padding: 10px 16px; border-top: 1px solid var(--a-line); font-size: 15px; color: var(--a-ink-2); }
.goes li:first-child { border-top: 0; }
.goes svg { width: 18px; height: 18px; flex: none; color: var(--a-green); margin-top: 1px; }
.goes b { color: var(--a-ink); }
.field { display: grid; gap: 6px; margin: 0 0 12px; font-size: 14px; font-weight: 600; color: var(--a-ink-3); }
.field textarea, .field input { font: inherit; font-size: 16px; font-weight: 400; color: var(--a-ink); background: var(--a-surface); border: 1px solid var(--a-line);
  border-radius: 14px; padding: 12px 14px; resize: vertical; }
.switch-row { display: flex; gap: 14px; align-items: center; justify-content: space-between; padding: 12px 16px; margin: 0 0 12px;
  border-radius: 16px; background: var(--a-surface); }
.switch-row b { font-size: 16px; }
.switch-row input { width: 22px; height: 22px; flex: none; }
.link { appearance: none; border: 0; background: none; padding: 4px 0 10px; font: inherit; font-weight: 650; color: var(--a-accent-text); cursor: pointer; }
.files { list-style: none; margin: 0 0 12px; padding: 10px 14px; border-radius: 14px; background: var(--a-surface); font: 13px/1.6 ui-monospace, 'SF Mono', Menlo, monospace; color: var(--a-ink-2); }
.tiny { display: block; color: var(--a-ink-3); font-size: 13px; font-family: inherit; margin-top: 6px; }
.err { margin: 0 0 12px; font-size: 14px; color: var(--a-red-text, #c0392b); }
.acts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.acts.one { grid-template-columns: 1fr; }
.acts .a-btn { height: 54px; font-size: 18px; border-radius: 18px; }
.qr-row { display: flex; gap: 22px; align-items: center; margin-bottom: 14px; }
.qr { flex: none; width: min(200px, 40vh); }
.qr-words { margin: 0; font-size: 17px; line-height: 1.4; color: var(--a-ink-2); }
.sent { display: grid; justify-items: center; text-align: center; gap: 8px; margin-bottom: 16px; }
.sent p { margin: 0; color: var(--a-ink-2); font-size: 17px; }
.ok { width: 56px; height: 56px; border-radius: 50%; display: grid; place-items: center; color: var(--a-green-text, #0f7a44);
  background: color-mix(in srgb, var(--a-green) 18%, transparent); }
.ok svg { width: 30px; height: 30px; }
.code { font-size: 40px; letter-spacing: .06em; color: var(--a-ink); }
@media (max-width: 520px) { .qr-row { flex-direction: column; } }
.files { max-height: 140px; overflow: auto; }
/* the printer's screen is 480 tall: the same sheet, tighter, so Send never falls off the bottom */
.compact .kinds { gap: 8px; margin-bottom: 10px; }
.compact .kind { padding: 10px 16px; }
.compact .kind b { font-size: 17px; }
.compact .moment { padding: 8px 14px; font-size: 15px; margin-bottom: 8px; }
.compact .goes li { padding: 6px 14px; font-size: 14px; }
.compact .goes svg { width: 16px; height: 16px; }
.compact .link { padding: 0 0 8px; }
.compact .files { max-height: 96px; }
.compact .acts .a-btn { height: 48px; font-size: 17px; }
</style>
