// Bench Cloud on a phone (design/cloud/ C, picked 11 October 2026; docs/cloud.md): turning it on for the house, the
// owner known by email (a code each time, no password), putting this printer in the house, a second way back, and
// the Allow card for a new card's backup. The words live here, pure, so tests/cloud.test.ts can pin them;
// components/cloud/ only draws.
//
// As built for testers: free by invite (no payment). Owners sign in with Supabase Auth (an email code, no password; 13
// October 2026), kept per page address, so a second printer's page asks for one more code. Sign in with Apple and Google
// come later as a Supabase setting.

import { agoWords, backupWords } from './intent/bring.ts'

export const CLOUD_API = 'https://cloud.elyir.dev'

/** GET /door/cloud: this printer in a house or not, and its last nightly backup. */
export interface DoorCloud {
  joined: boolean
  name: string | null
  house: string | null
  last: { at: number; size?: number; why?: string } | null
}

/** The house's owner, signed in on this phone: Supabase Auth's session (access, refresh, until), or `token`, a sign-in
 *  from before Supabase Auth that keeps working until this phone signs in again. */
export interface Owner {
  api: string
  email: string
  token?: string
  access?: string
  refresh?: string
  until?: number
  supabase?: SupabaseConfig
}
export interface SupabaseConfig { supabase_url: string; anon_key: string }

const KEY = 'elyir.cloud.owner'

export function loadOwner(store: Pick<Storage, 'getItem'> | null): Owner | null {
  try {
    const o = JSON.parse(store?.getItem(KEY) ?? 'null')
    if (!o || typeof o.api !== 'string') return null
    return typeof o.token === 'string' || (typeof o.access === 'string' && typeof o.refresh === 'string' && o.supabase) ? o : null
  } catch {
    return null
  }
}

export function saveOwner(store: Pick<Storage, 'setItem' | 'removeItem'> | null, o: Owner | null): void {
  try {
    if (o) store?.setItem(KEY, JSON.stringify(o))
    else store?.removeItem(KEY)
  } catch {
    // private browsing: the owner signs in again next time
  }
}

// ---- the card in Care -------------------------------------------------------------------------------

export type CardState = 'off' | 'owner' | 'on'
export const cardState = (d: DoorCloud, owner: Owner | null): CardState => (d.joined ? 'on' : owner ? 'owner' : 'off')

export const CARD_NAME = 'Bench Cloud'
export function cardLine(state: CardState, d: DoorCloud, printer: string, now: number): string {
  if (state === 'off') return 'Off. Everything here works without it, and always will.'
  if (state === 'owner') return `Your Bench Cloud is on. Add ${printer} for a backup every night.`
  if (d.last?.why) return `On · the last backup didn't happen: ${d.last.why}`
  if (d.last?.at) return `On · backed up ${backupWords(d.last.at, now)}`
  return 'On · the first backup is tonight'
}
/** On the printer's own screen nothing is typed: turning it on is a phone's, and this says where on the phone. */
export const panelOff = (_printer: string) => 'Off. To turn it on: on your phone, open the Printers app at printers.elyir.app.'
export const PRINTERS_YOU = 'https://printers.elyir.app/you'
export const TURN_ON_IN_APP = 'Turn on in the Printers app'
/** A phone away sees how it is; turning it on and adding a printer happen at home. */
export function awayLine(state: CardState, printer: string): string | null {
  if (state === 'off') return 'Off. Turn it on from your phone, at home.'
  if (state === 'owner') return `Add ${printer} from your phone, at home.`
  return null
}
export const TURN_ON = 'Turn on'
export const SIGN_IN = 'I have it'
export const addPrinter = (printer: string) => `Add ${printer}`

// ---- turning it on (C-phone-join), signing in --------------------------------------------------------

export const JOIN_TITLE = 'Bench Cloud for this house'
export const JOIN_SUB = 'Every phone at home gets it, with no sign-in.'
export const GETS = [
  { title: 'A backup every night', line: 'Settings, history and spools, for every printer you add.' },
  { title: 'A new card comes back as it was', line: 'Its address from away and its paired phones too.' },
]
export const LATER = 'Coming for testers: from away with nothing to set up, your shelf on every phone, slicing in seconds.'
export const EMAIL_LABEL = 'Your email'
export const EMAIL_HINT = "You'll be the owner: the one who can get a backup back. We send a code to check it. No password."
export const INVITE_LABEL = 'Tester invite code'
export const INVITE_HINT = 'Bench Cloud is free for testers for now, by invite.'
export const SEND = 'Send the code'
export const codeTitle = (to: string) => `Type the code we sent to ${to}`
export const SIGN_IN_TITLE = 'Sign in to your Bench Cloud'
export const SIGN_IN_SUB = 'The email you turned it on with. We send a code, no password.'
export const SIGN_IN_GO = 'Sign in'
export const joining = (printer: string) => `Adding ${printer}…`
export const CANCEL = 'Cancel'

// ---- a second way back (C-phone-backup) --------------------------------------------------------------

