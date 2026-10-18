// Sign in with Elyir (design/account/, picked 15 October 2026): the Printers app has no sign-in screens of its own. Sign in
// goes to account.elyir.com/continue with a challenge; the account sends the person back with a one-time code, and Bench
// Cloud trades the code and this tab's verifier for a Supabase session of the app's own (signed in and out by itself).

import { cloudCall, type Owner } from '../cloud.ts'

export const ACCOUNT_URL = (import.meta.env?.VITE_ACCOUNT_URL as string | undefined) || 'https://account.elyir.com'
const VERIFIER = 'elyir.signin.verifier'
const b64url = (b: Uint8Array) => btoa(String.fromCharCode(...b)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

/** Where Sign in goes: the account, which comes back to `back` with ?elyir_code= (or &elyir_code=). */
export async function signInUrl(back: string, store: Pick<Storage, 'setItem'> | null, account = ACCOUNT_URL): Promise<string> {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)))
  const challenge = b64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))))
  store?.setItem(VERIFIER, verifier)
  return `${account}/continue?${new URLSearchParams({ app: 'bench', return: back, challenge })}`
}

/** Back from the account with a code: this tab's verifier makes it a session, reached through Bench Cloud afterwards. */
export async function finishSignIn(api: string, code: string, store: Pick<Storage, 'getItem' | 'removeItem'> | null,
                                   f: typeof fetch = fetch): Promise<Owner> {
  const verifier = store?.getItem(VERIFIER)
  store?.removeItem(VERIFIER)
  if (!verifier) throw new Error('That sign-in started in another tab. Sign in again here.')
  const d = await cloudCall(api, 'POST', '/v1/account/redeem', { code, verifier }, undefined, f)
  const cfg = await cloudCall(api, 'GET', '/v1/config', undefined, undefined, f)
  return {
    api, email: String(d.user?.email ?? '').toLowerCase(), access: d.access_token, refresh: d.refresh_token,
    until: d.expires_at ?? Date.now() / 1000 + d.expires_in,
    supabase: { supabase_url: cfg.supabase_url, anon_key: cfg.anon_key },
  }
}
