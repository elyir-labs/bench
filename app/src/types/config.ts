// Configuration types for Elyir Bench
export interface AppConfig {
  moonraker: MoonrakerConfig
  display: DisplayConfig
  preheat: Record<string, PreheatPreset>
  movement: MovementConfig
  extrusion: ExtrusionConfig
  print: PrintConfig
  webcam: WebcamConfig
  macros: MacrosConfig
  graphs: GraphsConfig
  bedMesh: BedMeshConfig
  advanced: AdvancedConfig
  ui: UIConfig
  notifications: NotificationsConfig
  power: PowerConfig
  system: SystemConfig
  zOffset: ZOffsetConfig
  experimental: ExperimentalConfig
  // Backward compatibility
  moveDistances?: number[]
  extrudeDistances?: number[]
  printers?: PrinterConfig[]
}

export interface MoonrakerConfig {
  host: string
  port: number
  ssl: boolean
  apiKey?: string
  instances?: PrinterConfig[]
}

export interface DisplayConfig {
  theme: 'material-dark' | 'material-light'
  language: string
  use24HourTime: boolean
  confirmEstop: boolean
  confirmPowerOff?: boolean
  screenSaverTimeout?: number // minutes
  fontScale?: number
  // Backward compatibility
  width?: number
  height?: number
  showHeaterPower?: boolean
  screenTimeout?: number
}

export interface PreheatPreset {
  name?: string
  bed?: number
  extruder?: number
  chamber?: number
}

export interface MovementConfig {
  distances: number[]
  defaultSpeed: number
  zHop?: number
  invertX?: boolean
  invertY?: boolean
  invertZ?: boolean
}

export interface ExtrusionConfig {
  distances: number[]
  defaultSpeed: number
  minExtrudeTemp: number
}

export interface PrintConfig {
  autoStartAfterUpload: boolean
  showThumbnailPreview: boolean
  confirmBeforeStart: boolean
  fileSortOrder: 'name' | 'date' | 'size'
  showFileSize: boolean
}

export interface WebcamConfig {
  enabled: boolean
  url: string
  rotation: 0 | 90 | 180 | 270
  flipHorizontal: boolean
  flipVertical: boolean
}

export interface MacrosConfig {
  favorites: string[]
  hidden: string[]
  categories: Record<string, string[]>
}

export interface GraphsConfig {
  temperature: {
    updateInterval: number
    timeWindow: number
    showPower: boolean
    autoScale: boolean
    minTemp?: number
    maxTemp?: number
  }
}

export interface BedMeshConfig {
  showOnHome: boolean
  visualizationType: 'heatmap' | '3d' | 'wireframe'
  colorScheme: 'viridis' | 'plasma' | 'inferno' | 'magma' | 'jet'
  showProbePoints: boolean
}

export interface AdvancedConfig {
  printerQueryInterval: number
  temperatureQueryInterval: number
  fileListCacheTime: number
  developerMode: boolean
  verboseLogging: boolean
  enableTabSync: boolean
  retryFailedRequests: boolean
  maxRetries: number
}

export interface UIConfig {
  homeLayout: 'compact' | 'spacious' | 'custom'
  showConnectionStatus: boolean
  showClock: boolean
  footerButtons: string[]
  colors?: {
    primary?: string
    secondary?: string
    accent?: string
    positive?: string
    negative?: string
  }
}

export interface NotificationsConfig {
  printComplete: boolean
  printFailed: boolean
  filamentRunout: boolean
  enableSound: boolean
  browserNotifications: boolean
}

export interface PowerConfig {
  devices: PowerDevice[]
  autoOffAfterPrint: number
  autoOffIfIdle: number
}

export interface PowerDevice {
  name: string
  device: string
}

export interface SystemConfig {
  allowRestart: boolean
  allowShutdown: boolean
  allowReboot: boolean
  confirmSystemCommands: boolean
}

export interface ZOffsetConfig {
  increments: number[]
  autoSave: boolean
}

export interface ExperimentalConfig {
  enabled: boolean
  features: string[]
}

