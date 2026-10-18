<template>
  <!-- You (design/one-cloud/, A): the Elyir account, the house's Bench Cloud plan, each printer from away and its backup,
       the phones and computers signed in. cloud.elyir.dev sends people here. -->
  <main class="you-page" :class="{ stale: account.me && !account.fresh }">
    <!-- design/loading/, B + A: last time's account while it checks; its buttons wait until Bench Cloud has answered -->
    <div v-if="account.checking && account.me" class="a-topline" role="progressbar" aria-label="Checking your account"></div>
    <router-link to="/" class="back">‹ Printers</router-link>
    <p v-if="account.me && !account.fresh && account.error && !account.checking" class="a-stale-note" role="status">
      Couldn't check just now · <button @click="refreshAccount">Try again</button></p>

    <!-- signed out: Sign in with Elyir goes straight to account.elyir.com (design/account/, A); an invite says it's one -->
    <section v-if="account.state === 'out'" class="stack">
      <template v-if="inviteToken">
        <h1 class="a-display">{{ INVITED_TITLE }}</h1>
        <p class="sub">{{ INVITED_LINE }}</p>
      </template>
      <p v-else-if="!error" class="hint">{{ GOING }}</p>
      <button class="a-btn big elyir" :disabled="busy" @click="signIn"><span class="mark" aria-hidden="true">e</span>{{ SIGN_IN_ELYIR }}</button>
      <p v-if="error" class="err">{{ error }}</p>
    </section>

    <!-- nothing remembered (a first visit, or over a week ago): the page's shape, with what this phone knows -->
    <section v-else-if="account.state === 'checking'" class="shape" aria-busy="true" aria-label="Checking your account">
      <span class="list acct"><span class="row">
        <span class="av" aria-hidden="true">{{ initial(account.owner?.email) }}</span>
        <span class="t"><b>{{ account.owner?.email }}</b><small>{{ ACCOUNT_ROW }}</small></span>
      </span></span>
      <h2 class="lbl">Plan</h2>
      <div class="list"><div class="row"><span class="t"><i class="a-sk" style="width: 130px; height: 17px"></i><i class="a-sk" style="width: 170px; height: 13px"></i></span></div></div>
      <h2 class="lbl">Your printers</h2>
      <div class="list">
        <div v-for="(n, i) in shapeNames" :key="i" class="row">
          <span class="t"><b v-if="n">{{ n }}</b><i v-else class="a-sk" style="width: 90px; height: 17px"></i>
            <i class="a-sk" :style="{ width: [210, 170, 230][i % 3] + 'px', height: '13px' }"></i></span>
        </div>
      </div>
      <h2 class="lbl">Owners</h2>
      <div class="list"><div class="row"><span class="t"><i class="a-sk" style="width: 190px; height: 17px"></i><i class="a-sk" style="width: 40px; height: 13px"></i></span></div></div>
    </section>
    <section v-else-if="account.state === 'error'" class="stack">
      <p class="err">{{ account.error }}</p>
      <button class="a-btn ghost" @click="refreshAccount">Try again</button>
    </section>

    <template v-else>
      <!-- the Elyir account itself lives at account.elyir.com: sign-in, payments, phones and computers -->
      <a class="list acct" :href="ACCOUNT_URL">
        <span class="row">
          <span class="av" aria-hidden="true">{{ initial(account.owner?.email) }}</span>
          <span class="t"><b>{{ account.owner?.email }}</b><small>{{ ACCOUNT_ROW }}</small></span>
          <span class="chev" aria-hidden="true">›</span>
        </span>
      </a>

      <!-- an owner invite, opened from its email (design/account/, A-accept) -->
      <section v-if="invite" class="card accept">
        <template v-if="invite.for_you">
          <h2 class="a-display">{{ acceptTitle(invite.inviter) }}</h2>
          <p class="sub">{{ acceptLine(invite) }}</p>
          <button class="a-btn accent" :disabled="busy" @click="acceptIt">Accept</button>
          <button class="a-btn ghost" :disabled="busy" @click="declineIt">Not me</button>
        </template>
        <p v-else class="sub">{{ notForYou(invite) }}</p>
      </section>
      <p v-if="joined" class="hint paid">{{ joined }}</p>

      <!-- signed in, no house yet: the plan, paid for (Stripe) or turned on with a tester invite -->
      <section v-if="account.state === 'no-house' && !invite" class="stack nohouse">
        <div class="card pitch">
          <h2 class="a-display">{{ PLAN_TITLE }}</h2>
          <p class="sub">{{ PLAN_SUB }}</p>
          <CloudGets lines />
          <PlanPicker />
          <p class="hint">{{ ALERTS_FREE }}</p>
        </div>
      </section>

      <template v-else-if="me">
        <p v-if="paidWait" class="hint paid">{{ paidWait }}</p>
        <h2 class="lbl">Plan</h2>
        <!-- never on: one card, the plan and how to turn it on; on, or paid before: the plan's own row -->
        <div v-if="me.plan.on || me.plan.manage || paidWait" class="list">
          <div class="row">
            <span class="t"><b class="plan">{{ planTitle(me.plan) }} <span class="chip" :class="{ on: me.plan.on }">{{ me.plan.on ? 'On' : 'Off' }}</span></b>
              <small>{{ planLine(me.plan, account.pay) }}</small></span>
            <button v-if="me.plan.manage && account.pay" class="act" :disabled="busy" @click="manageIt">{{ MANAGE }}</button>
          </div>
        </div>
        <template v-if="me.plan.on && sizeLine(me)">
          <p class="size"><b>{{ sizeLine(me) }}</b><template v-if="!isOver(me)"> · {{ SIZE_HINT }}</template></p>
          <div class="meter" aria-hidden="true">
            <i v-for="i in Math.max(me.printers ?? 0, me.plan.covers!)" :key="i"
               :class="{ used: i <= Math.min(me.printers ?? 0, me.plan.covers!), over: i > me.plan.covers! }"></i>
          </div>
          <div v-if="isOver(me)" class="card workshop">
            <b>{{ WORKSHOP_TITLE }}</b>
            <p class="sub small">{{ workshopLine(me.printers ?? 0, me.plan.covers!) }}</p>
            <p v-if="me.house?.workshop_asked" class="hint">{{ TOLD }}</p>
            <button v-else class="link" :disabled="busy" @click="tellMe">{{ TELL_ME }}</button>
          </div>
        </template>
        <div v-if="!me.plan.on && !paidWait" class="card pitch">
          <template v-if="!me.plan.manage">
            <b class="plan">Bench Cloud <span class="chip">Off</span></b>
            <p class="sub small">{{ PLAN_OFF }}</p>
          </template>
          <CloudGets lines />
          <PlanPicker />
        </div>

        <h2 class="lbl">Your printers</h2>
        <div class="list">
          <div v-for="d in me.devices" :key="d.id" class="row">
            <span class="t"><b>{{ d.kind === 'box' ? 'Bench Box' : d.name }}</b><small>{{ deviceLine(d, me.plan, now) }}</small></span>
            <button v-if="d.backup" class="act" :disabled="busy" @click="download(d)">Download</button>
          </div>
          <div v-for="p in notIn" :key="p.id" class="row">
            <span class="t"><b>{{ p.name }}</b><small>{{ notInLine(p.reach === 'home') }}</small></span>
            <button v-if="p.reach === 'home' && p.base" class="act" :disabled="busy" @click="add(p)">Add</button>
          </div>
          <p v-if="!me.devices.length && !notIn.length" class="row hint">No printers yet. Add one from Printers, at home.</p>
        </div>

        <h2 class="lbl">Owners</h2>
        <div class="list">
          <div v-for="o in me.owners" :key="o.email" class="row">
            <span class="t"><b>{{ o.email }}</b><small>{{ ownerLine(o.you, me.owners.length) }}</small></span>
            <button v-if="!o.you && o.id" class="act" :disabled="busy" @click="takeOff(o.id, o.email)">Remove</button>
          </div>
          <div v-for="i in me.invites ?? []" :key="i.id" class="row">
            <span class="t"><b class="waiting">{{ i.email }}</b><small>{{ inviteLine(i, now) }}</small></span>
            <button class="act" :disabled="busy" @click="cancelIt(i.id)">Cancel</button>
          </div>
          <form v-if="adding" class="row add" @submit.prevent="addIt">
            <label class="field grow"><span>{{ SECOND_EMAIL }}</span>
              <input v-model="ownerEmail" type="email" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="name@example.net" /></label>
            <span class="pair">
              <button type="button" class="a-btn ghost" @click="adding = false">{{ CANCEL }}</button>
              <button class="a-btn accent" :disabled="busy || !validEmail(ownerEmail)">{{ busy ? '…' : SECOND_GO }}</button>
            </span>
          </form>
          <button v-else class="row addrow" @click="adding = true; added = null">
            <span class="t"><b>{{ me.owners.length === 1 ? SECOND_ADD : ANOTHER_ADD }}</b><small>{{ OWNER_ADD_LINE }}</small></span>
            <span class="chev" aria-hidden="true">+</span>
          </button>
        </div>
        <p v-if="added" class="hint ways-note">{{ invitedNote(added) }}</p>
        <p v-if="error" class="err">{{ error }}</p>
      </template>

    </template>

    <template v-if="printers.length">
      <h2 class="lbl">This {{ kind }}</h2>
      <NotificationsSetting />
    </template>
    <button v-if="account.state === 'in' || account.state === 'no-house'" class="a-btn ghost out" @click="leave">Sign out of this {{ kind }}</button>

  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CANCEL, SECOND_ADD, SECOND_EMAIL, SECOND_GO, validEmail } from '@/cloud'
