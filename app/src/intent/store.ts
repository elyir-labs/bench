// Pinia store: where the app gets its one intent object from.
//
// Which printer to talk to, in order of precedence:
//   1. ?printer=host:port in the URL   (handy for the phone and for demos)
//   2. VITE_MOONRAKER_URL              (npm run dev:sim sets this to the simulator)
//   3. public/config.json moonraker host/port
//   4. the host the page was served from (the kiosk case: nginx on the Pi)

import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { IntentClient, endpointFor, type PrinterEndpoint } from './client'
import type { Intent, IntentAction, HistoryJob, PrintCheck } from './types'
import { allowedHere, door } from '@/door'
import { embedded, withToken } from '@/auth'
import { sourceOf } from './source'
import { needsSheet } from './colour'
import { isPanel } from '@/theme'
import { demoBase } from '@/demo/socket'
import { BASE } from '@/base'

function resolveEndpoint(configHost?: string, configPort?: number, configSsl?: boolean): PrinterEndpoint {
  if (import.meta.env.VITE_DEMO === '1') return { http: demoBase().replace(/\/$/, ''), ws: 'demo' }   // the printer is in the page
  const q = new URLSearchParams(window.location.search).get('printer')
  if (q) {
    const [host, port] = q.split(':')
    return endpointFor(host, port ? Number(port) : 7125)
  }
  const env = import.meta.env.VITE_MOONRAKER_URL as string | undefined
  if (env) {
    const u = new URL(env)
    return endpointFor(u.hostname, Number(u.port || (u.protocol === 'https:' ? 443 : 80)), u.protocol === 'https:')
  }
  if (configHost && configHost !== '127.0.0.1' && configHost !== 'localhost') {
    return endpointFor(configHost, configPort ?? 7125, configSsl ?? false)
  }
  const loc = window.location
  const here = endpointFor(loc.hostname, loc.port ? Number(loc.port) : (loc.protocol === 'https:' ? 443 : 7125), loc.protocol === 'https:')
  return BASE ? { http: here.http + BASE, ws: here.ws.replace(/\/websocket$/, `${BASE}/websocket`) } : here
}

