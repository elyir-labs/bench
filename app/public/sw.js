// Elyir Bench service worker: shows the printer's notifications and opens the app when one is tapped.
// No offline caching; the app needs the printer anyway.
// Payload (from the door): {title, body, tag, url, urgency}

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = { body: event.data && event.data.text() } }
  const title = data.title || 'Your printer'
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || '',
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),          // a replacement still buzzes
    requireInteraction: data.urgency === 'high',   // stays up until someone deals with it
    icon: '/icons/icon-192.png',
    badge: '/icons/badge-96.png',
    data: { url: data.url || '/' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const c of open) {
      if (new URL(c.url).origin === self.location.origin) {
        await c.focus()
        if ('navigate' in c && c.url !== target) await c.navigate(target).catch(() => {})
        return
      }
    }
    await self.clients.openWindow(target)
  })())
})
