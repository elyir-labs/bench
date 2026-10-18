// The Print tab and the library share one picture of what's on the printer: the files, their
// history, what each one needs (the intent layer's check_print) and what's been removed.
// Refreshed when the socket comes up, when Moonraker says the files or the history changed, and
// when the spools change.
import { computed, ref, shallowRef, watch } from 'vue'
import { useIntentStore } from '@/intent/store'
import type { PrintCheck } from '@/intent/types'
import { door } from '@/door'
import { joinLibrary, shelf, onPrinter, withGhosts, SHELF_NEW, SHELF_RECENT, type Ghost, type Item, type PastJob, type PrinterFile } from './library'
import { hideFromRecent, inBatches, listFiles, loadHidden, pastJobs, removeFile } from './files'

/** How long a drained tile stays after the last touch before the grid closes up. */
export const SETTLE_MS = 4000

const files = shallowRef<PrinterFile[]>([])
const jobs = shallowRef<PastJob[]>([])
const hidden = ref<string[]>([])
const checks = ref<Record<string, PrintCheck>>({})
const loaded = ref(false)
type Place = 'library' | 'recent' | 'fresh'
const ghosts = ref<Record<Place, Ghost[]>>({ library: [], recent: [], fresh: [] })
const now = ref(Date.now() / 1000)

let started = false
let store: ReturnType<typeof useIntentStore>
let reloadTimer = 0
let settleTimer = 0

async function load() {
  const call = store.call
  const [f, j, h] = await Promise.all([listFiles(call).catch(() => null), pastJobs(call), loadHidden(call)])
  if (f) files.value = f
  jobs.value = j
  hidden.value = h
  now.value = Date.now() / 1000
  loaded.value = true
  void refreshChecks()
}

async function refreshChecks() {
  const out: Record<string, PrintCheck> = {}
  await inBatches(files.value.map(f => f.path), 6, async fn => { out[fn] = await store.checkPrint(fn) })
  checks.value = out
}

function reloadSoon() {
  window.clearTimeout(reloadTimer)
  reloadTimer = window.setTimeout(load, 400)
}

/** Drop the drained tiles once nobody has touched the screen for a few seconds. */
function armSettle() {
  window.clearTimeout(settleTimer)
  if (!Object.values(ghosts.value).some(g => g.length)) return
  settleTimer = window.setTimeout(settle, SETTLE_MS)
}
function settle() {
  ghosts.value = { library: [], recent: [], fresh: [] }
}

function start() {
  if (started) return
  started = true
  store = useIntentStore()
  store.on('notify_filelist_changed', reloadSoon)
  store.on('notify_history_changed', reloadSoon)
  if (store.connected) void load()
  watch(() => store.connected, c => { if (c) void load() })
  // spools loaded, swapped or told: what fits changes
  // (not grams: those tick down all through a print)
  watch(() => JSON.stringify((store.intent?.spools ?? []).map(s => [s.slot, s.color, s.material, s.status])),
    () => { if (loaded.value) void refreshChecks() })
  window.addEventListener('pointerdown', armSettle, { passive: true })
  document.addEventListener('visibilitychange', () => { if (document.hidden) settle() })
  window.setInterval(() => { now.value = Date.now() / 1000 }, 30000)
}

export function useLibrary() {
  start()
  const items = computed<Item[]>(() => joinLibrary(files.value, jobs.value))
  const theShelf = computed(() => {
    const s = shelf(items.value, now.value, hidden.value)
    return {
      ...s,
      fresh: withGhosts(s.fresh, ghosts.value.fresh).slice(0, SHELF_NEW),
      recent: withGhosts(s.recent, ghosts.value.recent).slice(0, SHELF_RECENT),
    }
  })
  const library = computed(() => onPrinter(items.value))
  const removed = computed(() => new Set(Object.values(ghosts.value).flat().map(g => g.item.filename)))

  /** Delete from the printer. The tile drains where it stood, in every place it shows; `at` is
   *  its index in the library as filtered on screen. Returns the words for a failure. */
  async function remove(item: Item, at = -1): Promise<string | null> {
    const r = await removeFile(store.call, item.filename, { away: door.away, hidden: hidden.value })
    if (!r.ok) return r.message ?? "It wasn't removed."
    const where = (list: Item[]) => list.findIndex(i => i.filename === item.filename)
    const places: Record<Place, number> = {
      library: at >= 0 ? at : where(library.value),
      recent: where(theShelf.value.recent),
      fresh: where(theShelf.value.fresh),
    }
    const next = { ...ghosts.value }
    for (const p of Object.keys(places) as Place[]) if (places[p] >= 0) next[p] = [...next[p], { item, index: places[p] }]
    ghosts.value = next
    hidden.value = r.hidden ?? hidden.value
    files.value = files.value.filter(f => f.path !== item.filename)
    armSettle()
    return null
  }

  /** A past print whose file is gone, off Recent. */
  async function forget(item: Item) {
    hidden.value = await hideFromRecent(store.call, hidden.value, item.filename)
  }

  return {
    loaded, items, library, checks, now, removed,
    shelf: theShelf,
    /** The library as shown: removed tiles stay drained in place until the screen settles. */
    withRemoved: (list: Item[]) => withGhosts(list, ghosts.value.library),
    remove, forget, reload: load,
  }
}
