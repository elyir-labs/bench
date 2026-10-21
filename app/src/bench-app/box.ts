// The box itself, at the foot of its Care (design/power/, A: Turn off with Restart; design/role/, B: the way back,
// Make it a printer). The service side is bench/box.py. Pure words and rules here, so tests/bench-box-care.test.ts
// can pin them; pages/CarePage.vue draws them.

export interface BoxRole { state: 'switching' | 'failed'; progress: { step: string; done: number; of: number } | null; why: string | null }
export type BoxUpdate = { state: 'updating'; line: string } | { state: 'failed'; why: string }
/** A card's OS (bench/box.py): what it runs, the newest out (null offline), an update started from here. */
export interface BoxOs { version: string; latest: string | null; update: BoxUpdate | null }
export interface BoxKey { id: string; kind: string; name: string }
export interface BoxInfo { power: boolean; role: BoxRole | null; os?: BoxOs | null; ssh?: { user: string; keys: BoxKey[] } }
export type BoxPower = 'off' | 'restart'

export const BOX_HEAD = 'This box'
export const POWER_ROW = { title: 'Turn off', line: 'Your printers keep going without it. It can only be switched on again at the box.' }
export const ROLE_ROW = { title: 'This is a Bench Box', line: "It can be a printer instead: Klipper comes back on, and its screen shows a new printer's setup." }

export function powerAsk(kind: BoxPower, name: string): { title: string; line: string; go: string } {
  return kind === 'off'
    ? { title: `Turn off ${name}?`, line: 'Your printers keep going without it. It can only be switched on again at the box.', go: 'Turn off' }
    : { title: `Restart ${name}?`, line: "Your printers keep going. It's back in about a minute.", go: 'Restart' }
}

export const ROLE_ASK = {
  title: 'Make this a printer?',
  line: "It stops looking after your printers, and they carry on as they are. Klipper and Moonraker come back on, and its screen shows a new printer's setup.",
  keep: 'Keep it a Bench Box', go: 'Make it a printer',
}

export const UPDATE_ASK = {
  title: 'Update now?',
  line: "It downloads the new version (about 900 MB) and restarts into it. Your printers keep going. If it doesn't start properly, it goes back to this one by itself.",
  keep: 'Not now', go: 'Update now',
}

/** The update row: what it runs, and whether there's newer (it also looks by itself at night). */
export function osRow(o: BoxOs): { title: string; line: string; newer: boolean } {
  const newer = !!o.latest && o.latest !== o.version
  const line = newer ? `${o.latest} is out. This box runs ${o.version}.`
    : o.latest ? `Up to date: ${o.version}. It updates by itself at night.`
    : `It runs ${o.version}, and looks for a new one by itself at night.`
  return { title: 'Updates', line, newer }
}

export const SSH_ADD = {
  title: 'Add an SSH key',
  line: 'Paste your public key: one line starting with ssh-ed25519 or ssh-rsa, from a file like ~/.ssh/id_ed25519.pub. Never the private key.',
  keep: 'Cancel', go: 'Add',
}

/** The SSH row: a card's user has no password, so a key is the only way in from a computer. */
export function sshRow(user: string, keys: BoxKey[]): { title: string; line: string } {
  return {
    title: 'SSH',
    line: keys.length ? `${keys.length === 1 ? 'This key signs' : `These ${keys.length} keys sign`} in as ${user}, from a computer on your Wi-Fi.`
      : `Add your public key to sign in as ${user} from a computer on your Wi-Fi. There's no password.`,
  }
}

/** After Turn off or Restart was said yes to: what the page says until the box goes quiet. */
export function powerGoing(kind: BoxPower, name: string): string {
  const who = name.charAt(0).toUpperCase() + name.slice(1)
  return kind === 'off' ? `${who} is turning off. When its screen goes dark, switch it off.` : `${who} is restarting. Back in about a minute.`
}

/** `elyir-bench role printer`'s steps, in its order (installer ROLE_STEPS["printer"]). */
export const ROLE_STEPS = ['Klipper and Moonraker on', 'The printer app', 'Its screen']

export function roleSteps(r: BoxRole | null): { label: string; status: 'ok' | 'now' | 'todo' }[] {
  const done = r?.progress?.done ?? 0
  return ROLE_STEPS.map((label, i) => ({ label, status: i < done ? 'ok' : i === done ? 'now' : 'todo' }))
}

export async function boxInfo(): Promise<BoxInfo | null> {
  try {
    const r = await fetch('/bench/box', { cache: 'no-store' })
    return r.ok ? ((await r.json()) as BoxInfo) : null
  } catch {
    return null
  }
}

export async function boxPost(path: 'power' | 'role' | 'update' | 'ssh', body: Record<string, unknown> = {}): Promise<string | null> {
  try {
    const r = await fetch(`/bench/box/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    return r.ok ? null : (await r.text()) || "The box didn't take it."
  } catch {
    return "The box didn't answer."
  }
}

export async function removeKey(id: string): Promise<string | null> {
  try {
    const r = await fetch(`/bench/box/ssh/${encodeURIComponent(id)}`, { method: 'DELETE' })
    return r.ok ? null : (await r.text()) || "The box didn't take it."
  } catch {
    return "The box didn't answer."
  }
}
