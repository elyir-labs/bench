// Last time's answer, kept on this device so a page can open with it while it checks (design/loading/, B + A).
// Kept per account, and only for so long: an older one is not shown, and the page draws its shape instead.

export const WEEK = 7 * 24 * 3600 * 1000

interface Kept<T> { who: string; at: number; value: T }

export function recall<T>(store: Pick<Storage, 'getItem'> | null, key: string, who: string, maxAge: number, now = Date.now()): T | null {
  try {
    const k = JSON.parse(store?.getItem(key) ?? 'null') as Kept<T> | null
    if (!k || k.who !== who || typeof k.at !== 'number' || k.value == null) return null
    return now - k.at >= 0 && now - k.at < maxAge ? k.value : null
  } catch {
    return null
  }
}

export function keep<T>(store: Pick<Storage, 'setItem' | 'removeItem'> | null, key: string, who: string, value: T | null, now = Date.now()): void {
  try {
    if (value == null) store?.removeItem(key)
    else store?.setItem(key, JSON.stringify({ who, at: now, value } satisfies Kept<T>))
  } catch {
    // private browsing or a full store: the page draws its shape next time
  }
}
