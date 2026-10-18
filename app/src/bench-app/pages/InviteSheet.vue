<template>
  <!-- Invite someone (design/bench-remote/, C-phone-invite): Watch by default, for a week; one link, once. A phone
       shares it with its own share sheet; a screen without one (the box) shows it to scan or copy. -->
  <SliceSheet :open="open" :title="made ? 'Send them this link' : INVITE.title" :sub="made ? madeSub : INVITE.sub" @close="close">
    <template v-if="!made">
      <p class="label">{{ INVITE.can }}</p>
      <div class="reach" role="radiogroup" :aria-label="INVITE.can">
        <button v-for="r in REACHES" :key="r" role="radio" :aria-checked="reach === r" class="opt" :class="{ on: reach === r }" @click="reach = r">
          <span class="t"><b>{{ REACH_WORDS[r].label }}</b><span>{{ REACH_WORDS[r].line }}</span></span>
          <span class="mark" aria-hidden="true"><svg v-if="reach === r" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg></span>
        </button>
      </div>
      <p class="label">{{ INVITE.long }}</p>
      <div class="seg" role="radiogroup" :aria-label="INVITE.long">
        <button v-for="l in LASTS" :key="l" role="radio" :aria-checked="lasts === l" :class="{ on: lasts === l }" @click="lasts = l">{{ LASTS_WORDS[l] }}</button>
      </div>
      <label v-if="!here.away" class="from"><span>From</span><input v-model="from" maxlength="40" placeholder="Your name, so they know who it's from" /></label>
      <button class="a-btn accent go" :disabled="busy" @click="make">{{ busy ? 'Making the link…' : INVITE.go }}</button>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <p class="foot">{{ INVITE.foot }}</p>
    </template>
    <template v-else>
      <div class="made">
        <div class="code-box"><QrCode :value="made.url" label="The invite link" /></div>
        <div class="link">
          <code>{{ made.url }}</code>
          <div class="btns">
            <button class="a-btn accent" @click="copy">{{ copied ? 'Copied' : 'Copy the link' }}</button>
            <button class="a-btn ghost" @click="close">Done</button>
          </div>
        </div>
      </div>
    </template>
  </SliceSheet>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SliceSheet from '@/components/slice/SliceSheet.vue'
import QrCode from '@/components/door/QrCode.vue'
import { INVITE, INVITE_DEFAULT, LASTS_WORDS, REACH_WORDS, dayLong, shareText, type Lasts, type Reach } from '../away'
import { cancelInvite, here, invite, type MadeInvite } from '../here'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; made: [] }>()
const REACHES: Reach[] = ['watch', 'step_in']
const LASTS: Lasts[] = ['day', 'week', 'removed']
const FROM = 'bench.inviteFrom'

const reach = ref<Reach>(INVITE_DEFAULT.reach)
const lasts = ref<Lasts>(INVITE_DEFAULT.lasts)
const from = ref(read())
const busy = ref(false)
const error = ref('')
const made = ref<MadeInvite | null>(null)
const copied = ref(false)
const madeSub = computed(() => made.value
  ? `${here.away ? 'Copy it and send it to them' : 'Scan it with your phone to send it on, or copy it'}. It works once; if nobody opens it, it stops working ${dayLong(made.value.expires, new Date())}.` : '')

watch(() => props.open, (o) => {
  if (!o) return
  reach.value = INVITE_DEFAULT.reach
  lasts.value = INVITE_DEFAULT.lasts
  error.value = ''
  made.value = null
  copied.value = false
})

function read(): string {
  try { return localStorage.getItem(FROM) ?? '' } catch { return '' }
}