export const ON_TITLE = 'Bench Cloud is on.'
export const onLine = (email: string, printer: string) => `${printer}'s first backup is tonight. You're the owner, as ${email}.`
export const SECOND_LABEL = 'A second way back'
export const SECOND_LINE = "If this phone is lost and you can't get into your email, a second owner gets you back in."
export const SECOND_ADD = 'Add a second owner'
export const SECOND_ADD_LINE = 'Someone else in the house, with their own email.'
export const SECOND_EMAIL = 'Their email'
export const SECOND_GO = 'Add them'
export const secondDone = (email: string) => `We emailed ${email} an invite. They become an owner when they accept it, signed in with that email.`
export const NOT_NOW = 'Not now'
export const DONE = 'Done'

export const validEmail = (s: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(s.trim())
export const validInvite = (s: string) => /^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$/.test(s.trim())
export const sixDigits = (s: string) => /^\d{6}$/.test(s.replace(/\s/g, ''))
export const digitsOf = (s: string) => s.replace(/\D/g, '').slice(0, 6)

// ---- the Allow card for a new card's backup (C-phone-allow) -------------------------------------------

export const allowTitle = (name: string) => `Allow ${name}'s backup onto a new card?`
export function allowWhat(backupAt: number | null, now: number): string {
  const when = backupAt ? backupWords(backupAt, now) : null
  const lead = !when ? 'Its last backup' : /ago$|^just now$/.test(when) ? `Made ${when}` : `From ${when}`
  return `${lead}: settings, print history and spools. Its address from away and its paired phones come back too.`
}
export const allowWhere = (name: string, at: number, now: number) => `Asked from ${name}'s own screen, at home, ${agoWords(at, now)}`

// ---- signing in: Supabase Auth -------------------------------------------------------------------------

const sbWords = (d: any): string => {
  const msg = String(d?.msg || d?.error_description || d?.message || '')
  return /expired|invalid|otp/i.test(msg) ? "That code isn't right, or it has run out. Ask for a new one." : msg || "That didn't work. Try again."
}

export async function supabaseCall(cfg: SupabaseConfig, path: string, body: unknown, token?: string, f: typeof fetch = fetch): Promise<any> {
  let r: Response
  try {
    r = await f(`${cfg.supabase_url}/auth/v1${path}`, { method: 'POST', body: JSON.stringify(body ?? {}),
      headers: { apikey: cfg.anon_key, 'Content-Type': 'application/json', Authorization: `Bearer ${token || cfg.anon_key}` } })
  } catch {
    throw new Error("Signing in isn't reachable right now.")
  }
  const d = await r.json().catch(() => null)
  if (!r.ok) throw new Error(sbWords(d))
  return d
}

/** Sends the email its code (Supabase, through Postmark); the config says where Supabase is. */
export async function sendCode(api: string, email: string, f: typeof fetch = fetch): Promise<SupabaseConfig> {
  const cfg = await cloudCall(api, 'GET', '/v1/config', undefined, undefined, f) as SupabaseConfig
  if (!cfg?.supabase_url) throw new Error("Bench Cloud can't sign anyone in right now.")
  await supabaseCall(cfg, '/otp', { email, create_user: true }, undefined, f)
  return cfg
}

const session = (api: string, email: string, cfg: SupabaseConfig, d: any): Owner =>
  ({ api, email, access: d.access_token, refresh: d.refresh_token, until: d.expires_at ?? Date.now() / 1000 + d.expires_in, supabase: cfg })

export async function verifyCode(api: string, cfg: SupabaseConfig, email: string, code: string, f: typeof fetch = fetch): Promise<Owner> {
  return session(api, email, cfg, await supabaseCall(cfg, '/verify', { type: 'email', email, token: digitsOf(code) }, undefined, f))
}

/** The token to send: a sign-in from before passes through; Supabase's is refreshed first when it's about to run out.
 *  null when Supabase says the session is gone (signed out everywhere): sign in again. */
export async function ownerToken(o: Owner, keep: (o: Owner | null) => void, now = Date.now() / 1000,
                                 f: typeof fetch = fetch): Promise<string | null> {
  if (o.token) return o.token
  if (!o.access || !o.refresh || !o.supabase) return null
  if ((o.until ?? 0) - now > 60) return o.access
  try {
    const fresh = session(o.api, o.email, o.supabase, await supabaseCall(o.supabase, '/token?grant_type=refresh_token', { refresh_token: o.refresh }, undefined, f))
    keep(fresh)
    return fresh.access!
  } catch {
    keep(null)
    return null
  }
}

/** A call to Bench Cloud as the owner, with this phone's name for a new card's "Allow on Alex's iPhone". */
export async function ownerCall(o: Owner, keep: (o: Owner | null) => void, device: string, method: string, path: string, body?: unknown,
                                f: typeof fetch = fetch): Promise<any> {
  const token = await ownerToken(o, keep, Date.now() / 1000, f)
  if (!token) throw new Error('Sign in to your Bench Cloud again.')
  return cloudCall(o.api, method, path, body, token, f, { 'X-Bench-Device': device })
}

// ---- talking to Bench Cloud --------------------------------------------------------------------------

export async function cloudCall(api: string, method: string, path: string, body?: unknown, token?: string,
                                f: typeof fetch = fetch, extra: Record<string, string> = {}): Promise<any> {
  let r: Response
  try {
    r = await f(`${api}${path}`, {
      method,
      headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error("Bench Cloud can't be reached right now.")
  }
  const d = await r.json().catch(() => null)
  if (!r.ok) throw new Error(typeof d?.error === 'string' ? d.error : `Bench Cloud answered ${r.status}.`)
  return d
}
