// Reads a QR code from the camera's current frame. The browser's own BarcodeDetector where there is
// one (Chrome on Android and macOS), otherwise jsQR: plain JavaScript, bundled into its own chunk and
// loaded only when Scan is tapped. iOS Safari has no BarcodeDetector, and the relay's CSP for
// printers.elyir.app allows no CDN, no wasm and no eval, which jsQR needs none of.

interface Detector { detect(source: CanvasImageSource): Promise<{ rawValue: string }[]> }
interface DetectorClass {
  new (opts: { formats: string[] }): Detector
  getSupportedFormats?(): Promise<string[]>
}

const MAX_SIDE = 720   // jsQR on a whole 1080p frame is slow on a phone; a code fills enough of this

export async function frameReader(video: HTMLVideoElement): Promise<() => Promise<string | null>> {
  const ready = () => video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0

  const BD = (globalThis as { BarcodeDetector?: DetectorClass }).BarcodeDetector
  if (BD) {
    try {
      const formats = (await BD.getSupportedFormats?.()) ?? ['qr_code']
      if (formats.includes('qr_code')) {
        const detector = new BD({ formats: ['qr_code'] })
        return async () => (ready() ? (await detector.detect(video))[0]?.rawValue ?? null : null)
      }
    } catch {
      // a detector that can't start: fall through to jsQR
    }
  }

  const { default: jsQR } = await import('jsqr')
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  return async () => {
    if (!ctx || !ready()) return null
    const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight))
    const w = Math.round(video.videoWidth * scale)
    const h = Math.round(video.videoHeight * scale)
    if (canvas.width !== w) canvas.width = w
    if (canvas.height !== h) canvas.height = h
    ctx.drawImage(video, 0, 0, w, h)
    const img = ctx.getImageData(0, 0, w, h)
    // both: the panel draws its code dark-on-light, but a dark theme or a glare can flip it
    return jsQR(img.data, w, h, { inversionAttempts: 'attemptBoth' })?.data ?? null
  }
}
