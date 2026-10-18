// The words of the Elyir account in the Printers app (design/one-cloud/, A, picked 15 October 2026), pure, so
// tests/you.test.ts can pin them. account.ts holds the signed-in state; pages/YouPage.vue and the list only draw.

import { agoWords, backupWords } from '../intent/bring.ts'

export interface Plan {
  name: string; on: boolean; away: boolean; backups: boolean
  until?: number | null   // a paid plan: when its period ends
  cancels?: boolean       // stopped, ending with this period
  manage?: boolean        // paid with Stripe: Manage opens its customer portal
  covers?: number | null  // how many printers the plan covers (Home, design/plan-size/, A); testers have no size
}
export type PaidPlan = 'monthly' | 'yearly'
/** Paying, when it's open: Stripe's prices as Bench Cloud reads them ("$5 a month", and "$5"). */
export interface Pay { prices: Record<PaidPlan, string>; amounts?: Record<PaidPlan, string> }
export interface CloudDevice {
  id: string
  name: string
  kind: 'printer' | 'box'
  backup: { id: string; at: number; size: number } | null
}
export interface Phone { id: string; agent: string; seen: number | null; you: boolean }
export interface PendingInvite { id: string; email: string; created: number; expires: number }
export interface OwnerInvite { email: string; inviter: string; printers: string; for_you: boolean; signed_in_as: string }
export interface Me {
  house?: { id: string; workshop_asked?: number | null }
  invites?: PendingInvite[]
  printers?: number       // what counts against the plan's size: printers, and the Kobras behind a Bench Box
  plan: Plan
  you: { email: string }
  owners: { id?: string; email: string; you: boolean }[]
  phones?: Phone[]
  devices: CloudDevice[]
}

export const YOU_TITLE = 'You'
export const ACCOUNT_LINE = 'Elyir account · also for the home hub'
export const PITCH_NAME = 'Bench Cloud'
export const PITCH_LINE = "For when you're not home."
export const GETS = [
  { icon: 'globe', title: 'See and stop them from anywhere', line: 'Every printer and the Bench Box, live, wherever you are.' },
  { icon: 'reload', title: 'A backup every night', line: 'A new card comes back as it was.' },
  { icon: 'phone', title: 'A new phone already knows them', line: 'Coming soon: sign in instead of pairing at each printer.' },
] as const
export const SEE_PLAN = 'See the plan'
export const PITCH_STRIP_LINE = 'Bench Cloud · a backup every night too'
export const NOT_NOW = 'Not now'
export const SIGN_IN_TITLE = 'Your Elyir account'
export const SIGN_IN_SUB = 'Sign in with your email. We send a code, no password. The same account works for the Elyir home hub.'
export const PLAN_OFF = 'At home, everything already works without it. Bench Cloud adds:'
export const STOP_ANY = 'Stop any time.'
export const PLAN_TITLE = 'Bench Cloud for this house'
export const PLAN_SUB = 'Every printer and the Bench Box in the house come with it. At home, everything works without it.'
export const PRICE = 'Monthly $5 or yearly $50, when it opens.'
// before paying opens (or from an older Bench Cloud) the prices as planned; after, always Stripe's
const PLANNED: Pay = { prices: { monthly: '$5 a month', yearly: '$50 a year' }, amounts: { monthly: '$5', yearly: '$50' } }
const amount = (plan: PaidPlan, pay: Pay | null = null) => (pay?.amounts ?? PLANNED.amounts!)[plan]
export const priceOpen = (pay: Pay | null) => `Monthly ${amount('monthly', pay)} or yearly ${amount('yearly', pay)}. Stop any time.`
export const turnOnLabel = (plan: PaidPlan, pay: Pay | null = null) => `Turn on · ${(pay ?? PLANNED).prices[plan]}`
export const planName = (plan: PaidPlan, pay: Pay | null = null) => `${plan === 'yearly' ? 'Yearly' : 'Monthly'} · ${amount(plan, pay)}`
export const HAVE_INVITE = 'Have a tester invite?'
export const MANAGE = 'Manage'
export const PAID_WAIT = 'Paid. Turning Bench Cloud on…'
export const PAID_SLOW = "Paid, and Stripe hasn't told Bench Cloud yet. It turns on by itself in a minute or two."
export const INVITE_HINT = "It's free for testers for now, by invite."
export const ALERTS_FREE = 'Alerts reach this phone either way, free.'
export const AWAY_WORD = 'At home only'
export const AWAY_LINE = "Can't see it from here"
export const AWAY_TITLE = 'See them from here with Bench Cloud'
export const AWAY_SUB = 'Your printers are on your home Wi-Fi, so this phone can only reach them there.'
/** Out of reach means "at home only" when the account is known and its plan doesn't carry the printers from away. Signed
 *  out, nothing is known (a printer may be carried by an older grant), so it stays "Out of reach". */
export const homeOnly = (me: Me | null | undefined, noHouse = false) => noHouse || (!!me && !me.plan.away)
export const NOT_YOURS = "Signed in, but this email isn't on a Bench Cloud house yet."

