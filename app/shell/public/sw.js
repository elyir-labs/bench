// The Printers app's service worker: shows every printer's notifications (one subscription for
// all of them, see src/shell-app/push.ts) and opens the right printer when one is tapped.
// Payload from a printer's door: {title, body, tag, url, urgency, printer}.
// No offline caching: the printers have to be reachable anyway. A model shared in from another app
// (Android's Share, design/look/) is left in the 'look-share' cache for the Look page.

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = { body: event.data && event.data.text() } }
  const printer = typeof data.printer === 'string' ? data.printer : ''
  const path = typeof data.url === 'string' && data.url.startsWith('/') ? data.url : '/'
  event.waitUntil(self.registration.showNotification(data.title || 'Your printer', {
    body: data.body || '',
    // tags are per printer already (workshop-attention, studio-job...), so printers never replace each other's
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    requireInteraction: data.urgency === 'high',
    icon: '/icons/icon-192.png',
    badge: '/icons/badge-96.png',
    data: { target: printer ? `/p/${encodeURIComponent(printer)}#${path}` : '/' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.target || '/', self.location.origin).href
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const c of open) {
      if (new URL(c.url).origin !== self.location.origin) continue
      await c.focus()
      c.postMessage({ type: 'printers:open', target })   // the open app routes without a reload
      return
    }
    await self.clients.openWindow(target)
  })())
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'POST' || url.origin !== self.location.origin || url.pathname !== '/look/share') return
  event.respondWith((async () => {
    const form = await event.request.formData()
    const file = form.getAll('model').find((f) => f && typeof f !== 'string')
    if (file) {
      const cache = await caches.open('look-share')
      await cache.put('/look/shared', new Response(file, { headers: { 'X-Name': encodeURIComponent(file.name || 'model.stl') } }))
    }
    return Response.redirect('/look?shared=1', 303)
  })())
})
