// The Bench app from away (design/bench-remote/, C, picked 9 October 2026; A built as part of it). The same app is
// served by the box's away listener (bench/away.py), where GET /door/me says who is looking: a phone paired at the
// box, or a guest invited by link who watches or steps in. At home /door/me isn't there and nothing changes.
// Pure words and rules, so tests/bench-away.test.ts can pin them; here.ts holds the live state, the pages draw it.

import type { Tile } from './bench'

export type Reach = 'watch' | 'step_in'
export type Lasts = 'day' | 'week' | 'removed'

/** Who this page is for. At home: `away` false and everything as before. */
export interface Here {
  checked: boolean
  away: boolean
  paired: boolean
  kind: 'phone' | 'guest' | null
  reach: Reach | null
  until: number | null
  name: string | null
  invitedBy: string | null
  actions: string[]
  may: { queue: boolean; invite: boolean }
  box: { name: string; address: string | null } | null
}

export const HOME: Here = { checked: true, away: false, paired: true, kind: null, reach: null, until: null, name: null, invitedBy: null,
                            actions: [], may: { queue: true, invite: true }, box: null }

/** GET /door/me's answer as this page's mode; anything that isn't the away listener's answer is home. */
export function hereOf(d: unknown): Here {
  const m = d as Record<string, unknown> | null
  if (!m || typeof m !== 'object' || m.role !== 'away') return HOME
  const may = (m.may ?? {}) as { queue?: boolean; invite?: boolean }
  const box = (m.box ?? null) as Here['box']
  return {
    checked: true, away: true, paired: !!m.paired,
    kind: m.kind === 'guest' ? 'guest' : m.kind === 'phone' ? 'phone' : null,
    reach: m.reach === 'step_in' ? 'step_in' : m.reach === 'watch' ? 'watch' : null,
    until: typeof m.until === 'number' ? m.until : null,
    name: typeof m.name === 'string' ? m.name : null,
    invitedBy: typeof m.invited_by === 'string' ? m.invited_by : null,
    actions: Array.isArray(m.actions) ? m.actions.filter((a): a is string => typeof a === 'string') : [],
    may: { queue: !!may.queue, invite: !!may.invite },
    box: box && typeof box.name === 'string' ? box : null,
  }
}

export const isGuest = (h: Here) => h.away && h.kind === 'guest'

/** Several shelf models at once (design/bench-several/, C): at home, and a paired phone away, which adds the plan to the
 *  queue; never a guest. */
export const mayPlan = (h: Here) => !h.away || (h.kind === 'phone' && h.may.queue)

/** The tab bar: a guest gets the printers and the shelf to look at; everyone else every tab. */
export function tabsFor(h: Here): string[] {
  return isGuest(h) ? ['/', '/print'] : ['/', '/print', '/spools', '/care']
}

/** The chip at the top right away: Away for a paired phone and a guest who steps in, Watching for a guest who watches. */
export function chipFor(h: Here): { label: string; icon: 'lock' | 'eye' } | null {
  if (!h.away || !h.paired) return null
  return isGuest(h) && h.reach !== 'step_in' ? { label: 'Watching', icon: 'eye' } : { label: 'Away', icon: 'lock' }
}