export function planOf(name: string | null | undefined): Plan {
  const on = ['tester', 'monthly', 'yearly'].includes(name ?? '')
  return { name: name || 'none', on, away: on, backups: on }
}

/** "October 14, 2027" */
export const dateWords = (epoch: number) =>
  new Date(epoch * 1000).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })

export function planLine(p: Plan, pay: Pay | null = null): string {
  if (p.name === 'tester') return 'Tester · free, by invite'
  if (p.name === 'monthly' || p.name === 'yearly') {
    const name = planName(p.name, pay)
    if (!p.on) return "Off · the last payment didn't go through"
    if (!p.until) return name
    return `${name} · ${p.cancels ? 'ends' : 'renews'} ${dateWords(p.until)}`
  }
  return 'Off'
}

const OK = '✓'
/** A printer's line on You: from away, and its last backup. */
export function deviceLine(d: CloudDevice, plan: Plan, now: number): string {
  if (!plan.on) return 'At home only'
  const away = plan.away ? `From away ${OK}` : 'At home only'
  if (d.kind === 'box') return away
  return `${away} · ${d.backup ? `backed up ${backupWords(d.backup.at, now)}` : 'first backup tonight'}`
}
export const NOT_IN = 'Not in Bench Cloud yet.'
export const notInLine = (atHome: boolean) => (atHome ? NOT_IN : `${NOT_IN} Add it from home.`)

/** "iPhone", "Mac": what a signed-in browser is, from its user agent. */
export function phoneName(agent: string): string {
  if (/iPhone/.test(agent)) return 'iPhone'
  if (/iPad/.test(agent)) return 'iPad'
  if (/Android/.test(agent)) return /Mobile/.test(agent) ? 'Android phone' : 'Android tablet'
  if (/Macintosh|Mac OS X/.test(agent)) return 'Mac'
  if (/Windows/.test(agent)) return 'Windows computer'
  if (/CrOS/.test(agent)) return 'Chromebook'
  if (/Linux/.test(agent)) return 'Linux computer'
  return 'A phone or computer'
}
export function phoneLine(p: Phone, now: number): string {
  if (p.you) return 'This one · now'
  return p.seen ? `Last used ${agoWords(p.seen, now)}` : 'Signed in'
}

/** The round button by the title: the email's first letter. */
export const initial = (email: string | undefined) => (email?.trim()[0] ?? '').toUpperCase()

// ---- more ways in (design/sign-in/, A, picked 15 October 2026) ----------------------------------------------------

export const SIGN_IN_LEAD = 'Sign in to see your printers from anywhere. The same account works for the Elyir home hub.'
export const OR_EMAIL = 'or with your email'
export const NO_PASSWORD = 'We send a six-digit code. No password, ever.'
export const USE_EMAIL = 'Use your email instead'
export const continueWith = (p: 'google' | 'apple') => `Continue with ${p === 'google' ? 'Google' : 'Apple'}`
export const welcomeBack = (email: string) => `Welcome back. Last time: ${email}.`

/** What this device calls a passkey: Face ID on an iPhone, Touch ID on a Mac. */
export function faceWord(agent: string): string {
  if (/iPhone|iPad/.test(agent)) return 'Face ID'
  if (/Macintosh|Mac OS X/.test(agent)) return 'Touch ID'
  if (/Windows/.test(agent)) return 'Windows Hello'
  return 'a passkey'
}
export const faceSignIn = (agent: string) => `Sign in with ${faceWord(agent)}`
export const offerTitle = (agent: string) => `Use ${faceWord(agent)} next time?`
export const offerLine = (agent: string) =>
  `Sign in on this ${phoneName(agent)} ${faceWord(agent) === 'Face ID' ? 'with a glance' : 'in a moment'}, no email to wait for. You can turn it off in You.`
export const offerYes = (agent: string) => `Use ${faceWord(agent)}`

export const WAYS_TITLE = 'Ways to sign in'
export const ANOTHER_ADD = 'Add another owner'
export const removeOwnerAsk = (email: string) =>
  `Take ${email} off as an owner? They'll no longer see the printers' backups or plan. We'll email them to say so.`
/** An owner's line: the only owner is told what a second one is for. */
export const ownerLine = (you: boolean, owners: number) =>
  you ? (owners === 1 ? 'You, the only owner. A second owner can get you back in if you lose access.' : 'You')
    : 'Can get a backup back, and sign in anywhere'
/** Whether this device can still add Face ID or Touch ID: not when the account's Apple passkey already syncs to it. */
export const canAddPasskey = (agent: string, passkeys: { friendly_name?: string }[]) =>
  !(['Face ID', 'Touch ID'].includes(faceWord(agent)) && passkeys.some((p) => /apple|icloud/i.test(p.friendly_name ?? '')))
export interface WayRow { id: string; kind: 'passkey' | 'google' | 'apple' | 'email'; title: string; line: string; remove: boolean }
interface Ways { passkeys: { id: string; friendly_name?: string; created_at: string; last_used_at?: string | null }[]; identities: { identity_id: string; provider: string; email: string | null }[] }

