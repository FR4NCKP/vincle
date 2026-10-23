import { isDirect, send } from './net'
import { rippleAt } from './motion'

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
// Dos dedos: si se separan o se juntan más de lo que se desplazan, es zoom.
const PINCH_DECIDE_PX = 16
const SCROLL_DECIDE_PX = 10
const ZOOM_STEP = 1.15 // cada 15 % de cambio en la separación es un paso de la rueda
// Tres dedos: deslizar cambia de ventana o muestra la vista de tareas / el escritorio.
const SWIPE_MIN_PX = 50
// Inercia del desplazamiento: sigue un momento al soltar, frenando poco a poco.
const GLIDE_MIN_SPEED = 0.3 // px/ms
const GLIDE_STOP_SPEED = 0.02
const GLIDE_DECAY_MS = 325
const GLIDE_MAX_PAUSE_MS = 80 // si los dedos se quedaron quietos antes de soltar, no hay inercia

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

  // Dos dedos: qué gesto es (se decide al empezar a moverlos) y desde dónde.
  let twoMode: 'scroll' | 'zoom' | null = null
  let pinchStart = 0
  let zoomRef = 0
  let centerStart = { x: 0, y: 0 }
  // Tres dedos: cuánto se deslizaron en total.
  const swipe = { x: 0, y: 0 }
  // Velocidad del desplazamiento con dos dedos, para la inercia.
  const velocity = { x: 0, y: 0 }
  let lastScrollAt = 0
  let glideFrame = 0

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

  function twoFingers() {
    const [a, b] = [...pointers.values()]
    return { dist: Math.hypot(a.x - b.x, a.y - b.y), cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 }
  }

  function stopGlide() {
    cancelAnimationFrame(glideFrame)
    glideFrame = 0
  }

  function glide(vx: number, vy: number) {
    let last = performance.now()
    const step = (now: number) => {
      const dt = now - last
      last = now
      const k = Math.exp(-dt / GLIDE_DECAY_MS)
      vx *= k
      vy *= k
      scrolls.add(vx * dt * SCROLL_GAIN, vy * dt * SCROLL_GAIN)
      if (Math.hypot(vx, vy) > GLIDE_STOP_SPEED) glideFrame = requestAnimationFrame(step)
      else {
        glideFrame = 0
        scrolls.flush()
      }
    }
    glideFrame = requestAnimationFrame(step)
  }

  surface.addEventListener('pointerdown', (e) => {
    e.preventDefault() // tocar el trackpad no le quita el foco al campo de escritura
    stopGlide() // tocar frena la inercia, como en un trackpad de verdad
    surface.setPointerCapture(e.pointerId)
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY })
    if (pointers.size === 1) {
      maxPointers = 1
      downAt = performance.now()
      isTap = true
      twoMode = null
      swipe.x = swipe.y = 0
      velocity.x = velocity.y = 0
      holdTimer = window.setTimeout(startDrag, HOLD_TO_DRAG_MS)
      ring.classList.remove('idle')
      placeRing(e.clientX, e.clientY)
    } else {
      maxPointers = Math.max(maxPointers, pointers.size)
      clearTimeout(holdTimer)
      if (pointers.size === 2) {
        const { dist, cx, cy } = twoFingers()
        pinchStart = zoomRef = dist
        centerStart = { x: cx, y: cy }
      }
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

    // Un gesto de varios dedos dura hasta soltarlos todos: si se levanta uno antes, el que
    // queda no mueve el cursor ni el de dos dedos pasa a otra cosa.
    if (maxPointers === 1) {
      const gain = pointerGain(dx, dy)
      moves.add(dx * gain, dy * gain)
      placeRing(e.clientX, e.clientY)
    } else if (maxPointers >= 3) {
      swipe.x += dx / pointers.size
      swipe.y += dy / pointers.size
    } else if (pointers.size === 2) {
      const { dist, cx, cy } = twoFingers()
      if (!twoMode) {
        const spread = Math.abs(dist - pinchStart)
        const travel = Math.hypot(cx - centerStart.x, cy - centerStart.y)
        // Al pellizcar con un dedo quieto, la separación cambia el doble de lo que se mueve el
        // centro; al desplazar, los dedos van juntos y la separación casi no cambia.
        if (spread > travel && spread > PINCH_DECIDE_PX) twoMode = 'zoom'
        else if (travel >= spread && travel > SCROLL_DECIDE_PX) twoMode = 'scroll'
      }
      if (twoMode === 'scroll') {
        // Cada dedo aporta su parte: el promedio es el desplazamiento del gesto.
        const sx = (dx / 2) * SCROLL_GAIN, sy = (dy / 2) * SCROLL_GAIN
        scrolls.add(sx, sy)
        const now = performance.now()
        const dt = Math.max(1, now - lastScrollAt)
        lastScrollAt = now
        // Los eventos de los dos dedos se intercalan: (dx / 2) / dt ya es la velocidad del centro.
        velocity.x = velocity.x * 0.8 + (dx / 2 / dt) * 0.2
        velocity.y = velocity.y * 0.8 + (dy / 2 / dt) * 0.2
      } else if (twoMode === 'zoom') {
        const steps = Math.trunc(Math.log(dist / zoomRef) / Math.log(ZOOM_STEP))
        if (steps) {
          zoomRef *= ZOOM_STEP ** steps
          send({ event: 'zoom', payload: { steps } })
          navigator.vibrate?.(5)
        }
      }
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
      const button = maxPointers >= 3 ? 'middle' : maxPointers === 2 ? 'right' : 'left'
      send({ event: 'click', payload: { button } })
      rippleAt(surface, e.clientX, e.clientY, 'tap') // el toque "marca" la superficie
    } else if (maxPointers >= 3 && Math.hypot(swipe.x, swipe.y) > SWIPE_MIN_PX) {
      const name = Math.abs(swipe.x) > Math.abs(swipe.y)
        ? (swipe.x > 0 ? 'right' : 'left')
        : (swipe.y > 0 ? 'down' : 'up')
      send({ event: 'gesture', payload: { name } })
      navigator.vibrate?.(20)
    } else if (twoMode === 'scroll' && performance.now() - lastScrollAt < GLIDE_MAX_PAUSE_MS
      && Math.hypot(velocity.x, velocity.y) > GLIDE_MIN_SPEED) {
      glide(velocity.x, velocity.y)
    }
    ring.classList.add('idle')
  }
  surface.addEventListener('pointerup', end)
  surface.addEventListener('pointercancel', end)
  surface.addEventListener('contextmenu', (e) => e.preventDefault())
}
