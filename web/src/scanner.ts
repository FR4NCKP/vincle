// Escáner QR dentro de la app. Usa BarcodeDetector cuando existe (Android) y jsQR como
// respaldo (iPhone), cargado solo al abrir la cámara.

const SCAN_EVERY_MS = 200

export function pinFromQr(text: string): string | null {
  // El QR de la PC trae la URL de la app con el PIN tras '#'; también se acepta solo el PIN.
  return /(?:#|^)(\d{6})$/.exec(text.trim())?.[1] ?? null
}

export async function startScanner(video: HTMLVideoElement, onPin: (pin: string) => void): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment' },
    audio: false,
  })
  video.srcObject = stream
  video.hidden = false
  await video.play()

  const Detector = (window as unknown as { BarcodeDetector?: new (o: object) => { detect(v: CanvasImageSource): Promise<{ rawValue: string }[]> } }).BarcodeDetector
  const detector = Detector ? new Detector({ formats: ['qr_code'] }) : null
  const jsQR = detector ? null : (await import('jsqr')).default
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!

  let stopped = false
  let timer = 0

  async function tick() {
    if (stopped) return
    let text: string | null = null
    try {
      if (detector) {
        text = (await detector.detect(video))[0]?.rawValue ?? null
      } else if (jsQR && video.videoWidth) {
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
        ctx.drawImage(video, 0, 0)
        const img = ctx.getImageData(0, 0, canvas.width, canvas.height)
        text = jsQR(img.data, img.width, img.height, { inversionAttempts: 'dontInvert' })?.data ?? null
      }
    } catch {
      // Un cuadro ilegible no detiene el escaneo.
    }
    const pin = text && pinFromQr(text)
    if (pin && !stopped) {
      stop()
      onPin(pin)
      return
    }
    timer = window.setTimeout(tick, SCAN_EVERY_MS)
  }

  function stop() {
    stopped = true
    clearTimeout(timer)
    stream.getTracks().forEach((t) => t.stop())
    video.srcObject = null
    video.hidden = true
  }

  void tick()
  return stop
}
