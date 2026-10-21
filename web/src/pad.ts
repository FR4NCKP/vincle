import { isDirect, send } from './net'

// Supabase Free corta la conexión pasados 100 mensajes/s por proyecto, y cada Broadcast
// cuenta como enviado + recibido: ~30 envíos/s deja margen. Por la conexión directa no hay
// cuota, y se manda casi cada evento del dedo (~120/s) para el menor retraso posible.
const SEND_INTERVAL_MS = 33
const DIRECT_SEND_INTERVAL_MS = 8
const TAP_MAX_MS = 250
const TAP_SLOP_PX = 8
const HOLD_TO_DRAG_MS = 400
const BASE_GAIN = 1.5
const SCROLL_GAIN = 1

const SENS_KEY = 'vincle.sensitivity'

export function getSensitivity(): number {
  try {
    const v = Number(localStorage.getItem(SENS_KEY))
    return v >= 0.4 && v <= 3 ? v : 1
  } catch {
    return 1
  }
}

export function setSensitivity(v: number) {
  try { localStorage.setItem(SENS_KEY, String(v)) } catch { /* solo esta sesión */ }
}

/** Aceleración simple: lento = preciso, rápido = recorre la pantalla. */
export function pointerGain(dx: number, dy: number) {
  return BASE_GAIN * getSensitivity() * (1 + Math.min(Math.hypot(dx, dy), 30) / 15)
}

/**
 * Acumula desplazamientos y los manda como mucho cada SEND_INTERVAL_MS (o el intervalo de la
 * conexión directa). Se envía solo la parte entera y el resto se guarda para el siguiente.
 */
export function createStream(event: 'move' | 'scroll' | 'laser_move') {
  let ax = 0, ay = 0
  let lastSend = 0
  let timer = 0

  function flush() {
    clearTimeout(timer)
    timer = 0
    lastSend = performance.now()
    const ix = Math.trunc(ax), iy = Math.trunc(ay)
    if (!ix && !iy) return
    ax -= ix
    ay -= iy
    send({ event, payload: { x: ix, y: iy } })
  }

  function add(dx: number, dy: number) {
    ax += dx
    ay += dy
    if (timer) return
    const interval = isDirect() ? DIRECT_SEND_INTERVAL_MS : SEND_INTERVAL_MS
    timer = window.setTimeout(flush, Math.max(0, lastSend + interval - performance.now()))
  }

  return { add, flush }
}

type Pointer = { x: number; y: number; startX: number; startY: number }

export function setupPad(surface: HTMLElement, ring: HTMLElement) {
  const pointers = new Map<number, Pointer>()
  let maxPointers = 0
  let downAt = 0
  let isTap = false
  let dragging = false
  let holdTimer = 0

  const moves = createStream('move')
  const scrolls = createStream('scroll')

  function placeRing(x: number, y: number) {
    const r = surface.getBoundingClientRect()
    ring.style.left = `${x - r.left}px`
    ring.style.top = `${y - r.top}px`
  }

  function startDrag() {
    holdTimer = 0
    if (pointers.size !== 1 || !isTap) return
    dragging = true
    isTap = false
    ring.classList.add('drag')
    navigator.vibrate?.(15)
    send({ event: 'drag', payload: { down: true } })
  }

  surface.addEventListener('pointerdown', (e) => {
    e.preventDefault() // tocar el trackpad no le quita el foco al campo de escritura
    surface.setPointerCapture(e.pointerId)
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY })
    if (pointers.size === 1) {
      maxPointers = 1
      downAt = performance.now()
      isTap = true
      holdTimer = window.setTimeout(startDrag, HOLD_TO_DRAG_MS)
      ring.classList.remove('idle')
      placeRing(e.clientX, e.clientY)
    } else {
      maxPointers = Math.max(maxPointers, pointers.size)
      clearTimeout(holdTimer)
    }
  })

  surface.addEventListener('pointermove', (e) => {
    const p = pointers.get(e.pointerId)
    if (!p) return
    const dx = e.clientX - p.x
    const dy = e.clientY - p.y
    p.x = e.clientX
    p.y = e.clientY
    if (isTap && Math.hypot(p.x - p.startX, p.y - p.startY) > TAP_SLOP_PX) {
      isTap = false
      clearTimeout(holdTimer)
    }

    if (pointers.size === 1) {
      const gain = pointerGain(dx, dy)
      moves.add(dx * gain, dy * gain)
      placeRing(e.clientX, e.clientY)
    } else {
      // Cada dedo aporta su parte: el promedio es el desplazamiento del gesto.
      scrolls.add((dx / pointers.size) * SCROLL_GAIN, (dy / pointers.size) * SCROLL_GAIN)
    }
  })

  function end(e: PointerEvent) {
    if (!pointers.delete(e.pointerId) || pointers.size > 0) return
    clearTimeout(holdTimer)
    moves.flush()
    scrolls.flush()
    if (dragging) {
      dragging = false
      ring.classList.remove('drag')
      send({ event: 'drag', payload: { down: false } })
    } else if (isTap && performance.now() - downAt < TAP_MAX_MS) {
      send({ event: 'click', payload: { button: maxPointers >= 2 ? 'right' : 'left' } })
    }
    ring.classList.add('idle')
  }
  surface.addEventListener('pointerup', end)
  surface.addEventListener('pointercancel', end)
  surface.addEventListener('contextmenu', (e) => e.preventDefault())
}