async function make() {
  busy.value = true
  error.value = ''
  try {
    const by = from.value.trim()
    if (!here.away) { try { localStorage.setItem(FROM, by) } catch { /* private window */ } }
    const inv = await invite(reach.value, lasts.value, here.away ? undefined : by || undefined)
    emit('made')
    if (navigator.share) {
      try {
        await navigator.share({ title: 'Elyir Bench', text: shareText(reach.value, here.away ? here.name : by || null), url: inv.url })
        close()
      } catch (e) {
        // not sent anywhere: the link would only wait out its day, so it goes now
        if ((e as Error).name === 'AbortError') { await cancelOwn(inv.id); emit('made') } else made.value = inv
      }
      return
    }
    made.value = inv
  } catch (e) {
    const err = e as Error & { detail?: string }
    error.value = err.detail === 'off' ? "The Bench Box isn't reachable from outside yet: turn on From away in its Care first." : err.message
  } finally {
    busy.value = false
  }
}

async function cancelOwn(id: string) {
  if (here.away) await fetch(`/door/invites/${encodeURIComponent(id)}`, { method: 'DELETE', credentials: 'include' }).catch(() => undefined)
  else await cancelInvite(id).catch(() => undefined)
}

async function copy() {
  if (!made.value) return
  try {
    await navigator.clipboard.writeText(made.value.url)
    copied.value = true
  } catch {
    error.value = 'Copying isn’t possible here: scan the code instead.'
  }
}

function close() { emit('close') }
</script>

<style scoped>
.label { margin: 18px 0 8px; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.reach { display: grid; gap: 10px; }
.opt { appearance: none; font: inherit; color: inherit; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 14px;
       padding: 14px 16px; border-radius: 16px; background: var(--a-surface); border: 1.5px solid var(--a-line); }
.opt.on { border-color: var(--a-accent); box-shadow: 0 0 0 1px var(--a-accent); }
.opt .t { flex: 1; display: grid; gap: 2px; }
.opt b { font-size: 17px; } .opt .t span { color: var(--a-ink-3); font-size: 14.5px; line-height: 1.35; }
.mark { width: 24px; height: 24px; flex: none; border-radius: 50%; border: 1.5px solid var(--a-line); display: grid; place-items: center; }
.opt.on .mark { border: 0; }
.mark svg { width: 24px; height: 24px; fill: none; stroke: var(--a-accent); stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.seg { display: grid; grid-template-columns: repeat(3, 1fr); background: var(--a-surface-2); border-radius: 999px; padding: 4px; }
.seg button { appearance: none; border: 0; background: none; font: inherit; padding: 10px 6px; border-radius: 999px; font-size: 15.5px; font-weight: 650; color: var(--a-ink-2); cursor: pointer; white-space: nowrap; }
.seg button.on { background: var(--a-surface); color: var(--a-ink); box-shadow: var(--a-card-shadow); }
.from { display: grid; gap: 6px; margin-top: 16px; font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); }
.from input { font: inherit; font-size: 17px; font-weight: 500; letter-spacing: 0; text-transform: none; color: var(--a-ink); background: var(--a-surface);
              border: 1px solid var(--a-line); border-radius: 14px; padding: 12px 14px; outline: none; }
.from input:focus { border-color: var(--a-accent); }
.go { width: 100%; height: 54px; margin-top: 22px; border-radius: 999px; font-size: 18px; font-weight: 650; }
.err { margin: 10px 0 0; color: var(--a-red-text); font-size: 15px; }
.foot { margin: 14px 0 0; color: var(--a-ink-3); font-size: 14px; text-align: center; line-height: 1.4; }
.made { display: flex; gap: 22px; align-items: center; }
.code-box { flex: none; width: 210px; }
.link { flex: 1; min-width: 0; display: grid; gap: 14px; }
.link code { font-size: 14px; color: var(--a-ink-2); background: var(--a-surface); border-radius: 12px; padding: 10px 12px; overflow-wrap: anywhere; }
.btns { display: flex; gap: 10px; }
.btns .a-btn { height: 50px; padding: 0 22px; border-radius: 999px; font-size: 17px; }
@media (max-width: 560px) { .made { flex-direction: column; align-items: stretch; } .code-box { width: 200px; align-self: center; } }
</style>
