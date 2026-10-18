// The shell's own storage on this phone: paired printers (with their tokens), the push key, and the
// models looked at lately (design/look/).
// IndexedDB, because Safari may clear localStorage for Home Screen apps and the key must persist.

const DB = 'printers'
const VERSION = 2

let opening: Promise<IDBDatabase> | null = null
function db(): Promise<IDBDatabase> {
  opening ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, VERSION)
    req.onupgradeneeded = () => {
      const d = req.result
      if (!d.objectStoreNames.contains('printers')) d.createObjectStore('printers', { keyPath: 'id' })
      if (!d.objectStoreNames.contains('kv')) d.createObjectStore('kv')
      if (!d.objectStoreNames.contains('looked')) d.createObjectStore('looked', { keyPath: 'id' })
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  return opening
}

function run<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T> {
  return db().then((d) => new Promise<T>((resolve, reject) => {
    const req = fn(d.transaction(store, mode).objectStore(store))
    req.onsuccess = () => resolve(req.result as T)
    req.onerror = () => reject(req.error)
  }))
}

export const getAll = <T>(store: string) => run<T[]>(store, 'readonly', (s) => s.getAll())
export const put = (store: string, value: unknown, key?: IDBValidKey) => run(store, 'readwrite', (s) => s.put(value, key))
export const del = (store: string, key: IDBValidKey) => run(store, 'readwrite', (s) => s.delete(key))
export const get = <T>(store: string, key: IDBValidKey) => run<T | undefined>(store, 'readonly', (s) => s.get(key))