export interface PrinterConfig {
  name: string
  host: string
  port: number
  ssl?: boolean
  apiKey?: string
}

export const DEFAULT_CONFIG: AppConfig = {
  moonraker: {
    host: '127.0.0.1',
    port: 7125,
    ssl: false
  },
  display: {
    theme: 'material-dark',
    language: 'en',
    use24HourTime: true,
    confirmEstop: true,
    confirmPowerOff: true,
    screenSaverTimeout: 10,
    fontScale: 1.0,
    width: 800,
    height: 480,
    showHeaterPower: false,
    screenTimeout: 600
  },
  preheat: {
    PLA: { bed: 60, extruder: 200, chamber: 0 },
    PETG: { bed: 80, extruder: 230, chamber: 0 },
    ABS: { bed: 90, extruder: 245, chamber: 40 },
    FLEX: { bed: 50, extruder: 210, chamber: 0 }
  },
  movement: {
    distances: [0.1, 0.5, 1, 5, 10, 25, 50],
    defaultSpeed: 100,
    zHop: 0,
    invertX: false,
    invertY: false,
    invertZ: false
  },
  extrusion: {
    distances: [5, 10, 25, 50, 100],
    defaultSpeed: 5,
    minExtrudeTemp: 170
  },
  print: {
    autoStartAfterUpload: false,
    showThumbnailPreview: true,
    confirmBeforeStart: true,
    fileSortOrder: 'date',
    showFileSize: true
  },
  webcam: {
    enabled: false,
    url: 'http://127.0.0.1:8080/?action=stream',
    rotation: 0,
    flipHorizontal: false,
    flipVertical: false
  },
  macros: {
    favorites: ['LOAD_FILAMENT', 'UNLOAD_FILAMENT', 'PURGE_LINE', 'CLEAN_NOZZLE'],
    hidden: ['_TOOLHEAD_PARK_PAUSE_CANCEL', '_CLIENT_VARIABLE'],
    categories: {
      Filament: ['LOAD_FILAMENT', 'UNLOAD_FILAMENT'],
      Calibration: ['BED_MESH_CALIBRATE', 'Z_TILT_ADJUST', 'PID_CALIBRATE_BED', 'PID_CALIBRATE_HOTEND'],
      Maintenance: ['CLEAN_NOZZLE', 'PURGE_LINE']
    }
  },
  graphs: {
    temperature: {
      updateInterval: 1,
      timeWindow: 10,
      showPower: true,
      autoScale: false,
      minTemp: 0,
      maxTemp: 300
    }
  },
  bedMesh: {
    showOnHome: true,
    visualizationType: 'heatmap',
    colorScheme: 'viridis',
    showProbePoints: true
  },
  advanced: {
    printerQueryInterval: 500,
    temperatureQueryInterval: 1000,
    fileListCacheTime: 30,
    developerMode: false,
    verboseLogging: false,
    enableTabSync: true,
    retryFailedRequests: true,
    maxRetries: 3
  },
  ui: {
    homeLayout: 'spacious',
    showConnectionStatus: true,
    showClock: true,
    footerButtons: ['home', 'temperature', 'movement', 'print', 'macros', 'settings']
  },
  notifications: {
    printComplete: true,
    printFailed: true,
    filamentRunout: true,
    enableSound: false,
    browserNotifications: true
  },
  power: {
    devices: [
      { name: 'Printer', device: 'printer' },
      { name: 'LED Lights', device: 'leds' }
    ],
    autoOffAfterPrint: 0,
    autoOffIfIdle: 0
  },
  system: {
    allowRestart: true,
    allowShutdown: true,
    allowReboot: true,
    confirmSystemCommands: true
  },
  zOffset: {
    increments: [0.01, 0.05, 0.1],
    autoSave: true
  },
  experimental: {
    enabled: false,
    features: []
  },
  // Backward compatibility
  moveDistances: [0.1, 0.5, 1, 5, 10, 25, 50],
  extrudeDistances: [5, 10, 25, 50, 100]
}