import { ACCOUNT_URL, finishSignIn, signInUrl } from '../signin'
import { printers, type LivePrinter } from '../printers'
import { useRoute, useRouter } from 'vue-router'
import {
  account, acceptInvite, addOwner, addPrinter, api, askWorkshop, cancelInvite, declineInvite, getInvite, removeOwner, downloadBackup, loadPay, manage, refreshAccount, removePhone, setOwner, signOut,
} from '../account'
import {
  ALERTS_FREE, MANAGE, PAID_SLOW, PAID_WAIT, PLAN_SUB, PLAN_TITLE, deviceLine, initial, notInLine, planLine, type CloudDevice,
  ANOTHER_ADD, PLAN_OFF, SIZE_HINT, removeOwnerAsk, ownerLine, TELL_ME, TOLD, WORKSHOP_TITLE, isOver, planTitle, sizeLine, workshopLine,
  ACCOUNT_ROW, GOING, INVITED_LINE, INVITED_TITLE, OWNER_ADD_LINE, SIGN_IN_ELYIR, acceptLine, acceptTitle, inviteLine, invitedNote,
  notForYou, type OwnerInvite,
} from '../you'
import CloudGets from '../CloudGets.vue'
import PlanPicker from '../PlanPicker.vue'
import NotificationsSetting from '../NotificationsSetting.vue'