/** A person from the name of what invited them: phones are named "Alex's iPhone", so the invite says "Alex". */
export function ownerOf(name: string | null | undefined): string | null {
  const n = name?.trim()
  if (!n) return null
  return n.match(/^(.+?)['’]s\s+\S/)?.[1] ?? n
}

/** Who "you" is in the bench's sentence for a guest: the person who invited them, else the household. */
export function hostOf(h: Here): string {
  const by = ownerOf(h.invitedBy)
  return by && h.invitedBy !== h.box?.name ? by : 'someone at home'
}

/** What a tile offers away: its button only when the away list allows that action, else a word on where it's done.
 *  A guest who watches gets neither. */
export function tileAct(t: Tile, h: Here): { button: string | null; note: string | null } {
  if (!h.away) return { button: t.action, note: null }
  if (!t.action || (isGuest(h) && h.reach !== 'step_in')) return { button: null, note: null }
  if (t.actionId && h.actions.includes(t.actionId)) return { button: t.action, note: null }
  if (t.actionId === 'print_model') return { button: null, note: null }
  if (t.actionId === 'taken_off') return { button: null, note: 'Take it off at home' }
  if (t.queued) return { button: null, note: 'Starts at home' }
  return { button: null, note: 'Needs someone at home' }
}

// ── days and times ──

const time = (d: Date) => d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase()
const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
const daysFrom = (t: number, now: Date) => Math.round((startOf(new Date(t * 1000)) - startOf(now)) / 86400000)

/** "today at 7:33 pm", "tomorrow at 7:33 pm", "Thursday, October 16". */
export function dayLong(t: number, now: Date): string {
  const d = new Date(t * 1000), n = daysFrom(t, now)
  if (n === 0) return `today at ${time(d)}`
  if (n === 1) return `tomorrow at ${time(d)}`
  return d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
}

/** As dayLong, but within the week just the day: "Thursday". */
export function dayShort(t: number, now: Date): string {
  const n = daysFrom(t, now)
  return n >= 2 && n < 7 ? new Date(t * 1000).toLocaleDateString('en-US', { weekday: 'long' }) : dayLong(t, now)
}

// ── the guest's bench ──

/** The line under a guest's printers: until when, and what tapping does. */
export function guestLine(h: Here, now: Date): string {
  const who = hostOf(h)
  const until = h.until ? `until ${dayShort(h.until, now)}` : `until ${who === 'someone at home' ? 'the household ends it' : `${who} ends it`}`
  return h.reach === 'step_in'
    ? `You can watch and step in ${until}. Tap a printer to see its camera, and to pause or stop its print.`
    : `You're watching ${until}. Tap a printer to see its camera. Pausing or stopping is up to ${who}.`
}

// ── inviting someone (C-phone-invite) ──

export const INVITE_DEFAULT: { reach: Reach; lasts: Lasts } = { reach: 'watch', lasts: 'week' }
export const INVITE = {
  title: 'Invite someone',
  sub: 'They open a link, type their name, and see the bench. Nothing to install.',
  can: 'What they can do',
  long: 'For how long',
  go: 'Share the link',
  foot: 'The link works once. If nobody opens it, it stops working tomorrow.',
}
export const REACH_WORDS: Record<Reach, { label: string; line: string }> = {
  watch: { label: 'Watch', line: 'See every printer, its camera and the shelf. Touch nothing.' },
  step_in: { label: 'Watch and step in', line: 'Also pause, carry on or stop a print, and cool a printer down.' },
}
export const LASTS_WORDS: Record<Lasts, string> = { day: 'A day', week: 'A week', removed: 'Until I remove it' }

/** What a share sheet sends with the link. */
export function shareText(reach: Reach, by: string | null): string {
  const owner = ownerOf(by)
  const who = owner ? `${owner} invited you` : "You're invited"
  return reach === 'watch' ? `${who} to watch the printers. Open the link and type your name.`
    : `${who} to watch the printers, and step in if one needs it. Open the link and type your name.`
}

// ── opening a link (C-guest-open) ──

export interface Look { box: { name: string }; invited_by: string | null; reach: Reach; until: number | null }

const inviter = (l: Look) => (l.invited_by && l.invited_by !== l.box.name ? ownerOf(l.invited_by) : null)

export function joinTitle(l: Look): string {
  const by = inviter(l)
  return by ? `${by} invited you to see their printers.` : "You're invited to see the printers."
}

export function joinCard(l: Look, now: Date): { chip: string; until: string; line: string } {
  return {
    chip: REACH_WORDS[l.reach].label,
    until: l.until ? `until ${dayLong(l.until, now)}` : 'until they end it',
    line: l.reach === 'watch' ? "See every printer, its camera and the shelf. You can't change anything."
      : 'See every printer, its camera and the shelf, and pause, carry on or stop a print if one needs it.',
  }
}

export function joinFoot(l: Look): string {
  const who = inviter(l) ?? 'The household'
  return `${who} sees your name, and can end this at any time. To come back easily: Share, then Add to Home Screen.`
}

// ── the shelf away (A-phone-shelf) ──

export const AT_HOME = {
  title: 'Prints start at home.',
  queued: "It waits on the bench. Nothing starts until someone at home clears a bed and taps It's clear.",
}

/** The shelf's sentence for someone who only looks: no question asked of them. */
export function lookingOnly(s: string): string {
  return s.replace(/\s*What should (it|they) print\?$/, '')
}

export function awayShelfFoot(h: Here): string {
  return isGuest(h) ? 'Every model printed on the bench lands here.'
    : "Every model printed on the bench lands here. From away, a model waits in the queue until someone at home says a bed is clear."
}

/** The card's line: who checks the bed, and where it would go now. */
export function atHomeLine(free: { name: string; filament: string | null } | null): string {
  const first = 'Someone at the printer checks the bed is clear first.'
  if (!free) return `${first} No printer is free now: it waits for the first one that is.`
  return `${first} ${free.name} is free now${free.filament ? `, with ${free.filament} loaded` : ''}.`
}

// ── the box's Phones (C-box-phones, A-box-add) ──

export interface PhoneRecord {
  id: string
  name: string
  joined: number
  last_seen: number | null
  notifications: boolean
  kind: string
  watching: number
  reach?: Reach
  until?: number | null
  invited_by?: string | null
}
export interface InviteRecord { id: string; reach: Reach; lasts: Lasts; invited_by: string; made: number; expires: number; until: number | null }
export interface PhonesList { address: string | null; phones: PhoneRecord[]; guests: PhoneRecord[]; invites: InviteRecord[]; watching: string[] }

export interface PhoneRow {
  id: string
  kind: 'phone' | 'guest' | 'invite'
  title: string
  chip: string | null
  line: string
  watching: boolean
  button: string
}

export const PHONES = { head: 'Phones', line: 'These can see the whole bench from anywhere.', invite: 'Invite someone', add: 'Add a phone' }

export function seenLine(p: { last_seen: number | null; joined: number }, now: Date): string {
  const t = p.last_seen ?? p.joined
  const mins = Math.max(0, Math.round((now.getTime() / 1000 - t) / 60))
  if (mins < 2) return 'Seen just now'
  if (mins < 60) return `Seen ${mins} minutes ago`
  const days = -daysFrom(t, now)
  if (days === 0) { const h = Math.round(mins / 60); return `Seen ${h} hour${h === 1 ? '' : 's'} ago` }
  return days === 1 ? 'Seen yesterday' : `Seen ${days} days ago`
}

const guestChip = (reach: Reach | undefined) => `Guest · ${REACH_WORDS[reach ?? 'watch'].label}`
const LASTS_LINE: Record<Lasts, string> = { day: 'for a day', week: 'for a week', removed: 'until removed' }

/** The household's phones, then guests, then invites nobody has opened yet. */
export function phoneRows(l: PhonesList, now: Date): PhoneRow[] {
  return [
    ...l.phones.map((p): PhoneRow => ({ id: p.id, kind: 'phone', title: p.name, chip: null, watching: false, button: 'Remove',
      line: [seenLine(p, now), p.notifications ? 'notifications on' : ''].filter(Boolean).join(' · ') })),
    ...l.guests.map((g): PhoneRow => ({ id: g.id, kind: 'guest', title: g.name, chip: guestChip(g.reach), watching: g.watching > 0, button: 'Remove',
      line: [g.invited_by ? `Invited by ${ownerOf(g.invited_by)}` : '', g.until ? `until ${dayLong(g.until, now)}` : 'until removed',
             g.watching > 0 ? 'watching now' : seenLine(g, now).replace('Seen', 'seen')].filter(Boolean).join(' · ') })),
    ...l.invites.map((i): PhoneRow => ({ id: i.id, kind: 'invite', title: 'Not opened yet', chip: guestChip(i.reach), watching: false,
      button: 'Cancel the invite', line: `Invited by ${ownerOf(i.invited_by)} · ${LASTS_LINE[i.lasts]} · the link stops working ${dayLong(i.expires, now)}` })),
  ]
}

/** The box's top line while a guest is connected: "Jo is watching". Never the household's own phones. */
export function watchingLine(names: string[]): string | null {
  if (!names.length) return null
  const all = [...new Set(names)]
  const list = all.length < 2 ? all[0] : `${all.slice(0, -1).join(', ')} and ${all[all.length - 1]}`
  return `${list} ${all.length === 1 ? 'is' : 'are'} watching`
}

/** "KQ4MT7RA" as it's typed: "KQ4M-T7RA". */
export const prettyCode = (c: string) => c.replace(/[^a-z0-9]/gi, '').toUpperCase().replace(/^(.{4})(.+)$/, '$1-$2')

/** "9:52": what's left of a ten-minute code. */
export function codeLeft(expires: number, now: number): string {
  const s = Math.max(0, Math.round(expires - now))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// ── the box's own name (GET /bench/box/remote) ──

export interface BoxRemote { on: boolean; name: string | null; address: string | null; open: boolean; carried: boolean; link: 'off' | 'waiting' | 'on' | string }

/** Care's From away row: whether the bench can be reached from outside, said plainly. */
export function remoteRow(r: BoxRemote): { title: string; line: string; button: 'Turn on' | 'Turn off'; on: boolean; needsCode: boolean } {
  const title = 'From away'
  if (!r.on) {
    return { title, on: false, button: 'Turn on', needsCode: !r.address,
             line: r.address ? `Off. ${r.address} is kept for when it's on; phones away and invite links don't reach the bench.`
               : "Off. Phones away and invite links can't reach the bench. The first time, it needs an invite code from Elyir." }
  }
  if (!r.address) return { title, on: true, button: 'Turn off', needsCode: true, line: "On, but it has no name yet. It needs an invite code from Elyir." }
  if (r.link === 'on') return { title, on: true, button: 'Turn off', needsCode: false, line: `On, at ${r.address}. Phones added here, and people you invite, reach the bench there.` }
  return { title, on: true, button: 'Turn off', needsCode: false, line: `${r.address} isn't reachable yet. The box tries again every minute.` }
}
