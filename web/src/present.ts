import { send } from './net'
import { createStream, pointerGain } from './pad'
import { replay } from './motion'

/**
 * Modo presentación: pasar diapositivas con las teclas que mandan los presentadores
 * inalámbricos (AvPág / RePág, que entienden PowerPoint, Google Slides, Canva y los visores
 * de PDF) y un puntero láser que solo se ve en la PC mientras el dedo está en la zona láser.
 */
export function setupPresent(els: {
  laserPad: HTMLElement
  laserDot: HTMLElement
  buttons: HTMLElement
}) {
  const { laserPad, laserDot, buttons } = els
  const aim = createStream('laser_move')
  let pointerId: number | null = null
  let last = { x: 0, y: 0 }

  buttons.addEventListener('click', (e) => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('button[data-key]')
    const key = btn?.dataset.key
    if (!btn || !key) return
    send({ event: 'key', payload: { key, ctrl: false } })
    navigator.vibrate?.(10)
    if (btn.classList.contains('tile')) replay(btn, 'flash')
  })

  laserPad.addEventListener('pointerdown', (e) => {
    if (pointerId !== null) return // un solo dedo maneja el láser
    e.preventDefault()
    laserPad.setPointerCapture(e.pointerId)
    pointerId = e.pointerId
    last = { x: e.clientX, y: e.clientY }
    laserPad.classList.add('on')
    placeDot(e.clientX, e.clientY)
    send({ event: 'laser', payload: { on: true } })
  })

  laserPad.addEventListener('pointermove', (e) => {
    if (e.pointerId !== pointerId) return
    const dx = e.clientX - last.x
    const dy = e.clientY - last.y
    last = { x: e.clientX, y: e.clientY }
    const gain = pointerGain(dx, dy)
    aim.add(dx * gain, dy * gain)
    placeDot(e.clientX, e.clientY)
  })

  function end(e: PointerEvent) {
    if (e.pointerId !== pointerId) return
    pointerId = null
    aim.flush()
    laserPad.classList.remove('on')
    send({ event: 'laser', payload: { on: false } })
  }
  laserPad.addEventListener('pointerup', end)
  laserPad.addEventListener('pointercancel', end)
  laserPad.addEventListener('contextmenu', (e) => e.preventDefault())

  function placeDot(x: number, y: number) {
    const r = laserPad.getBoundingClientRect()
    laserDot.style.left = `${x - r.left}px`
    laserDot.style.top = `${y - r.top}px`
  }
}

// Mientras se presenta, la pantalla del celular no debe apagarse sola.
let wakeLock: WakeLockSentinel | null = null

export async function keepScreenOn(on: boolean) {
  if (!on) {
    await wakeLock?.release().catch(() => {})
    wakeLock = null
    return
  }
  if (!('wakeLock' in navigator) || wakeLock) return
  try {
    const lock = await navigator.wakeLock.request('screen')
    wakeLock = lock
    // El sistema lo suelta solo al salir de la app; así se puede volver a pedir.
    lock.addEventListener('release', () => { if (wakeLock === lock) wakeLock = null })
  } catch {
    // Sin permiso o sin soporte: el celular se apagará según su configuración.
  }
}