export const useIntentStore = defineStore('intent', () => {
  const client = shallowRef<IntentClient | null>(null)
  const intent = computed<Intent | null>(() => client.value?.intent.value ?? null)
  const connected = computed(() => client.value?.connected.value ?? false)
  const busyAction = ref<string | null>(null)
  const actionError = ref<string | null>(null)
  const lastJob = ref<HistoryJob | null>(null)

  /** URL for a path under Moonraker's gcodes root, e.g. a slicer thumbnail. */
  function fileUrl(path: string | null | undefined): string | null {
    if (!path || !client.value) return null
    if (import.meta.env.VITE_DEMO === '1') return `${demoBase()}thumbs/${encodeURIComponent(path.split('/').pop()!)}`
    return withToken(`${client.value.endpoint.http}/server/files/gcodes/${path.split('/').map(encodeURIComponent).join('/')}`)
  }
  /** Largest slicer preview from a history entry's metadata. */
  function thumbOf(job: HistoryJob | null | undefined): string | null {
    const thumbs = (job?.metadata?.thumbnails as { width?: number; height?: number; relative_path?: string }[] | undefined) ?? []
    let best: { area: number; path: string } | null = null
    for (const t of thumbs) {
      if (!t.relative_path) continue
      const area = (t.width ?? 0) * (t.height ?? 0)
      if (!best || area > best.area) best = { area, path: t.relative_path }
    }
    if (!best || !job) return null
    const folder = job.filename.includes('/') ? job.filename.slice(0, job.filename.lastIndexOf('/')) + '/' : ''
    return fileUrl(folder + best.path)
  }

  /** Moonraker notifications, e.g. notify_webcams_changed. Safe to call before start(). */
  const subscribers: [string, (params: any[]) => void][] = []
  function on(method: string, fn: (params: any[]) => void) {
    subscribers.push([method, fn])
    client.value?.on(method, fn)
  }

  function start(configHost?: string, configPort?: number, configSsl?: boolean) {
    if (client.value) return
    const c = new IntentClient(resolveEndpoint(configHost, configPort, configSsl))
    for (const [m, fn] of subscribers) c.on(m, fn)
    c.connect()
    client.value = c
    // The Ready screen shows the last thing printed; refresh it whenever a job ends.
    const refreshLast = async () => { lastJob.value = (await recentJobs(1))[0] ?? null }
    c.on('notify_history_changed', refreshLast)
    let wasConnected = false
    setInterval(() => {
      const now = c.connected.value
      if (now && !wasConnected) refreshLast()
      wasConnected = now
    }, 500)
  }

  async function act(action: IntentAction | string, args?: Record<string, unknown>) {
    const id = typeof action === 'string' ? action : action.id
    const a = typeof action === 'string' ? args ?? {} : { ...(action.args ?? {}), ...(args ?? {}) }
    if (!client.value) return
    if (!allowedHere(id)) {   // the door would refuse it; say so instead of asking
      actionError.value = 'That has to be done at the printer.'
      return
    }
    busyAction.value = id
    actionError.value = null
    try {
      await client.value.act(id, a, sourceOf({ embedded, panel: isPanel, away: door.away }))
    } catch (e: any) {
      actionError.value = e?.message ?? String(e)
    } finally {
      busyAction.value = null
    }
  }

  /** Plain Moonraker call, for the few things that aren't intent (e.g. stored settings). */
  function call<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    if (!client.value) return Promise.reject(new Error('Not connected'))
    return client.value.call<T>(method, params)
  }

  async function recentJobs(limit = 12): Promise<HistoryJob[]> {
    if (!client.value) return []
    try {
      const r = await client.value.call<{ jobs: HistoryJob[] }>('server.history.list', { limit, order: 'desc' })
      return r?.jobs ?? []
    } catch {
      return []
    }
  }

  /** Is what this file needs loaded? Never starts anything. A printer whose intent
   *  layer predates the check has nothing to say, which counts as fine. */
  async function checkPrint(filename: string): Promise<PrintCheck> {
    if (!client.value) return { ok: true, filename, missing: [] }
    try {
      return await client.value.call<PrintCheck>('printer.intent.check_print', { filename })
    } catch {
      return { ok: true, filename, missing: [] }
    }
  }

  /** Start a file, unless the check says something's missing: then hand the refusal
   *  back for the screen to show, and start nothing. */
  async function requestPrint(filename: string): Promise<PrintCheck> {
    const check = await checkPrint(filename)
    if (!needsSheet(check)) await startPrint(filename)   // colour changes are planned on a sheet first
    return check
  }

  /** Start without checking (after "Print anyway"). */
  async function startPrint(filename: string) {
    await act('start_file', { filename })
  }

  /** Colour and material for a spool without a tag. */
  async function setSpool(slot: number, color: string, material: string) {
    await act('set_spool', { slot, color, material })
  }

  async function fileMetadata(filename: string): Promise<Record<string, any> | null> {
    if (!client.value) return null
    try {
      return await client.value.call('server.files.metadata', { filename })
    } catch {
      return null
    }
  }

  /** Anything but Ready: the printer is doing something or waiting on a person. */
  const busy = computed(() => !!intent.value && intent.value.state !== 'ready')

  const endpoint = computed(() => client.value?.endpoint ?? null)
  const advancedUrl = computed(() => {
    const fromPrinter = intent.value?.printer?.advanced_url
    if (fromPrinter && fromPrinter !== '/') return fromPrinter
    const ep = endpoint.value
    if (!ep) return '/'
    // Mainsail lives on port 80 of the same host by default
    return ep.http.replace(/:\d+$/, '') + '/'
  })

  return { start, on, act, call, recentJobs, startPrint, checkPrint, requestPrint, setSpool, fileMetadata, fileUrl, thumbOf, lastJob, busy, intent, connected, busyAction, actionError, endpoint, advancedUrl }
})
