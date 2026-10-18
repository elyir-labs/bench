// Sign in with Elyir (design/account/, A, picked 15 October 2026): the Printers app goes to account.elyir.com with a
// challenge and trades the code it comes back with, and this tab's verifier, for a session of its own.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { finishSignIn, signInUrl } from '../src/shell-app/signin.ts'
import { acceptLine, acceptTitle, inviteLine, invitedNote, notForYou } from '../src/shell-app/you.ts'

const API = 'https://cloud.elyir.app'
const memory = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) } }

test('Sign in goes to the account with a challenge; the code that comes back and this tab’s verifier make a session', async () => {
  const tab = memory()
  const url = new URL(await signInUrl('https://printers.elyir.app/you?accept=oi_1', tab))
  assert.equal(url.origin + url.pathname, 'https://account.elyir.com/continue')
  assert.equal(url.searchParams.get('app'), 'bench')
  assert.equal(url.searchParams.get('return'), 'https://printers.elyir.app/you?accept=oi_1')
  const verifier = tab.getItem('elyir.signin.verifier')!
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)))
  assert.equal(url.searchParams.get('challenge'), Buffer.from(digest).toString('base64url'))

  const seen: any[] = []
  const f = (async (u: string, init: RequestInit = {}) => {
    seen.push({ u, body: init.body ? JSON.parse(String(init.body)) : undefined })
    const d = u.endsWith('/v1/config') ? { supabase_url: API, anon_key: 'anon' }
      : { access_token: 'a', refresh_token: 'r', expires_at: 1800000000, user: { email: 'Sam@example.net' } }
    return new Response(JSON.stringify(d), { status: 200 })
  }) as unknown as typeof fetch
  const o = await finishSignIn(API, 'ec_1', tab, f)
  assert.deepEqual(seen[0], { u: `${API}/v1/account/redeem`, body: { code: 'ec_1', verifier } })
  assert.deepEqual(o, { api: API, email: 'sam@example.net', access: 'a', refresh: 'r', until: 1800000000, supabase: { supabase_url: API, anon_key: 'anon' } })
  await assert.rejects(finishSignIn(API, 'ec_1', tab, f), /another tab/)   // the verifier goes once used
})

test('an owner invite says whose it is, what yes means, and what to do when it’s for another email', () => {
  assert.equal(acceptTitle('alex@example.net'), "Be an owner of alex@example.net's printers?")
  assert.equal(acceptLine({ inviter: 'sam@example.net', email: 'jo@example.net', printers: 'Workshop and Studio' }),
    "sam@example.net invited you, as jo@example.net. You'd see Workshop and Studio from anywhere, their backups and the plan. Only Elyir Bench: nothing else of theirs comes with it.")
  assert.match(notForYou({ email: 'jo@example.net', signed_in_as: 'sam@example.net' }), /for jo@example.net, and you're signed in as sam@example.net/)
  assert.equal(invitedNote('jo@example.net'), "We emailed jo@example.net. They become an owner when they say yes; we'll tell you when they do.")
  const now = new Date(2026, 9, 15, 9, 30).getTime()
  assert.match(inviteLine({ id: 'oi_1', email: 'jo@example.net', created: now / 1000 - 120, expires: now / 1000 + 7 * 86400 }, now),
    /^Invited .*, waiting for them · runs out October 22$/)
})
