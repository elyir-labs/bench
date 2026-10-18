import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Quasar, Notify, Dialog, Loading } from 'quasar'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import router from './router'
import App from './App.vue'

// Import Quasar css
import 'quasar/dist/quasar.css'
import '@quasar/extras/material-icons/material-icons.css'

// Import Design System
import './styles/design-system/index.scss'
import './styles/app.scss'
import './styles/elyir-bench.css'
import './theme'  // sets html[data-theme] before the first paint
import { registerServiceWorker } from './push'
import { embedded } from './auth'

const app = createApp(App)
const pinia = createPinia()

// Configure TanStack Query
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000, // Consider data stale after 1 second
      gcTime: 5 * 60 * 1000, // Keep unused data in cache for 5 minutes (formerly cacheTime)
      refetchOnWindowFocus: false, // Don't refetch on window focus (touchscreen use case)
      retry: 3, // Retry failed requests 3 times
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000), // Exponential backoff
    },
    mutations: {
      retry: 1, // Retry mutations once
    }
  }
})

app.use(pinia)
app.use(router)
app.use(VueQueryPlugin, { queryClient })
app.use(Quasar, {
  plugins: {
    Notify,
    Dialog,
    Loading
  },
  config: {
    brand: {
      primary: '#1A7BE1',    // Electric Blue
      secondary: '#1C2128',  // BG Tertiary
      accent: '#06B6D4',     // Cyan
      dark: '#0F1419',       // BG Primary
      positive: '#10B981',   // Green (Ready)
      negative: '#EF4444',   // Red (Error)
      info: '#06B6D4',       // Cyan
      warning: '#F59E0B'     // Amber (Paused)
    },
    dark: true,
    notify: {}
  }
})

app.mount('#app')
if (!embedded && import.meta.env.VITE_DEMO !== '1') registerServiceWorker()   // where push can work; inside the Printers app, the app does push
