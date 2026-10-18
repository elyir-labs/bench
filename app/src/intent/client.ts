// Minimal Moonraker JSON-RPC client for the intent layer.
// One websocket, automatic reconnect, and a single reactive intent object.

import { ref, shallowRef } from 'vue'
import type { Intent } from './types'
import { wsProtocols } from '@/auth'
import { DemoSocket } from '@/demo/socket'

type Pending = { resolve: (v: any) => void; reject: (e: Error) => void }

export interface PrinterEndpoint {
  http: string // e.g. http://workshop.local:7125
  ws: string   // e.g. ws://workshop.local:7125/websocket
}

export function endpointFor(host: string, port: number, ssl = false): PrinterEndpoint {
  const h = port === 80 || port === 443 ? host : `${host}:${port}`
  return {
    http: `${ssl ? 'https' : 'http'}://${h}`,
    ws: `${ssl ? 'wss' : 'ws'}://${h}/websocket`,
  }
}

export class IntentClient {
  readonly intent = shallowRef<Intent | null>(null)
  readonly connected = ref(false)
  readonly lastError = ref<string | null>(null)

  private ws: WebSocket | null = null
  private pending = new Map<number, Pending>()
  private nextId = 1
  private closed = false
  private retryMs = 1000
  private listeners = new Map<string, Set<(params: any[]) => void>>()

  // protocols: the shell passes each printer's own token here; the printer app's comes from auth.ts
  constructor(public endpoint: PrinterEndpoint, private protocols?: string[]) {}

  connect(): void {
    this.closed = false
    this.open()
  }

  close(): void {
    this.closed = true
    this.ws?.close()
    this.ws = null
  }

  on(method: string, fn: (params: any[]) => void): () => void {
    if (!this.listeners.has(method)) this.listeners.set(method, new Set())
    this.listeners.get(method)!.add(fn)
    return () => this.listeners.get(method)?.delete(fn)
  }

  call<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('Not connected'))
        return
      }
      const id = this.nextId++
      this.pending.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({ jsonrpc: '2.0', method, params, id }))
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id)
          reject(new Error(`${method} timed out`))
        }
      }, 15000)
    })
  }

  /** Run an intent action: the button a person pressed. */
  async act(action: string, args: Record<string, unknown> = {}, source?: string): Promise<Intent | null> {
    const r = await this.call<{ intent?: Intent }>('printer.intent.action', source ? { action, args, source } : { action, args })
    if (r?.intent) this.intent.value = r.intent
    return r?.intent ?? null
  }

  private open(): void {
    if (this.closed) return
    let ws: WebSocket
    try {
      // the web demo: a printer simulated in the page (src/demo/socket.ts)
      ws = import.meta.env.VITE_DEMO === '1' ? (new DemoSocket() as unknown as WebSocket) : new WebSocket(this.endpoint.ws, this.protocols ?? wsProtocols())
    } catch (e) {
      this.scheduleRetry()
      return
    }
    this.ws = ws
    ws.onopen = async () => {
      this.connected.value = true
      this.lastError.value = null
      this.retryMs = 1000
      try {
        await this.call('server.connection.identify', {
          client_name: 'elyir-bench', version: '0.1', type: 'display', url: 'https://bench.elyir.com',
        }).catch(() => undefined)
        const intent = await this.call<Intent>('printer.intent')
        this.intent.value = intent
      } catch (e: any) {
        this.lastError.value = e?.message ?? String(e)
      }
    }
    ws.onmessage = (ev) => {
      let msg: any
      try { msg = JSON.parse(ev.data) } catch { return }
      if (msg.id !== undefined && this.pending.has(msg.id)) {
        const p = this.pending.get(msg.id)!
        this.pending.delete(msg.id)
        if (msg.error) p.reject(new Error(msg.error.message || 'Request failed'))
        else p.resolve(msg.result)
        return
      }
      if (msg.method === 'notify_intent_update' && Array.isArray(msg.params)) {
        this.intent.value = msg.params[0] as Intent
      }
      const fns = this.listeners.get(msg.method)
      if (fns) for (const fn of fns) fn(msg.params ?? [])
    }
    ws.onclose = () => {
      this.connected.value = false
      for (const p of this.pending.values()) p.reject(new Error('Connection closed'))
      this.pending.clear()
      this.scheduleRetry()
    }
    ws.onerror = () => {
      this.lastError.value = 'Connection error'
    }
  }

  private scheduleRetry(): void {
    if (this.closed) return
    setTimeout(() => this.open(), this.retryMs)
    this.retryMs = Math.min(this.retryMs * 2, 10000)
  }
}
