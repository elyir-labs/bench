// Pinia store for Elyir Bench configuration
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import yaml from 'js-yaml'
import type { AppConfig, PreheatPreset, PrinterConfig } from '@/types/config'
import { DEFAULT_CONFIG } from '@/types/config'
import { BASE } from '@/base'

export const useConfigStore = defineStore('config', () => {
  // Configuration
  const config = ref<AppConfig>(DEFAULT_CONFIG)

  // Moonraker connection
  const moonrakerHost = computed(() => config.value.moonraker.host)
  const moonrakerPort = computed(() => config.value.moonraker.port)
  const moonrakerSSL = computed(() => config.value.moonraker.ssl)
  const moonrakerApiKey = computed(() => config.value.moonraker.apiKey)

  // Display settings
  const displayWidth = computed(() => config.value.display.width)
  const displayHeight = computed(() => config.value.display.height)
  const theme = computed(() => config.value.display.theme)
  const language = computed(() => config.value.display.language)
  const use24HourTime = computed(() => config.value.display.use24HourTime)
  const confirmEstop = computed(() => config.value.display.confirmEstop)
  const showHeaterPower = computed(() => config.value.display.showHeaterPower)

  // Preheat presets
  const preheatPresets = computed(() => config.value.preheat)
  const preheatPresetNames = computed(() => Object.keys(config.value.preheat))

  // Move/extrude distances (with backward compatibility)
  const moveDistances = computed(() => config.value.movement?.distances || config.value.moveDistances || DEFAULT_CONFIG.movement.distances)
  const extrudeDistances = computed(() => config.value.extrusion?.distances || config.value.extrudeDistances || DEFAULT_CONFIG.extrusion.distances)

  // Multi-printer support
  const printers = computed(() => config.value.printers || [])
  const hasMultiplePrinters = computed(() => (config.value.printers?.length || 0) > 1)

  // Current printer (for multi-printer setups)
  const currentPrinterIndex = ref(0)
  const currentPrinter = computed(() => {
    if (!config.value.printers || config.value.printers.length === 0) {
      // Use default moonraker connection
      return {
        name: 'Printer',
        host: config.value.moonraker.host,
        port: config.value.moonraker.port,
        ssl: config.value.moonraker.ssl,
        apiKey: config.value.moonraker.apiKey
      }
    }
    return config.value.printers[currentPrinterIndex.value]
  })

  // Actions

  /**
   * Load configuration from YAML, JSON, or localStorage
   */
  async function loadConfig() {
    // Priority 1: Try YAML configuration
    try {
      const yamlResponse = await fetch(`${BASE}/elyir-bench.yaml`)
      if (yamlResponse.ok) {
        const yamlText = await yamlResponse.text()
        const loadedConfig = yaml.load(yamlText) as any
        config.value = mergeConfig(DEFAULT_CONFIG, loadedConfig)
        console.log('[Config] Loaded configuration from /elyir-bench.yaml')
        return
      }
    } catch (error) {
      console.warn('[Config] Could not load /elyir-bench.yaml:', error)
    }

    // Priority 2: Try JSON configuration (backward compatibility)
    try {
      const jsonResponse = await fetch(`${BASE}/config.json`)
      if (jsonResponse.ok) {
        const loadedConfig = await jsonResponse.json() as AppConfig
        config.value = mergeConfig(DEFAULT_CONFIG, loadedConfig)
        console.log('[Config] Loaded configuration from /config.json')
        return
      }
    } catch (error) {
      console.warn('[Config] Could not load /config.json:', error)
    }

    // Priority 3: Fallback to localStorage
    const savedConfig = localStorage.getItem('elyir-bench-config')
    if (savedConfig) {
      try {
        const parsed = JSON.parse(savedConfig) as AppConfig
        config.value = mergeConfig(DEFAULT_CONFIG, parsed)
        console.log('[Config] Loaded configuration from localStorage')
      } catch (error) {
        console.error('[Config] Error parsing localStorage config:', error)
      }
    } else {
      console.log('[Config] Using default configuration')
    }
  }

  /**
   * Deep merge configuration objects
   */
  function mergeConfig(defaults: any, overrides: any): AppConfig {
    const result = { ...defaults }

    for (const key in overrides) {
      if (overrides[key] !== undefined && overrides[key] !== null) {
        if (typeof overrides[key] === 'object' && !Array.isArray(overrides[key])) {
          result[key] = {
            ...(defaults[key] || {}),
            ...overrides[key]
          }
        } else {
          result[key] = overrides[key]
        }
      }
    }

    return result as AppConfig
  }

  /**
   * Save configuration to localStorage
   */
  function saveConfig() {
    localStorage.setItem('elyir-bench-config', JSON.stringify(config.value))
    console.log('[Config] Saved configuration to localStorage')
  }

  /**
   * Update Moonraker connection settings
   */
  function updateMoonrakerConnection(host: string, port: number, ssl: boolean, apiKey?: string) {
    config.value.moonraker = {
      host,
      port,
      ssl,
      apiKey
    }
    saveConfig()
  }

  /**
   * Add preheat preset
   */
  function addPreheatPreset(name: string, preset: PreheatPreset) {
    config.value.preheat[name] = preset
    saveConfig()
  }

  /**
   * Remove preheat preset
   */
  function removePreheatPreset(name: string) {
    delete config.value.preheat[name]
    saveConfig()
  }

  /**
   * Update move distances
   */
  function updateMoveDistances(distances: number[]) {
    config.value.moveDistances = distances
    saveConfig()
  }

  /**
   * Update extrude distances
   */
  function updateExtrudeDistances(distances: number[]) {
    config.value.extrudeDistances = distances
    saveConfig()
  }

  /**
   * Switch to a different printer (multi-printer setup)
   */
  function switchPrinter(index: number) {
    if (config.value.printers && index >= 0 && index < config.value.printers.length) {
      currentPrinterIndex.value = index
      console.log('[Config] Switched to printer:', config.value.printers[index].name)
    }
  }

  /**
   * Add printer to multi-printer list
   */
  function addPrinter(printer: PrinterConfig) {
    if (!config.value.printers) {
      config.value.printers = []
    }
    config.value.printers.push(printer)
    saveConfig()
  }

  /**
   * Remove printer from multi-printer list
   */
  function removePrinter(index: number) {
    if (config.value.printers && index >= 0 && index < config.value.printers.length) {
      config.value.printers.splice(index, 1)
      if (currentPrinterIndex.value >= config.value.printers.length) {
        currentPrinterIndex.value = Math.max(0, config.value.printers.length - 1)
      }
      saveConfig()
    }
  }

  return {
    // State
    config,
    moonrakerHost,
    moonrakerPort,
    moonrakerSSL,
    moonrakerApiKey,
    displayWidth,
    displayHeight,
    theme,
    language,
    use24HourTime,
    confirmEstop,
    showHeaterPower,
    preheatPresets,
    preheatPresetNames,
    moveDistances,
    extrudeDistances,
    printers,
    hasMultiplePrinters,
    currentPrinterIndex,
    currentPrinter,

    // Actions
    loadConfig,
    saveConfig,
    updateMoonrakerConnection,
    addPreheatPreset,
    removePreheatPreset,
    updateMoveDistances,
    updateExtrudeDistances,
    switchPrinter,
    addPrinter,
    removePrinter
  }
})
