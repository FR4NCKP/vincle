import { send } from './net'
import { replay } from './motion'

const REPEAT_DELAY_MS = 400
const REPEAT_EVERY_MS = 120

/**
 * Control multimedia: las mismas teclas que tienen los teclados con botones de música
 * (reproducir/pausar, pista anterior/siguiente y volumen), que entienden Spotify, YouTube en
 * el navegador, VLC y el propio Windows. Los de volumen se repiten mientras se mantienen.
 */
export function setupMedia(container: HTMLElement) {
  let repeatTimer = 0

  const press = (key: string) => send({ event: 'key', payload: { key, ctrl: false } })

  function stopRepeat() {
    clearTimeout(repeatTimer)
    repeatTimer = 0
  }

  container.addEventListener('pointerdown', (e) => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('button[data-key]')
    if (!btn?.dataset.key) return
    const key = btn.dataset.key
    press(key)
    navigator.vibrate?.(10)
    if (btn.classList.contains('play')) replay(btn, 'pulse')
    if (!btn.hasAttribute('data-repeat')) return
    const again = () => {
      press(key)
      repeatTimer = window.setTimeout(again, REPEAT_EVERY_MS)
    }
    repeatTimer = window.setTimeout(again, REPEAT_DELAY_MS)
  })
  for (const type of ['pointerup', 'pointercancel', 'pointerleave'] as const) {
    container.addEventListener(type, stopRepeat)
  }
  // El teclado (Enter o espacio sobre el botón) también funciona.
  container.addEventListener('keydown', (e) => {
    const btn = (e.target as Element).closest<HTMLButtonElement>('button[data-key]')
    if (btn?.dataset.key && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      press(btn.dataset.key)
    }
  })
  container.addEventListener('contextmenu', (e) => e.preventDefault())
}