const kind = matchMedia('(pointer: coarse)').matches ? 'phone' : 'computer'
const me = computed(() => account.me)
const now = ref(Date.now())
const notIn = computed(() => {
  const named = new Set((me.value?.devices ?? []).map((d) => d.name.toLowerCase()))
  return printers.filter((p) => !named.has(p.name.toLowerCase()))
})

const shapeNames = computed(() => (printers.length ? printers.map((p) => p.name) : [null, null]))

const busy = ref(false)
const error = ref<string | null>(null)

async function doing(fn: () => Promise<void>): Promise<void> {
  busy.value = true
  error.value = null
  try {
    await fn()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

// ---- Sign in with Elyir (design/account/, A) ----
const tab = (() => { try { return window.sessionStorage } catch { return null } })()
const INVITE = 'elyir.invite'
const route = useRoute(), router = useRouter()
const inviteToken = ref<string | null>(typeof route.query.accept === 'string' ? route.query.accept : (() => {
  try { return tab?.getItem(INVITE) ?? null } catch { return null } })())
if (inviteToken.value) { try { tab?.setItem(INVITE, inviteToken.value) } catch { /* kept in the address instead */ } }
const invite = ref<OwnerInvite | null>(null)
const joined = ref<string | null>(null)

const signIn = () => doing(async () => {
  const back = `${location.origin}/you${inviteToken.value ? `?accept=${encodeURIComponent(inviteToken.value)}` : ''}`
  location.href = await signInUrl(back, tab)
})
/** Signing out of the Printers app only: back to the list, not straight back in through the account. */
async function leave(): Promise<void> {
  await signOut()
  router.push('/')
}
async function backFromAccount(): Promise<boolean> {
  const code = route.query.elyir_code
  if (typeof code !== 'string') return false
  router.replace('/you')
  await doing(async () => { setOwner(await finishSignIn(api, code, tab)) })
  return true
}
function dropInvite(): void {
  inviteToken.value = null
  invite.value = null
  try { tab?.removeItem(INVITE) } catch { /* nothing kept */ }
}
async function loadInvite(): Promise<void> {
  if (!inviteToken.value || !account.owner) return
  try { invite.value = await getInvite(inviteToken.value) } catch (e) { error.value = (e as Error).message; dropInvite() }
}
const acceptIt = () => doing(async () => {
  const from = invite.value!.inviter
  await acceptInvite(inviteToken.value!)
  dropInvite()
  joined.value = `You're an owner of ${from}'s printers now.`
})
const declineIt = () => doing(async () => { await declineInvite(inviteToken.value!); dropInvite() })
const cancelIt = (id: string) => doing(() => cancelInvite(id))

const manageIt = () => doing(() => manage())
const tellMe = () => doing(() => askWorkshop())

// a second owner, by email: they sign in themselves (the same as a printer's Bench Cloud card)
const adding = ref(false)
const ownerEmail = ref('')
const added = ref<string | null>(null)
const addIt = () => doing(async () => {
  const e = ownerEmail.value.trim()
  await addOwner(e)
  added.value = e
  ownerEmail.value = ''
  adding.value = false
})
const takeOff = (id: string, email: string) => doing(async () => {
  if (!confirm(removeOwnerAsk(email))) return
  await removeOwner(id)
  added.value = null
})

// back from Stripe (?paid=1): the plan goes on once Stripe tells Bench Cloud, usually within seconds
const paidWait = ref<string | null>(null)
async function waitForPaid(): Promise<void> {
  if (route.query.paid !== '1') return
  paidWait.value = PAID_WAIT
  for (let i = 0; i < 20 && !account.me?.plan.on; i++) {
    await new Promise((r) => setTimeout(r, 3000))
    await refreshAccount()
  }
  paidWait.value = account.me?.plan.on ? null : PAID_SLOW
  router.replace('/you')
}
const add = (p: LivePrinter) => doing(() => addPrinter(p.base!, p.token, p.name))
const download = (d: CloudDevice) => doing(() => downloadBackup(d))
const remove = (id: string) => doing(() => removePhone(id))

let timer = 0
onMounted(async () => {
  loadPay()
  const back = await backFromAccount()
  await refreshAccount()
  // signed out and not mid-invite: no screen of our own, straight to the account (it comes back at once if signed in)
  if (account.state === 'out' && !back && !inviteToken.value && !error.value) signIn()
  await loadInvite()
  waitForPaid()
  timer = window.setInterval(() => { now.value = Date.now() }, 60_000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<style scoped>
.you-page {
  min-height: 100dvh; box-sizing: border-box; max-width: 640px; margin: 0 auto;
  padding: calc(18px + env(safe-area-inset-top, 0px)) 20px calc(28px + env(safe-area-inset-bottom, 0px));
  background: var(--a-bg); color: var(--a-ink); font-family: var(--a-font);
  display: flex; flex-direction: column;
}
.back { align-self: flex-start; color: var(--a-accent-text); text-decoration: none; font-weight: 600; font-size: 16px; margin-bottom: 14px; }
.stack { display: flex; flex-direction: column; gap: 14px; }
h1 { font-size: 30px; margin: 0; }
h2.a-display { font-size: 24px; margin: 0; }
.sub { color: var(--a-ink-2); font-size: 17px; line-height: 1.45; margin: 0; }
.hint { color: var(--a-ink-3); font-size: 15px; line-height: 1.4; margin: 0; }
.err { color: var(--a-red-text); font-size: 16px; margin: 0; }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 14px; font-weight: 600; color: var(--a-ink-3); }
input {
  font: inherit; font-size: 18px; font-weight: 500; color: var(--a-ink);
  background: var(--a-surface); border: 1px solid var(--a-line); border-radius: 14px;
  padding: 14px 16px; outline: none; user-select: text; -webkit-user-select: text;
}
input:focus { border-color: var(--a-accent); }
.pitch input { background: var(--a-bg); }
.code { font-size: 22px; font-weight: 700; letter-spacing: 0.2em; }
.paid { margin: 14px 4px 0; color: var(--a-green-text); font-weight: 600; }
.link { appearance: none; background: none; border: 0; padding: 4px 0; font: inherit; font-size: 16px; font-weight: 600; color: var(--a-accent-text); cursor: pointer; align-self: flex-start; }
.card { background: var(--a-surface); border-radius: 20px; box-shadow: var(--a-card-shadow); padding: 18px; display: flex; flex-direction: column; gap: 14px; }
.pitch { margin-top: 8px; }
.pitch > .plan { font-size: 17px; font-weight: 650; }
.pitch > .small { margin-top: -8px; }
.nohouse { margin-top: 12px; }
.lbl { font-size: 12px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--a-ink-3); margin: 22px 4px 8px; }
.pitch .lbl { margin: 0; }
.who { display: flex; align-items: center; gap: 14px; margin: 2px 4px 0; }
.av { width: 52px; height: 52px; border-radius: 50%; flex: none; display: grid; place-items: center; font-weight: 750; font-size: 22px;
  color: var(--a-accent); background: color-mix(in srgb, var(--a-accent) 14%, transparent); }
.t { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.t b { font-size: 17px; font-weight: 650; overflow-wrap: anywhere; }
.who .t b { font-size: 20px; }
.t small { font-size: 14px; color: var(--a-ink-3); line-height: 1.35; }
.list { background: var(--a-surface); border-radius: 20px; box-shadow: var(--a-card-shadow); overflow: hidden; }
.row { display: flex; align-items: center; gap: 12px; padding: 13px 16px; border-top: 1px solid var(--a-line); margin: 0; }
.row:first-child { border-top: 0; }
.act { appearance: none; background: none; border: 0; padding: 8px 0 8px 8px; font: inherit; font-size: 15px; font-weight: 650; color: var(--a-accent-text); cursor: pointer; white-space: nowrap; }
.act[disabled] { opacity: .5; }
.plan { display: flex; align-items: center; gap: 10px; }
.chip { font-size: 13px; font-weight: 650; padding: 2px 10px; border-radius: 99px; background: var(--a-surface-2); color: var(--a-ink-2); }
.chip.on { background: color-mix(in srgb, var(--a-green) 18%, transparent); color: var(--a-green-text); }
.out { margin-top: 26px; flex: none; }
.big { min-height: 54px; display: inline-flex; align-items: center; justify-content: center; gap: 10px; }
.elyir { background: #111827; color: #fff; border-color: transparent; }
.elyir .mark { width: 24px; height: 24px; border-radius: 7px; background: #fff; color: #111827; display: grid; place-items: center;
  font-weight: 800; font-size: 14px; }
.acct { display: block; text-decoration: none; color: inherit; margin-top: 2px; }
.acct .av { width: 40px; height: 40px; font-size: 17px; }
.acct .chev { color: var(--a-ink-3); font-size: 22px; }
.accept { margin-top: 14px; }
.waiting { color: var(--a-ink-2); }
.addrow { width: 100%; appearance: none; background: none; border: 0; border-top: 1px solid var(--a-line); font: inherit; color: inherit; text-align: left; cursor: pointer; }
.addrow .t b { color: var(--a-accent-text); }
.addrow .chev { color: var(--a-accent-text); font-size: 24px; font-weight: 600; }
.shape .t { gap: 8px; }
.stale :is(.act, .addrow, .pitch button, .workshop .link) { opacity: .45; pointer-events: none; }
.a-stale-note { margin: 0 0 12px; }
.add { flex-direction: column; align-items: stretch; gap: 12px; }
.grow { flex: 1; }
.pair { display: flex; gap: 10px; justify-content: flex-end; }
.pair .a-btn { flex: none; padding: 0 20px; }
.size { margin: 12px 4px 0; font-size: 14.5px; color: var(--a-ink-3); line-height: 1.4; }
.size b { color: var(--a-ink); }
.meter { display: flex; gap: 6px; margin: 10px 4px 0; }
.meter i { flex: 1; height: 8px; border-radius: 4px; background: var(--a-surface-2); }
.meter i.used { background: var(--a-accent); }
.meter i.over { background: var(--a-amber); }
.workshop { margin-top: 14px; gap: 8px; box-shadow: var(--a-card-shadow), inset 0 0 0 2px var(--a-amber); }
.workshop b { font-size: 17px; }
.small { font-size: 15px; }
.big { min-height: 54px; display: inline-flex; align-items: center; justify-content: center; gap: 10px; }
.big svg { width: 20px; height: 20px; flex: none; }
.apple { background: #000; color: #fff; border-color: transparent; }
.google { background: var(--a-surface); color: var(--a-ink); border: 1px solid var(--a-line); }
.or { display: flex; align-items: center; gap: 12px; color: var(--a-ink-3); font-size: 14.5px; margin: 2px 4px; }
.or::before, .or::after { content: ''; flex: 1; height: 1px; background: var(--a-line); }
.center { align-self: center; }
.ways-note { margin: 8px 4px 0; }
.ways-add { margin: 8px 4px 0; }
.scrim { position: fixed; inset: 0; background: rgba(10, 14, 22, .38); display: flex; align-items: flex-end; justify-content: center; z-index: 20; }
.sheet { width: 100%; max-width: 640px; box-sizing: border-box; background: var(--a-surface); border-radius: 28px 28px 0 0;
  padding: 12px 22px calc(24px + env(safe-area-inset-bottom, 0px)); display: flex; flex-direction: column; gap: 14px; }
.grab { width: 40px; height: 5px; border-radius: 3px; background: var(--a-surface-2); align-self: center; margin-bottom: 4px; }
.sheet-h { font-size: 26px; font-weight: 750; letter-spacing: -.02em; line-height: 1.1; margin: 0; }
</style>