const dayOf = (iso: string, now: number) => {
  const d = new Date(iso), n = new Date(now)
  return d.toDateString() === n.toDateString() ? 'today' : dateWords(d.getTime() / 1000)
}
/** A passkey by what the person uses, not by where it's kept: Supabase names it after the password manager that holds it
 *  ("Apple Passwords"), which syncs it to every device signed in there. */
export function passkeyWords(kept?: string): { title: string; kept: string | null } {
  const k = (kept ?? '').trim()
  if (/apple|icloud/i.test(k)) return { title: 'Face ID or Touch ID', kept: 'In Apple Passwords, on your Apple devices' }
  if (/google/i.test(k)) return { title: 'Fingerprint or face unlock', kept: 'In Google Password Manager' }
  if (/windows/i.test(k)) return { title: 'Windows Hello', kept: null }
  return { title: k ? `Passkey in ${k}` : 'Passkey', kept: null }
}

/** You's list of ways in: passkeys, Google or Apple, and the email code, which is always there and can't be removed. */
export function wayRows(w: Ways, email: string, now: number): WayRow[] {
  const linked = w.identities.filter((i) => i.provider === 'google' || i.provider === 'apple')
  return [
    ...w.passkeys.map((p): WayRow => {
      const { title, kept } = passkeyWords(p.friendly_name)
      const used = p.last_used_at ? ` · last used ${dayOf(p.last_used_at, now)}` : ''
      return { id: p.id, kind: 'passkey', title, remove: true, line: `${kept ? `${kept} · ` : ''}added ${dayOf(p.created_at, now)}${used}` }
    }),
    // Supabase won't take away an account's only way in that isn't the code: then there's nothing to remove
    ...linked.map((i): WayRow => ({ id: i.identity_id, kind: i.provider as 'google' | 'apple', title: i.provider === 'google' ? 'Google' : 'Apple',
      line: i.email || email, remove: w.identities.length > 1 })),
    { id: 'email', kind: 'email', title: 'Email code', line: 'Always on: printers and the box use it too', remove: false },
  ]
}
export const notLinked = (p: 'google' | 'apple') =>
  `${p === 'google' ? 'Google' : 'Apple'} isn't set up for this account. Sign in with it once, with the same email, and it's added here.`

// ---- how many printers the plan covers (design/plan-size/, A, picked 15 October 2026) -----------------------------

export const planTitle = (p: Plan) => (p.covers ? 'Bench Cloud Home' : 'Bench Cloud')
export const isOver = (me: Me) => !!me.plan.covers && (me.printers ?? 0) > me.plan.covers
/** "4 of 5 printers", or over it "7 printers · Home covers 5"; nothing for a plan without a size. */
export function sizeLine(me: Me): string | null {
  const n = me.printers ?? 0, of = me.plan.covers
  if (!of) return null
  return n > of ? `${n} printers · Home covers ${of}` : `${n} of ${of} printer${of === 1 ? '' : 's'}`
}
export const SIZE_HINT = "The Kobras behind the Bench Box count; the box doesn't."
export const WORKSHOP_TITLE = 'Workshop is coming soon'
export const workshopLine = (n: number, of: number) =>
  `For more than ${of} printers: orders into the queue, cost per print, several people at once. Until then all ${n} keep working on Home.`
export const TELL_ME = 'Tell me when it opens'
export const TOLD = "We'll email you when it opens."

// ---- the Elyir account and owner invites (design/account/, A, picked 15 October 2026) -----------------------------

export const SIGN_IN_ELYIR = 'Sign in with Elyir'
export const GOING = 'Taking you to your Elyir account…'
export const ACCOUNT_ROW = 'Your Elyir account: sign-in, payments, phones'
export const OWNER_ADD_LINE = 'Someone else in the house, with their own Elyir account.'
export const INVITED_TITLE = "You're invited to someone's printers"
export const INVITED_LINE = 'Sign in with the email the invite was sent to. Then you see whose printers they are, and say yes or no.'
export const invitedNote = (email: string) => `We emailed ${email}. They become an owner when they say yes; we'll tell you when they do.`
export const acceptTitle = (inviter: string) => `Be an owner of ${inviter}'s printers?`
export const acceptLine = (i: { inviter: string; email: string; printers: string }) =>
  `${i.inviter} invited you, as ${i.email}. You'd see ${i.printers || 'their printers'} from anywhere, their backups and the plan. ` +
  'Only Elyir Bench: nothing else of theirs comes with it.'
export const notForYou = (i: { email: string; signed_in_as: string }) =>
  `This invite is for ${i.email}, and you're signed in as ${i.signed_in_as}. To accept it, sign out of your Elyir account ` +
  `(at account.elyir.com) and sign in with ${i.email}.`
/** A pending owner invite: "Invited 2 minutes ago, waiting for them · runs out October 22". */
export function inviteLine(i: PendingInvite, now: number): string {
  const until = new Date(i.expires * 1000).toLocaleDateString('en-US', { month: 'long', day: 'numeric' })
  return `Invited ${agoWords(i.created, now).replace(/^today at /, 'today at ')}, waiting for them · runs out ${until}`
}
